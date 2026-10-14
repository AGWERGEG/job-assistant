from app.version import EXTENSION_ID
import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from app.store import Store, Problem
from app.companion import Companion
from app.privacy import safe_context
from app.worker import CodexWorker, prompt_for
from app.bridge import Bridge
from app.server import make_server
from app.providers import test_connection


class CompanionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.store.save_profile({'name': '陈晓雨', 'facts': '姓名：陈晓雨\n手机：13812345678\n邮箱：xiaoyu@example.com\n身份证：110101199901011234\n住在星河路88号。\n曾协调5名同学完成校园活动。', 'preferences': '杭州运营'})
        self.c = Companion(self.store)
        self.c.save_settings({'user_name': '雨雨', 'private_terms': '星河路88号', 'buddy_name': '小树'})
        self.approve()
        self.job = self.store.save_job({'title': '运营助理', 'company': '虚构公司', 'jd': '负责校园活动策划、报名整理、用户反馈和复盘，要求细致有沟通能力。'*3})

    def approve(self):
        self.c.approve({'token': self.c.preview_profile()['token'], 'confirmed': True})

    def turn(self, text='这个岗位值得聊吗', request='request-1', kind='companion_chat', job=None):
        return self.c.send({'job_id': self.job['id'] if job is None else job, 'kind': kind, 'text': text, 'request_id': request})['task']

    def finish(self, task, reply='可以先了解一下具体工作内容。'):
        claim = self.store.claim(task['id'])
        return self.store.finish(task['id'], claim['claim_token'], {'mode': 'agent', 'producer': 'test', 'summary': reply, 'primary_output': reply, 'strategy': '主打活动协调', 'markdown': reply})

    def test_redaction_all_context_surfaces_and_profile_reapproval(self):
        t = self.turn('联系陈晓雨 13812345678 xiaoyu@example.com，住星河路88号')
        task = self.store.get_task(t['id'])
        task['context']['prior_results'] = [{'primary_output': '陈晓雨，身份证110101199901011234'}]
        prompt = prompt_for(task, self.c.settings())
        for value in ['陈晓雨', '13812345678', 'xiaoyu@example.com', '110101199901011234', '星河路88号', '雨雨']:
            self.assertNotIn(value, prompt)
        self.assertIn('5名同学', prompt)
        preview = self.c.preview_profile()
        self.c.save_settings({'private_terms': '星河路88号\n新词'})
        self.assertFalse(self.c.ready())
        with self.assertRaises(Problem):
            self.c.approve({'token': preview['token'], 'confirmed': True})

    def test_history_persists_and_is_job_scoped(self):
        first = self.turn()
        self.finish(first, '先问清活动执行比例')
        second = self.turn('那我该怎么问？', request='second')
        context = self.store.get_task(second['id'])['context']
        self.assertIn('先问清活动执行比例', json.dumps(context, ensure_ascii=False))
        reopened = Companion(Store(self.temp.name))
        self.assertEqual(len(reopened.history(self.job['id'])['turns']), 2)
        self.assertEqual(reopened.history('another-job')['turns'], [])
        self.assertEqual(reopened.settings()['buddy_name'], '小树')

    def test_general_chat_without_job_and_idempotency(self):
        first = self.turn('最近有点没信心', job='')
        self.assertEqual(first['id'], self.turn('最近有点没信心', job='')['id'])
        with self.assertRaises(Problem):
            self.turn('再发一句', request='second', job='')
        self.finish(first)
        self.assertEqual(self.c.history('')['turns'][0]['status'], 'done')

    def test_first_use_guide_requires_explicit_job_and_completed_first_reply(self):
        fresh = Companion(Store(str(Path(self.temp.name) / 'guide')))
        fresh.store.save_profile({'facts': '校园活动：负责报名、沟通与复盘。', 'preferences': '杭州运营'})
        job = fresh.store.save_job({'title': '运营助理', 'company': '引导公司', 'jd': '负责活动执行、用户沟通和复盘整理，需要细致推进能力。' * 3})
        self.assertEqual(fresh.onboarding_state()['step'], 'connection')
        fresh.onboarding_action({'action': 'connection'})
        self.assertEqual(fresh.onboarding_state()['step'], 'persona')
        fresh.onboarding_action({'action': 'persona'})
        self.assertEqual(fresh.onboarding_state()['step'], 'privacy')
        fresh.approve({'token': fresh.preview_profile()['token'], 'confirmed': True})
        self.assertEqual(fresh.onboarding_state()['step'], 'browse')
        fresh.onboarding_job(job['id'])
        self.assertEqual(fresh.onboarding_state()['step'], 'first_reply')
        quick = fresh.send({'job_id': job['id'], 'kind': 'quick_analysis', 'text': '', 'request_id': 'guide-quick'})['task']
        self.assertEqual(fresh.onboarding_state()['step'], 'first_reply_wait')
        with self.assertRaises(Problem):
            fresh.onboarding_action({'action': 'complete'})
        claim = fresh.store.claim(quick['id'])
        fresh.store.finish(quick['id'], claim['claim_token'], {'mode': 'agent', 'producer': 'test', 'summary': '完成', 'primary_output': '完成', 'strategy': '', 'markdown': '完成'})
        self.assertEqual(fresh.onboarding_state()['step'], 'first_success')
        fresh.onboarding_action({'action': 'complete'})
        self.assertFalse(fresh.onboarding_state()['active'])

    def test_onboarding_can_go_back_or_skip(self):
        fresh=Companion(Store(str(Path(self.temp.name)/'guide-controls')))
        self.assertEqual(fresh.onboarding_state()['step'],'connection')
        fresh.onboarding_action({'action':'connection'})
        self.assertEqual(fresh.onboarding_state()['step'],'persona')
        fresh.onboarding_action({'action':'back'})
        self.assertEqual(fresh.onboarding_state()['step'],'connection')
        fresh.onboarding_action({'action':'skip'})
        self.assertFalse(fresh.onboarding_state()['active'])

    def test_skipped_guide_has_an_actionable_readiness_reason(self):
        fresh = Companion(Store(str(Path(self.temp.name) / 'guide-readiness')))
        fresh.onboarding_action({'action': 'skip'})
        public = fresh.settings(public=True)
        self.assertFalse(fresh.ready())
        self.assertEqual(public['readiness']['state'], 'profile_required')
        self.assertEqual(public['readiness']['page'], 'profile')
        self.assertNotIn('api_key', public['readiness'])
        fresh.store.save_profile({'facts': '校园活动：负责报名、沟通与复盘。', 'preferences': '杭州运营'})
        self.assertEqual(fresh.settings(public=True)['readiness']['state'], 'privacy_required')
        fresh.approve({'token': fresh.preview_profile()['token'], 'confirmed': True})
        self.assertEqual(fresh.settings(public=True)['readiness']['state'], 'ready')

    def test_codex_login_check_distinguishes_missing_login(self):
        from app.worker import codex_login_check
        with patch('app.worker.subprocess.run', return_value=SimpleNamespace(returncode=1, stdout='Not logged in', stderr='')):
            ok,message=codex_login_check('/fake/codex')
        self.assertFalse(ok)
        self.assertIn('401',message)
        with patch('app.worker.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout='Logged in', stderr='')):
            self.assertTrue(codex_login_check('/fake/codex')[0])
        with patch('app.worker.subprocess.run', side_effect=OSError('private path')):
            ok,message=codex_login_check('/fake/codex')
            self.assertFalse(ok);self.assertNotIn('private path',message)

    def test_guide_back_preserves_profile_approval_tasks_and_stays_after_reload(self):
        before_profile=self.c.profile();approval=self.c.settings()['privacy_approved']
        self.c.onboarding_action({'action':'restart'})
        self.c.onboarding_action({'action':'connection'})
        self.c.onboarding_action({'action':'back'})
        self.assertEqual(self.c.onboarding_state()['step'],'privacy')
        self.c.onboarding_action({'action':'back'})
        self.assertEqual(Companion(self.store).onboarding_state()['step'],'profile')
        self.assertEqual(self.c.profile(),before_profile)
        self.assertEqual(self.c.settings()['privacy_approved'],approval)
        self.assertTrue(self.c.ready())
        self.c.onboarding_action({'action':'connection-settings'})
        self.assertEqual(self.c.onboarding_state()['step'],'connection')
        self.c.onboarding_action({'action':'skip'})
        self.assertFalse(self.c.onboarding_state()['active'])
        unready=Companion(Store(str(Path(self.temp.name)/'skip-unready')))
        unready.onboarding_action({'action':'skip'})
        self.assertFalse(unready.ready())

    def test_model_auth_failure_takes_precedence_over_transport_retries(self):
        from app.worker import codex_error
        self.assertIn('401',codex_error(1,'stream disconnected\nERROR: 401 Missing bearer authentication'))
        self.assertIn('超时',codex_error(1,'plugin cache failed 401\nstream disconnected'))

    def test_failed_first_task_is_replaced_by_next_explicit_attempt(self):
        self.c.onboarding_action({'action':'restart'})
        self.c.onboarding_action({'action':'connection'})
        self.c.onboarding_job(self.job['id'])
        t=self.turn(kind='quick_analysis')
        claim=self.store.claim(t['id']);self.store.fail(t['id'],claim['claim_token'],'401','test')
        second=self.turn(kind='quick_analysis',request='new-attempt')
        self.finish(second)
        self.assertEqual(self.c.onboarding_state()['step'],'first_success')

    def test_explicit_resume_request_routes_but_discussion_stays_chat(self):
        first = self.turn('帮我优化简历，重点写校园经历')
        self.assertEqual(first['kind'], 'tailor_resume')
        self.finish(first)
        second = self.turn('HR让我改简历，我有点担心', request='discussion')
        self.assertEqual(second['kind'], 'companion_chat')

    def test_detailed_analysis_phrasing_routes_to_background(self):
        for index, message in enumerate((
            '详细分析一下这个岗位',
            '结合公司背景全面判断这个机会',
            '请系统拆解岗位要求和我的经历',
        )):
            task = self.turn(message, request='deep-'+str(index))
            self.assertEqual(task['kind'], 'analyze_job')
            self.store.cancel(task['id'])

    def test_endpoint_change_clears_old_key_and_http_remote_is_rejected(self):
        self.c.save_settings({'base_url': 'https://example.com/v1', 'api_key': 'synthetic-secret'})
        self.c.save_settings({'base_url': 'https://new.example.com/v1', 'api_key': ''})
        self.assertFalse(self.c.settings(public=True)['has_api_key'])
        with self.assertRaises(Problem):
            self.c.save_settings({'base_url': 'http://remote.example.com/v1'})

    def test_api_connection_test_explains_unsaved_key(self):
        self.c.save_settings({'provider': 'api', 'base_url': 'https://api.example.com/v1', 'api_model': 'test-model', 'clear_api_key': True})
        with self.assertRaisesRegex(Problem, '尚未保存 API 密钥'):
            test_connection(self.c.settings())

    def test_connection_test_falls_back_when_stream_is_incompatible(self):
        from app.providers import test_connection
        cfg={'provider':'api','api_key':'synthetic','stream':True}
        with patch('app.providers.complete',side_effect=[Problem('流式连接提前结束'), 'OK', '{"ok":true}']) as call:
            result=test_connection(cfg)
        self.assertFalse(result['stream_supported']);self.assertIn('自动改用',result['message'])
        self.assertTrue(result['structured_supported']);self.assertEqual(call.call_count,3);self.assertIsNotNone(call.call_args_list[0].kwargs.get('on_delta'))
        self.assertFalse(call.call_args_list[1].args[0]['stream'])

    def test_prompt_budget_selects_relevant_profile_without_mutating_snapshot(self):
        facts=[]
        for index in range(20):
            facts.append(f'普通经历{index}\n2024年负责日常行政归档、会议记录和物品整理。')
        facts.insert(7,'AI产品销售经历\n2025年负责企业客户需求沟通、产品演示、方案整理与合同跟进。')
        full='\n\n'.join(facts)
        self.store.save_profile({'facts':full,'preferences':'销售'})
        self.approve()
        job=self.store.save_job({'title':'AI解决方案销售','company':'虚构公司','jd':'负责AI产品销售、企业客户开发、产品演示、方案沟通和合同跟进。'})
        task=self.store.create_task({'kind':'tailor_resume','job_id':job['id'],'instruction':'优化简历'})
        stored=self.store.get_task(task['id'])['context']['profile']['facts']
        prompt=prompt_for(self.store.get_task(task['id']),self.c.settings())
        self.assertEqual(stored,full)
        self.assertIn('AI产品销售经历',prompt)
        self.assertLess(len(prompt),len(full)+2400)
        self.assertIn('未发送不代表没有相关经历',prompt)

    def test_legacy_confirmed_user_with_partial_guide_fields_is_not_onboarded_again(self):
        legacy = self.c.settings()
        legacy.pop('guide_version', None)
        legacy.update(guide_completed=False, guide_connection_ready=True, guide_persona_ready=False)
        with self.store.connect() as db:
            db.execute('INSERT OR REPLACE INTO companion_settings VALUES(1,?)', (json.dumps(legacy, ensure_ascii=False),))
        restored = Companion(self.store)
        self.assertFalse(restored.settings(public=True)['guide']['active'])
        restored.save_settings({'buddy_name': '小树'})
        self.assertTrue(restored.settings()['guide_completed'])

    def test_quota_classification_does_not_echo_prompt(self):
        from app.worker import codex_error
        raw = "request timed out 陈晓雨 13812345678 You've hit your usage limit"
        error = codex_error(1, raw)
        self.assertIn('额度', error)
        self.assertNotIn('陈晓雨', error)

    def test_stale_accepted_resume_not_in_new_context(self):
        first = self.turn(kind='tailor_resume')
        self.finish(first)
        self.c.accept_resume({'task_id':first['id'], 'content':'旧版已验收简历'})
        self.store.save_profile({'facts':'新画像内容'})
        self.approve()
        second = self.turn('继续', request='new-profile')
        self.assertNotIn('accepted_resume', self.store.get_task(second['id'])['context'])

    def test_structured_api_response_flows_to_acceptance(self):
        t = self.turn(kind='tailor_resume')
        self.c.save_settings({'provider':'api','base_url':'https://example.com/v1','api_model':'synthetic'})
        result = {'summary':'虚构回归结果','decision':'突出活动协调','strategy':'保留事实','primary_output':'负责活动报名与复盘','questions':[],'markdown':'前置校园活动经历。'}
        def fake(*args,**kwargs):
            kwargs['on_usage']({'prompt_tokens':321,'completion_tokens':123,'total_tokens':444})
            return json.dumps(result)
        with patch('app.worker.api_complete', side_effect=fake) as call:
            CodexWorker(self.store, '.').run_one()
            self.assertTrue(call.call_args.kwargs['structured'])
            self.assertTrue(call.call_args.kwargs['on_usage'])
        done = self.store.get_task(t['id'])
        self.assertEqual(done['status'],'done')
        self.assertEqual(done['metrics']['input_tokens'],321)
        self.assertEqual(done['metrics']['output_tokens'],123)
        self.assertTrue(self.c.accept_resume({'task_id':t['id'],'content':done['result']['primary_output']})['saved'])

    def test_http_bridge_cannot_access_settings_or_unconfirmed_history(self):
        import urllib.request
        import urllib.error
        server = make_server(self.temp.name, 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}'
        session = {'token':server.session_token}
        def post(path, payload, headers):
            req = urllib.request.Request(base+path, data=json.dumps(payload).encode(), headers={'Content-Type':'application/json', **headers})
            return json.load(urllib.request.urlopen(req))
        code = post('/api/extension-code', {}, {'X-Local-Token':session['token']})['code']
        origin = 'chrome-extension://'+EXTENSION_ID
        pair = post('/bridge/pair', {'code': code}, {'Origin':origin})
        headers = {'Origin':origin,'X-Bridge-Token':pair['token']}
        with self.assertRaises(urllib.error.HTTPError) as error:
            post('/api/companion', {}, headers)
        self.assertEqual(error.exception.code, 403)
        status = post('/bridge/status', {}, headers)
        self.assertTrue(status['ready'])
        self.assertNotIn('api_key', status)
        with self.assertRaises(urllib.error.HTTPError):
            post('/bridge/history', {'scope':'new','seq':1}, headers)

    def test_only_one_concurrent_turn_per_job(self):
        def send(i):
            try:
                return self.turn(request=str(i))['status']
            except Problem:
                return 'busy'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(send, [1, 2])), ['queued', 'busy'])

    def test_resume_acceptance_is_versioned_idempotent_and_stale_safe(self):
        t = self.turn(kind='tailor_resume')
        self.finish(t, '负责校园活动协调')
        a = self.c.accept_resume({'task_id': t['id'], 'content': '我核对过的活动经历'})
        b = self.c.accept_resume({'task_id': t['id'], 'content': '我核对过的活动经历'})
        self.assertEqual(a['id'], b['id'])
        next_task = self.turn('帮我写招呼', request='next', kind='suggest_reply')
        self.assertEqual(self.store.get_task(next_task['id'])['context']['accepted_resume'], '我核对过的活动经历')
        self.store.save_profile({'facts': '更新后的经历'})
        with self.assertRaises(Problem):
            self.c.accept_resume({'task_id': t['id'], 'content': '旧版'})

    def test_api_transport_only_sends_redacted_prompt_and_never_exposes_key(self):
        captured = []
        class Fake(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                captured.append((self.path, self.headers.get('Authorization'), json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                data = ('data: ' + json.dumps({'id':'fixture','object':'chat.completion.chunk','created':0,'model':'fixture','choices':[{'index':0,'delta':{'role':'assistant','content':'好，你慢慢说。'},'finish_reason':None}]}) + '\n\ndata: ' + json.dumps({'id':'fixture','object':'chat.completion.chunk','created':0,'model':'fixture','choices':[{'index':0,'delta':{},'finish_reason':'stop'}]}) + '\n\ndata: [DONE]\n\n').encode()
                self.send_response(200); self.send_header('Content-Type','text/event-stream'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Fake)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        self.c.save_settings({'provider': 'api', 'base_url': f'http://127.0.0.1:{server.server_port}/v1', 'api_model': 'test-model', 'api_key': 'synthetic-secret','dialogue_agent':True})
        t = self.turn('陈晓雨 13812345678 想聊聊')
        worker = CodexWorker(self.store, '.', timeout=5)
        self.assertTrue(worker.run_one())
        done = self.store.get_task(t['id'])
        self.assertEqual(done['status'], 'done')
        self.assertIn('total_seconds', done['metrics'])
        path, auth, body = captured[0]
        self.assertEqual(path, '/v1/chat/completions')
        self.assertEqual(auth, 'Bearer synthetic-secret')
        serialized = json.dumps(body, ensure_ascii=False)
        for value in ['陈晓雨', '13812345678', 'synthetic-secret', 'xiaoyu@example.com']:
            self.assertNotIn(value, serialized)
        self.assertNotIn('synthetic-secret', json.dumps(self.c.settings(public=True)))
        self.assertNotIn('synthetic-secret', json.dumps(self.store.state()))

    def test_codex_transport_uses_same_privacy_boundary(self):
        t = self.turn('手机号13812345678，如何表达经历？', kind='quick_analysis')
        calls = []
        def fake_run(command, prompt, work, timeout, cancelled):
            calls.append(prompt)
            target = command[command.index('--output-last-message')+1]
            Path(target).write_text('可以先用校园活动协调经历说明你怎样推进工作。', encoding='utf-8')
            return SimpleNamespace(returncode=0)
        worker = CodexWorker(self.store, '.', codex_bin='/bin/true')
        with patch('app.worker.run_codex', side_effect=fake_run):
            worker.run_one()
        self.assertEqual(self.store.get_task(t['id'])['status'], 'done')
        self.assertNotIn('13812345678', calls[0])
        self.assertNotIn('陈晓雨', calls[0])

    def test_worker_stops_unreviewed_profile_before_network(self):
        t = self.turn()
        self.store.save_profile({'facts': '新经历，尚未核对'})
        with patch('app.worker.run_codex') as run:
            CodexWorker(self.store, '.', codex_bin='/bin/true').run_one()
            run.assert_not_called()
        self.assertEqual(self.store.get_task(t['id'])['status'], 'failed')

    def test_bridge_requires_confirmation_and_rejects_old_sequence(self):
        b = Bridge(self.store); client = 'chrome-extension://'+EXTENSION_ID
        payload = {'scope': 'scope1', 'seq': 1, 'capture': {'job_key': 'job1234', 'url': 'https://www.zhipin.com/job_detail/job1234.html', 'title': '运营', 'company': '公司', 'jd': '整理数据并执行校园活动，做好活动沟通和复盘。'*4}}
        b.capture(client, payload)
        with self.assertRaises(Problem):
            b.companion_action(client, {'scope': 'scope1', 'seq': 1}, 'history')
        b.companion_action(client, {'scope': 'scope1', 'seq': 1}, 'confirm')
        result = b.companion_action(client, {'scope': 'scope1', 'seq': 1, 'text': '你好', 'request_id': 'bridge1'}, 'talk')
        self.assertEqual(result['task']['status'], 'queued')
        b.capture(client, {'scope': 'scope1', 'seq': 2, 'capture': None})
        with self.assertRaises(Problem):
            b.companion_action(client, {'scope': 'scope1', 'seq': 1}, 'history')

    def test_existing_database_migration_preserves_profile_and_tasks(self):
        t = self.turn()
        original = self.c.profile()
        with self.store.connect() as db:
            db.execute("UPDATE meta SET value='4' WHERE key='schema_version'")
        reopened = Store(self.temp.name)
        self.assertEqual(Companion(reopened).profile(), original)
        self.assertEqual(reopened.get_task(t['id'])['status'], 'queued')


if __name__ == '__main__':
    unittest.main()
