import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error

from app.bridge import Bridge, normalize_capture
from app.server import make_server
from app.store import Problem, Store

ORIGIN = "chrome-extension://" + "a" * 32
OTHER = "chrome-extension://" + "b" * 32


def capture(key="job0001", text="负责客户需求沟通与产品演示，结合客户场景制定方案，配合技术推进试用并跟进反馈；要求本科，表达清楚。"):
    return {"job_key": key, "url": f"https://www.zhipin.com/job_detail/{key}.html?security_token=discard-me",
            "title": "销售", "company": "虚构测试公司", "jd": text, "method": "dom"}


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
        local = json.load(req('/api/session'))['token']
        initial = json.load(req('/api/companion'))
        self.assertEqual(initial['guide']['step'], 'pairing')
        self.assertFalse(initial['extension_paired'])
        code = json.load(req('/api/extension-code', {}, local=local))['code']
        self.assertEqual(json.load(req('/api/companion'))['guide']['step'], 'pairing')
        for origin in ("https://www.zhipin.com", "null", "https://evil.example"):
            with self.assertRaises(urllib.error.HTTPError): req('/bridge/pair', {"code":code}, origin=origin)
        pair_response = req('/bridge/pair', {"code": code}, origin=ORIGIN)
        self.assertEqual(pair_response.headers['Access-Control-Allow-Origin'], ORIGIN)
        token = json.load(pair_response)['token']
        paired = json.load(req('/api/companion'))
        self.assertTrue(paired['extension_paired'])
        self.assertEqual(paired['guide']['step'], 'connection')
        req('/api/onboarding', {'action':'connection'}, local=local)
        req('/api/onboarding', {'action':'persona'}, local=local)
        preview = json.load(req('/api/privacy-preview', {}, local=local))
        approved = json.load(req('/api/privacy-approve', {'token':preview['token'],'confirmed':True}, local=local))
        self.assertEqual(approved['guide']['step'], 'browse')
        self.assertTrue(json.load(req('/bridge/status', {}, origin=ORIGIN, token=token))['profile_ready'])
        with self.assertRaises(urllib.error.HTTPError): req('/api/state', origin=ORIGIN, token=token)
        with self.assertRaises(urllib.error.HTTPError): req('/bridge/status', {}, origin=OTHER, token=token)
        preflight = req('/bridge/capture', origin=ORIGIN, method='OPTIONS')
        self.assertEqual(preflight.status, 204)
        self.assertEqual(preflight.headers['Access-Control-Allow-Origin'], ORIGIN)
        with self.assertRaises(urllib.error.HTTPError): req('/bridge/onboarding-complete', {}, origin=ORIGIN)
        with self.assertRaises(urllib.error.HTTPError): req('/bridge/onboarding-complete', {}, origin=ORIGIN, token=token)  # No first reply yet.
        req('/bridge/disconnect', {}, origin=ORIGIN, token=token)
        self.assertEqual(json.load(req('/api/companion'))['guide']['step'], 'pairing')
        code = json.load(req('/api/extension-code', {}, local=local))['code']
        token = json.load(req('/bridge/pair', {'code':code}, origin=ORIGIN))['token']
        self.assertEqual(json.load(req('/api/companion'))['guide']['step'], 'browse')
        req('/api/extension-revoke', {}, local=local)
        self.assertEqual(json.load(req('/api/companion'))['guide']['step'], 'pairing')
        with self.assertRaises(urllib.error.HTTPError): req('/bridge/status', {}, origin=ORIGIN, token=token)


if __name__ == '__main__': unittest.main()
