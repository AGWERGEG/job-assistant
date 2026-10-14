import json
import hashlib
import hmac
import tempfile
import threading
import unittest
import urllib.request
import urllib.error

from app.bridge import Bridge, normalize_capture, source_identity
from app.server import make_server
from app.store import Problem, Store
from app.version import EXTENSION_ID, EXTENSION_NAME, VERSION

ORIGIN = "chrome-extension://" + EXTENSION_ID
OTHER_ID = EXTENSION_ID[:-1] + ("a" if EXTENSION_ID[-1] != "a" else "b")
OTHER = "chrome-extension://" + OTHER_ID


def capture(key="job0001", text="负责客户需求沟通与产品演示，结合客户场景制定方案，配合技术推进试用并跟进反馈；要求本科，表达清楚。"):
    return {"job_key": key, "url": f"https://www.zhipin.com/job_detail/{key}.html?security_token=discard-me",
            "title": "销售", "company": "虚构测试公司", "jd": text, "method": "dom"}

def foreign_capture(site="zhaopin"):
    host = "jobs.zhaopin.com" if site == "zhaopin" else "hz.58.com"
    return {"job_key":"abc12345", "url":f"https://{host}/jobdetail/abc12345.html", "title":"客户经理", "company":"虚构测试公司", "jd":"负责客户沟通与需求跟进，整理反馈并推动合作落地；要求表达清楚。"*3, "method":"dom", "source_site":site}


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.store.save_profile({"facts": "虚构资料：有产品演示和试用协调经验。"})
        self.bridge = Bridge(self.store)
        code = self.bridge.issue_code()["code"]
        self.token = self.bridge.pair(ORIGIN, {"code": code})["token"]

    def adopt(self, seq, key="job0001", **kwargs):
        return self.bridge.capture(ORIGIN, {"scope": "tab-session", "seq": seq, "capture": capture(key, **kwargs)})

    def test_foreign_site_capture_uses_site_namespace(self):
        first = self.bridge.capture(ORIGIN, {"scope":"foreign", "seq":1, "capture":foreign_capture('zhaopin')})
        self.assertEqual(first['job']['url'], 'https://jobs.zhaopin.com/jobdetail/abc12345.html')
        second = self.bridge.capture(ORIGIN, {"scope":"foreign2", "seq":1, "capture":foreign_capture('58')})
        self.assertEqual(second['job']['url'], 'https://hz.58.com/jobdetail/abc12345.html')
        self.assertNotEqual(first['job']['id'], second['job']['id'])

    def test_foreign_identity_must_match_public_detail_url(self):
        value = foreign_capture("zhaopin")
        value["job_key"] = "different"
        with self.assertRaises(Problem):
            normalize_capture(value)
        value = foreign_capture("58")
        value["url"] = "https://hz.58.com/zpshengchankaifa/67714798680634x.shtml"
        value["job_key"] = "other12345"
        with self.assertRaises(Problem):
            normalize_capture(value)
        self.assertEqual(source_identity("https://hz.58.com/zpshengchankaifa/67714798680634x.shtml"), ("58", "67714798680634x"))

    def test_explicit_company_bind_is_site_scoped_and_cannot_replace_existing_binding(self):
        capture = {**foreign_capture("zhaopin"), "company": "虚构智联公司"}
        unbound = self.bridge.capture(ORIGIN, {"scope":"bind-zhaopin", "seq":1, "capture":capture})["job"]
        self.bridge.companion_action(ORIGIN, {"scope":"bind-zhaopin", "seq":1}, "confirm")
        ref = {"source_site":"zhaopin", "company_key":"zhaopin:CZ123456", "company_url":"https://www.zhaopin.com/companydetail/CZ123456.htm"}
        data = {**ref, "name":"虚构智联公司", "source_url":"https://www.zhaopin.com/companydetail/jobs-CZ123456/?from=joblist"}
        result = self.bridge.companion_action(ORIGIN, {"scope":"bind-zhaopin", "seq":1, "company":data}, "company-bind")
        self.assertEqual(result["company_key"], ref["company_key"])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT company_key FROM job_companies WHERE job_id=?", (unbound["id"],)).fetchone()[0], ref["company_key"])
        with self.assertRaisesRegex(Problem, "智联公司标识与来源链接不一致"):
            self.bridge.companion_action(ORIGIN, {"scope":"bind-zhaopin", "seq":1, "company":{**data, "source_site":"boss"}}, "company-bind")
        other = {**data, "company_key":"zhaopin:CZ654321", "company_url":"https://www.zhaopin.com/companydetail/CZ654321.htm", "source_url":"https://www.zhaopin.com/companydetail/CZ654321.htm"}
        with self.assertRaisesRegex(Problem, "已经关联其他公司"):
            self.bridge.companion_action(ORIGIN, {"scope":"bind-zhaopin", "seq":1, "company":other}, "company-bind")

        boss_job = self.adopt(1)
        self.bridge.companion_action(ORIGIN, {"scope":"tab-session", "seq":1}, "confirm")
        with self.assertRaisesRegex(Problem, "不是同一招聘站点"):
            self.bridge.companion_action(ORIGIN, {"scope":"tab-session", "seq":1, "company":data}, "company-bind")

    def test_restore_keeps_foreign_site_identity(self):
        saved = self.bridge.capture(ORIGIN, {"scope":"restore-source", "seq":1, "capture":foreign_capture("zhaopin")})
        self.bridge.companion_action(ORIGIN, {"scope":"restore-source", "seq":1}, "confirm")
        restored = self.bridge.restore(ORIGIN, {"scope":"restored", "seq":1})
        self.assertEqual(restored["job"]["id"], saved["job"]["id"])
        self.assertEqual(restored["capture"]["job_key"], "abc12345")
        self.assertEqual(restored["capture"]["source_site"], "zhaopin")

    def task(self, seq, **kwargs):
        return self.bridge.task(ORIGIN, {"scope": "tab-session", "seq": seq, "kind": "analyze_job", **kwargs})

    def finish(self, result):
        claimed = self.store.claim(result["task"]["id"])
        self.store.finish(claimed["id"], claimed["claim_token"], {"mode": "agent", "producer": "test", "summary": "建议", "markdown": "依据", "strategy": "演示经验", "primary_output": "先沟通"})

    def test_pair_once_origin_bound_revoke(self):
        self.assertTrue(self.bridge.paired())
        self.assertFalse(Bridge(self.store).paired())  # A saved profile cannot restore a process-local token.
        self.bridge.authenticate(ORIGIN, self.token)
        with self.assertRaises(Problem):
            self.bridge.authenticate(OTHER, self.token)
        with self.assertRaises(Problem):
            self.bridge.pair(ORIGIN, {"code": "bad"})
        self.bridge.revoke_all()
        self.assertFalse(self.bridge.paired())
        with self.assertRaises(Problem):
            self.bridge.authenticate(ORIGIN, self.token)

    def test_server_proof_requires_paired_extension_and_fresh_nonce_shape(self):
        nonce = "ab" * 32
        result = self.bridge.server_proof(ORIGIN, nonce)
        expected = hmac.new(self.token.encode("utf-8"), nonce.encode("ascii"), hashlib.sha256).hexdigest()
        self.assertEqual(result, {"version": VERSION, "nonce": nonce, "proof": expected})
        self.assertNotIn("token", result)
        self.assertNotEqual(result["proof"], self.bridge.server_proof(ORIGIN, "cd" * 32)["proof"])
        for invalid in ("", "ab" * 31, "AB" * 32, "g0" * 32, None):
            with self.subTest(nonce=invalid), self.assertRaises(Problem):
                self.bridge.server_proof(ORIGIN, invalid)
        with self.assertRaises(Problem):
            self.bridge.server_proof(OTHER, nonce)
        self.bridge.revoke_all()
        with self.assertRaises(Problem):
            self.bridge.server_proof(ORIGIN, nonce)

    def test_capture_idempotent_identity_and_tracking_stripped(self):
        a = self.adopt(1)
        b = self.adopt(2)
        self.assertEqual(a["job"]["id"], b["job"]["id"])
        self.assertEqual(b["job"]["revision"], 1)
        self.assertNotIn("?", b["job"]["url"])
        with self.assertRaises(Problem):
            self.adopt(1, "old0001")
        c = self.adopt(3, text=capture()["jd"] + "新增一句要求")
        self.assertEqual(c["job"]["revision"], 2)
        with self.assertRaises(Problem):
            normalize_capture({**capture(), "url": "https://www.zhipin.com/job_detail/other001.html"})
        with self.assertRaises(Problem):
            normalize_capture({**capture(), "url": "https://evil.example/job_detail/job0001.html"})

    def test_unchanged_save_preserves_binding_and_explicit_sync_keeps_edited_jd(self):
        job=self.adopt(1)['job']
        self.bridge.companion_action(ORIGIN,{'scope':'tab-session','seq':1},'confirm')
        original=self.store.state()['jobs'][0]
        same=self.store.save_job(original)
        self.assertEqual(same['revision'],original['revision'])
        self.bridge.companion_action(ORIGIN,{'scope':'tab-session','seq':1},'history')
        edited=self.store.save_job({**original,'jd':original['jd']+'用户核对后的补充'})
        with self.assertRaisesRegex(Problem,'岗位内容已更新'):
            self.bridge.companion_action(ORIGIN,{'scope':'tab-session','seq':1},'history')
        with self.assertRaises(Problem):
            self.bridge.companion_action(ORIGIN,{'scope':'another','seq':1},'sync')
        synced=self.bridge.companion_action(ORIGIN,{'scope':'tab-session','seq':1},'sync')
        self.assertEqual(synced['job']['revision'],edited['revision'])
        self.assertNotIn('jd',synced['job'])
        self.bridge.companion_action(ORIGIN,{'scope':'tab-session','seq':1},'history')
        self.assertEqual(self.store.state()['jobs'][0]['jd'],edited['jd'])

    def test_switch_cancels_old_auto_and_rejects_late_result(self):
        self.adopt(1)
        a = self.task(1, automatic=True)
        self.adopt(2, "job0002")
        self.assertEqual(self.store.get_task(a["task"]["id"])["status"], "cancelled")
        with self.assertRaises(Problem):
            self.bridge.result(ORIGIN, {"scope": "tab-session", "seq": 1, "task_id": a["task"]["id"]})
        with self.assertRaises(Problem):
            self.bridge.result(ORIGIN, {"scope": "tab-session", "seq": 2, "task_id": a["task"]["id"]})

    def test_cache_reuse_and_profile_invalidation(self):
        self.adopt(1)
        a = self.task(1)
        self.assertEqual(self.task(1)["task"]["id"], a["task"]["id"])
        self.finish(a)
        self.adopt(2, "job0002")
        self.adopt(3)
        cached = self.task(3)
        self.assertTrue(cached["cached"])
        self.assertEqual(cached["task"]["id"], a["task"]["id"])
        self.store.save_profile({"facts": "新增真实责任"})
        result = self.bridge.result(ORIGIN, {"scope": "tab-session", "seq": 3, "task_id": a["task"]["id"]})
        self.assertTrue(result["stale"])
        self.assertFalse(self.task(3)["cached"])

    def test_selected_chat_not_persisted_to_job_and_scoped(self):
        self.adopt(1)
        r = self.task(1, kind="suggest_reply", conversation="虚构 HR 消息：有没有相关经验？")
        t = self.store.get_task(r["task"]["id"])
        self.assertIn("虚构 HR", t["context"]["job"]["conversation"])
        self.assertEqual(self.store.state()["jobs"][0]["conversation"], "")
        with self.assertRaises(Problem):
            self.task(1, automatic=True, kind="suggest_reply", conversation="no")

    def test_origin_cors_auth_and_narrow_permissions(self):
        server = make_server(self.tmp.name, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        def req(path, data=None, origin=None, token=None, method=None, local=None):
            headers = {"Content-Type": "application/json"}
            if origin: headers["Origin"] = origin
            if token: headers["X-Bridge-Token"] = token
            if local: headers["X-Local-Token"] = local
            return urllib.request.urlopen(urllib.request.Request(base+path, data=json.dumps(data).encode() if data is not None else None, headers=headers, method=method))
        local = server.session_token
        initial = json.load(req('/api/companion', local=local))
        self.assertEqual(initial['guide']['step'], 'pairing')
        self.assertFalse(initial['extension_paired'])
        discovered=json.load(req('/bridge/discover', {}, origin=ORIGIN))
        self.assertEqual(discovered['pairing'],'confirmation')
        with self.assertRaises(urllib.error.HTTPError):req('/bridge/challenge', {'nonce':'ab'*32}, origin=ORIGIN)
        requested=json.load(req('/bridge/pair-request', {}, origin=ORIGIN))
        info=json.load(req('/api/pair-request-info', {'request_id':requested['request_id']}, local=local))
        self.assertEqual(info['status'],'pending');self.assertNotIn(ORIGIN, json.dumps(info))
        self.assertEqual(info['extension_id'], EXTENSION_ID)
        self.assertEqual(info['extension_name'], EXTENSION_NAME)
        self.assertEqual(info['extension_hint'], f"{EXTENSION_NAME} · {EXTENSION_ID}")
        with self.assertRaises(urllib.error.HTTPError):req('/api/pair-request-approve', {'request_id':requested['request_id'],'confirmed':False}, local=local)
        json.load(req('/api/pair-request-approve', {'request_id':requested['request_id'],'confirmed':True}, local=local))
        auto=json.load(req('/bridge/pair-status', {'request_id':requested['request_id']}, origin=ORIGIN))
        self.assertEqual(auto['status'],'approved');self.assertTrue(auto['token'])
        req('/bridge/disconnect', {}, origin=ORIGIN, token=auto['token'])
        code = json.load(req('/api/extension-code', {}, local=local))['code']
        self.assertEqual(json.load(req('/api/companion', local=local))['guide']['step'], 'pairing')
        for origin in ("https://www.zhipin.com", "null", "https://evil.example"):
            with self.assertRaises(urllib.error.HTTPError): req('/bridge/discover', {}, origin=origin)
            with self.assertRaises(urllib.error.HTTPError): req('/bridge/pair', {"code":code}, origin=origin)
        pair_response = req('/bridge/pair', {"code": code}, origin=ORIGIN)
        self.assertEqual(pair_response.headers['Access-Control-Allow-Origin'], ORIGIN)
        token = json.load(pair_response)['token']
        nonce = "12" * 32
        proof = json.load(req('/bridge/challenge', {'nonce':nonce}, origin=ORIGIN))
        self.assertEqual(proof['version'], VERSION)
        self.assertEqual(proof['nonce'], nonce)
        self.assertEqual(proof['proof'], hmac.new(token.encode('utf-8'), nonce.encode('ascii'), hashlib.sha256).hexdigest())
        self.assertNotIn('token', proof)
        with self.assertRaises(urllib.error.HTTPError):req('/bridge/challenge', {'nonce':'12'*32}, origin=OTHER)
        with self.assertRaises(urllib.error.HTTPError):req('/bridge/challenge', {'nonce':'short'}, origin=ORIGIN)
        paired = json.load(req('/api/companion', local=local))
        self.assertTrue(paired['extension_paired'])
        self.assertEqual(paired['guide']['step'], 'connection')
        req('/api/onboarding', {'action':'connection'}, local=local)
        req('/api/onboarding', {'action':'persona'}, local=local)
        preview = json.load(req('/api/privacy-preview', {}, local=local))
        approved = json.load(req('/api/privacy-approve', {'token':preview['token'],'confirmed':True}, local=local))
        self.assertEqual(approved['guide']['step'], 'browse')
        self.assertTrue(json.load(req('/bridge/status', {}, origin=ORIGIN, token=token))['profile_ready'])
        self.assertIn('verified-chat-links',json.load(req('/bridge/status', {}, origin=ORIGIN, token=token))['capabilities'])
        self.assertEqual(json.load(req('/api/health'))['version'], VERSION)
        saved=json.load(req('/bridge/capture',{'scope':'links','seq':1,'capture':{**capture(),'recruiter_name':'张先生'}},origin=ORIGIN,token=token))
        req('/bridge/confirm',{'scope':'links','seq':1},origin=ORIGIN,token=token)
        chat={'url':'https://www.zhipin.com/web/geek/chat','recruiter_name':'张先生','company':'虚构测试公司','job_title':'销售'}
        payload={'scope':'links','seq':1,'job_id':saved['job']['id'],'chat':chat}
        with self.assertRaises(urllib.error.HTTPError):req('/bridge/link-save',payload,origin=ORIGIN)
        req('/bridge/link-save',payload,origin=ORIGIN,token=token)
        linked=json.load(req('/bridge/link-context',{'scope':'links','chat':chat},origin=ORIGIN,token=token))
        self.assertEqual(linked['link']['job_id'],saved['job']['id'])
        self.assertTrue(linked['recruiter_verified'])
        req('/bridge/link-unbind',payload,origin=ORIGIN,token=token)
        self.assertIsNone(json.load(req('/bridge/link-context',{'scope':'links','chat':chat},origin=ORIGIN,token=token))['link'])
        with self.assertRaises(urllib.error.HTTPError): req('/api/state', origin=ORIGIN, token=token)
        with self.assertRaises(urllib.error.HTTPError): req('/bridge/status', {}, origin=OTHER, token=token)
        preflight = req('/bridge/capture', origin=ORIGIN, method='OPTIONS')
        self.assertEqual(preflight.status, 204)
        self.assertEqual(preflight.headers['Access-Control-Allow-Origin'], ORIGIN)
        with self.assertRaises(urllib.error.HTTPError): req('/bridge/onboarding-complete', {}, origin=ORIGIN)
        with self.assertRaises(urllib.error.HTTPError): req('/bridge/onboarding-complete', {}, origin=ORIGIN, token=token)  # No first reply yet.
        req('/bridge/disconnect', {}, origin=ORIGIN, token=token)
        self.assertEqual(json.load(req('/api/companion', local=local))['guide']['step'], 'pairing')
        code = json.load(req('/api/extension-code', {}, local=local))['code']
        token = json.load(req('/bridge/pair', {'code':code}, origin=ORIGIN))['token']
        # The HTTP binding check above explicitly confirmed a job, so pairing
        # restoration must preserve first_reply instead of returning to browse.
        self.assertEqual(json.load(req('/api/companion', local=local))['guide']['step'], 'first_reply')
        req('/api/extension-revoke', {}, local=local)
        self.assertEqual(json.load(req('/api/companion', local=local))['guide']['step'], 'pairing')
        with self.assertRaises(urllib.error.HTTPError): req('/bridge/status', {}, origin=ORIGIN, token=token)


if __name__ == '__main__': unittest.main()
