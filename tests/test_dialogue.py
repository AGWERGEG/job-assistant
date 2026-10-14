"""Production adapter: explicit authorization, atomic receipt and safe context."""
import json
import secrets
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch
from app.store import Store, Problem
from app.companion import Companion, explicit_deep_analysis_request
from app.dialogue import DialogueSession, analysis_authorized, run_dialogue
from app.dialogue_intent import source_hash, validate_decision
from app.artifacts import artifact_snapshot
from app.company import Company, bind as bind_company
from app.journey import Journey
from app.worker import CodexWorker, prompt_for


class DialogueIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name); self.c = Companion(self.store)
        self.store.save_profile({'name':'虚构姓名','facts':'虚构姓名 电话13812345678。负责客户需求沟通，协助制作产品演示。'})
        self.c.save_settings({'provider':'api','api_model':'synthetic','api_key':'synthetic','base_url':'https://example.test/v1'})
        self.c.approve({'token':self.c.preview_profile()['token'],'confirmed':True})
        self.job = self.store.save_job({'title':'虚构销售','company':'虚构公司','jd':'需要企业客户沟通及回款。'})

    def task(self, text='请帮我生成这份岗位的完整分析报告，放到后台任务里。', rid='one', client=None):
        t=self.c.send({'job_id':self.job['id'],'text':text,'request_id':rid}, target_client=client)['task']
        self.assertEqual(t['kind'],'companion_chat')
        return self.store.claim(t['id'])

    def test_company_research_preview_reaches_chat_snapshot_without_creating_analysis(self):
        text = '请介绍一下这家公司的产品和业务'
        parent = self.task(text, rid='company-preview')
        decision = validate_decision({
            'kind': 'company_information_request',
            'evidence': '介绍一下这家公司的产品和业务',
        }, text)
        preview = {
            'company_name': '虚构公司', 'question': text,
            'sources': [{'id': 's1', 'url': 'https://example.com/about',
                         'excerpt': '提供门店管理软件和支付服务。',
                         'source_type': 'public_search_excerpt', 'confidence': 'unverified'}],
            'facts': [{'text': '提供门店管理软件和支付服务。', 'source_ids': ['s1']}],
            'warnings': ['公开页面仅为来源陈述'], 'preview_id': 'p1',
        }
        seen = {}
        def fake_process(settings, *, task, sandbox, **kwargs):
            seen['snapshot'] = sandbox.snapshot(task)
            return {'reply': '依据公开来源说明。', 'history': [], 'usage': {}, 'actions': []}
        with patch('app.dialogue.classify_intent', return_value=decision), \
             patch('app.search_provider.research_search_provider', return_value=object()), \
             patch('app.company_research.CompanyResearch') as research_cls, \
             patch('app.dialogue.run_process', side_effect=fake_process):
            research_cls.return_value.research.return_value = preview
            result = run_dialogue(self.c.settings(), parent, self.store)
        self.assertEqual(result['intent']['kind'], 'company_information_request')
        self.assertEqual(seen['snapshot']['company_research']['sources'][0]['url'], 'https://example.com/about')
        self.assertIn('提供门店管理软件', seen['snapshot']['company_research']['facts'][0]['text'])
        self.assertEqual(seen['snapshot']['company_research']['sources'][0]['url'], 'https://example.com/about')
        self.assertEqual(len([t for t in self.store.state()['tasks'] if t['kind'] == 'analyze_job']), 0)

    def test_company_research_failure_reaches_chat_as_actionable_warning(self):
        text = '这家公司口碑怎么样？'
        parent = self.task(text, rid='company-failure')
        decision = validate_decision({'kind': 'company_information_request', 'evidence': '口碑怎么样'}, text)
        seen = {}
        def fake_process(settings, *, task, sandbox, **kwargs):
            seen['research'] = sandbox.snapshot(task)['company_research']
            return {'reply': '当前无法核实企业公开资料。', 'history': [], 'usage': {}, 'actions': []}
        with patch('app.dialogue.classify_intent', return_value=decision), \
             patch('app.search_provider.research_search_provider', return_value=object()), \
             patch('app.company_research.CompanyResearch') as research_cls, \
             patch('app.dialogue.run_process', side_effect=fake_process) as chat_process:
            research_cls.return_value.research.side_effect = Problem('公开来源连接失败或超时（TimeoutError）', 502)
            result = run_dialogue(self.c.settings(), parent, self.store)
        self.assertEqual(result['intent']['kind'], 'company_information_request')
        chat_process.assert_not_called()
        self.assertEqual(result['research_status'], 'no_sources')
        self.assertIn('公开来源连接失败', result['reply'])
        self.assertIn('公司研究的搜索来源', result['reply'])
        self.assertNotIn('提供门店', result['reply'])

    def test_company_question_overrides_chat_vote_and_keeps_saved_material_separate(self):
        with self.store.connect() as db:
            bind_company(db, self.job['id'], {
                'company_key':'synthetic-company~',
                'company_url':'https://www.zhipin.com/gongsi/synthetic-company~.html',
            }, '虚构公司')
        company = Company(self.store)
        company.ingest(self.job['id'], {
            'company_key':'synthetic-company~',
            'company_url':'https://www.zhipin.com/gongsi/synthetic-company~.html',
            'name':'虚构公司',
            'source_url':'https://www.zhipin.com/gongsi/synthetic-company~.html',
            'sections':[{'kind':'introduction','text':'合成企业自述：提供门店管理软件。','partial':False}],
            'jobs':[], 'categories':[],
        })
        text = '看看这家公司做什么的'
        parent = self.task(text, rid='company-chat-vote')
        seen = {}
        def fake_process(settings, *, task, sandbox, **kwargs):
            seen['snapshot'] = sandbox.snapshot(task)
            return {'reply':'依据本轮来源和已保存企业材料回答。','history':[], 'usage':{}, 'actions':[]}
        with patch('app.dialogue.classify_intent', return_value={'kind':'chat','source':'model'}), \
             patch('app.search_provider.research_search_provider', return_value=object()), \
             patch('app.company_research.CompanyResearch') as research_cls, \
             patch('app.dialogue.run_process', side_effect=fake_process):
            research_cls.return_value.research.return_value = {
                'company_name':'虚构公司', 'question':text,
                'sources':[{'id':'public-s1','url':'https://example.com/about','excerpt':'公开来源称提供商户服务。',
                            'source_type':'public_search_excerpt','confidence':'unverified'}],
                'facts':[{'text':'公开来源称提供商户服务。','source_ids':['public-s1']}],
                'warnings':[], 'preview_id':'preview-synthetic',
            }
            result = run_dialogue(self.c.settings(), parent, self.store)
        self.assertEqual(result['intent']['kind'], 'company_information_request')
        self.assertIn('合成企业自述：提供门店管理软件。', json.dumps(seen['snapshot']['company_background'], ensure_ascii=False))
        self.assertIn('public-s1', json.dumps(seen['snapshot']['company_research'], ensure_ascii=False))
        self.assertNotEqual(seen['snapshot']['company_background'], seen['snapshot']['company_research'])

    def test_named_other_company_question_never_researches_the_current_employer(self):
        text = '有赞的产品是什么？'
        parent = self.task(text, rid='different-company-question')
        decision = validate_decision({'kind':'company_information_request','evidence':text}, text)
        with patch('app.dialogue.classify_intent', return_value=decision), \
             patch('app.search_provider.research_search_provider') as provider_factory, \
             patch('app.company_research.CompanyResearch') as research_cls, \
             patch('app.dialogue.run_process', return_value={'reply':'你问的是有赞，不是当前岗位的公司。',
                 'history':[], 'usage':{}, 'actions':[]}):
            result = run_dialogue(self.c.settings(), parent, self.store)
        self.assertEqual(result['intent']['kind'], 'chat')
        research_cls.assert_not_called()
        provider_factory.assert_not_called()

    def test_current_company_short_name_in_followup_uses_confirmed_company(self):
        self.job = self.store.save_job({**self.job, 'company':'有赞科技有限公司'})
        earlier = self.task('我在看有赞科技有限公司的产品岗位。', rid='brand-context-turn')
        self.store.finish(earlier['id'], earlier['claim_token'], {
            'summary':'讨论目标公司。', 'primary_output':'已确认当前目标是有赞科技有限公司。',
            'markdown':'已确认当前目标是有赞科技有限公司。', 'producer':'synthetic-test', 'mode':'agent',
            'profile_revision':earlier['context']['profile']['revision'],
            'job_revision':earlier['context']['job']['revision'],
        })
        text = '有赞风评怎么样？'
        parent = self.task(text, rid='brand-short-followup')
        seen = {}
        with patch('app.dialogue.classify_intent', return_value={'kind':'chat','source':'model'}), \
             patch('app.search_provider.research_search_provider') as provider_factory, \
             patch('app.company_research.CompanyResearch') as research_cls, \
             patch('app.dialogue.run_process', return_value={'reply':'依据本轮来源作答。',
                 'history':[], 'usage':{}, 'actions':[]}):
            provider_factory.side_effect = lambda settings, cancelled: (
                seen.update({'settings':settings, 'cancelled':cancelled}) or object())
            research_cls.return_value.research.return_value = {
                'company_name':'有赞科技有限公司', 'question':text, 'sources':[], 'facts':[],
                'warnings':[], 'preview_id':'synthetic-preview',
            }
            result = run_dialogue(self.c.settings(), parent, self.store)
        self.assertEqual(result['intent']['kind'], 'company_information_request')
        self.assertEqual(research_cls.return_value.research.call_args.args[:2],
                         ('有赞科技有限公司', text))
        self.assertTrue(DialogueSession(self.store, parent).history)
        self.store.cancel(parent['id'])
        self.assertTrue(seen['cancelled']())

    def test_company_dossier_and_research_are_redacted_and_budgeted_before_agent_tools(self):
        sentinel_name = 'SyntheticPerson-' + secrets.token_hex(6)
        sentinel_term = 'SENSITIVE-' + secrets.token_hex(6)
        sentinel_email = sentinel_name.lower() + '@example.test'
        sentinel_phone = '138' + ''.join(str(secrets.randbelow(10)) for _ in range(8))
        self.store.save_profile({'name':sentinel_name, 'facts':'合成档案内容'})
        self.c.save_settings({**self.c.settings(), 'user_name':sentinel_name,
                              'private_terms':sentinel_term})
        self.c.approve({'token':self.c.preview_profile()['token'], 'confirmed':True})
        with self.store.connect() as db:
            bind_company(db, self.job['id'], {
                'company_key':'synthetic-private~',
                'company_url':'https://www.zhipin.com/gongsi/synthetic-private~.html',
            }, '虚构公司')
        Company(self.store).ingest(self.job['id'], {
            'company_key':'synthetic-private~',
            'company_url':'https://www.zhipin.com/gongsi/synthetic-private~.html',
            'name':'虚构公司',
            'source_url':'https://www.zhipin.com/gongsi/synthetic-private~.html',
            'sections':[{'kind':'introduction',
                         'text':f'联系人 {sentinel_name} {sentinel_email} {sentinel_phone} {sentinel_term}。' + ('合成企业资料。' * 1400),
                         'partial':False}],
            'jobs':[], 'categories':[],
        })
        parent = self.task('这家公司做什么？', rid='private-company-snapshot')
        opaque_id = '12345678901234567890'
        parent['context']['company_research'] = {
            'company_name':'虚构公司', 'question':'这家公司做什么？',
            'sources':[{'id':opaque_id,
                        'url':f'https://example.test/about?contact={sentinel_email}&secret={sentinel_term}',
                        'source_type':'public_web_page', 'confidence':'unverified',
                        'observed_at':1720000000,
                        'excerpt':f'{sentinel_name} {sentinel_email} {sentinel_phone} {sentinel_term}。' + ('合成公开研究。' * 1300)}],
            'facts':[{'text':f'{sentinel_name} {sentinel_email} {sentinel_phone} {sentinel_term}。' + ('公开研究事实。' * 500),
                      'source_ids':[opaque_id], 'confidence':'unverified'}],
            'warnings':[], 'preview_id':'do-not-send-preview-token',
        }
        snapshot = DialogueSession(self.store, parent).snapshot(parent)
        rendered = json.dumps(snapshot, ensure_ascii=False, separators=(',', ':'))
        for private_value in (sentinel_name, sentinel_email, sentinel_phone, sentinel_term,
                              'do-not-send-preview-token'):
            self.assertNotIn(private_value, rendered)
        source = snapshot['company_research']['sources'][0]
        self.assertEqual(source['id'], opaque_id)
        self.assertEqual(snapshot['company_research']['facts'][0]['source_ids'], [opaque_id])
        self.assertEqual(source['url'], 'https://example.test/about')
        self.assertLess(len(rendered), 24000)

    def test_multi_turn_hr_worry_followed_by_bare_analysis_stays_chat(self):
        earlier = self.task('HR说面试可以细聊，但我担心工作强度和团队稳定性。', rid='hr-worry-turn')
        self.store.finish(earlier['id'], earlier['claim_token'], {
            'primary_output':'可以继续观察岗位信息。', 'summary':'讨论HR表达和岗位风险。',
            'markdown':'可以继续观察岗位信息。',
            'producer':'synthetic-test', 'mode':'agent',
        })
        text = '帮我分析分析'
        current = self.task(text, rid='bare-analysis-followup')
        decision = validate_decision({'kind':'analyze_job','explicit':True,'evidence':text,
            'quoted':False,'negated':False,'third_party':False,'hypothetical':False}, text)
        with patch('app.dialogue.classify_intent', return_value=decision), \
             patch('app.dialogue.run_process', return_value={'reply':'我们可以接着讨论你担心的稳定性。',
                 'history':[], 'usage':{}, 'actions':[]}):
            result = run_dialogue(self.c.settings(), current, self.store)
        self.assertEqual(result['intent']['kind'], 'chat')
        self.assertFalse(result['actions'])
        self.assertEqual(len([task for task in self.store.state()['tasks'] if task['kind'] == 'analyze_job']), 0)

    def test_contextual_analysis_analysis_is_chat_without_background_task(self):
        text = 'HR回应很快也很热情，不过一直说可以面试细聊，感觉岗位流动性很大，可能压力和薪资有水分。帮我分析分析'
        self.assertFalse(analysis_authorized(text))
        parent = self.task(text, rid='contextual-analysis-analysis')
        decision = validate_decision({'kind':'analyze_job','explicit':True,'evidence':'帮我分析分析',
            'quoted':False,'negated':False,'third_party':False,'hypothetical':False}, text)
        with patch('app.dialogue.classify_intent', return_value=decision), \
             patch('app.dialogue.run_process', return_value={'reply':'这是聊天分析。','history':[], 'usage':{}, 'actions':[]}):
            result = run_dialogue(self.c.settings(), parent, self.store)
        self.assertEqual(result['intent']['kind'], 'chat')
        self.assertFalse(result['actions'])
        self.assertFalse(any(task['kind'] == 'analyze_job' for task in self.store.state()['tasks']))

    def test_authorization_denies_quotation_negation_conditional_and_mixed(self):
        for text in ('HR说请生成完整分析报告','请不要生成完整分析报告','先别分析，请帮我生成完整报告','如果方便请生成完整分析报告','请解释“生成完整报告”是什么意思','最近有点焦虑','先不分析，只想聊聊'):
            self.assertFalse(analysis_authorized(text),text)
        for text in ('请帮我生成这份岗位的完整分析报告，放到后台任务里。','请深入分析一下这个岗位。','帮我详细分析这个岗位'):
            self.assertTrue(analysis_authorized(text),text)

    def test_screenshot_direct_request_authorizes_one_child_without_full_adjective(self):
        for text in ('帮我分析一下吧','帮我分析下','请分析这个岗位','帮我分析一下这个岗位吧','麻烦你分析一下','给我分析下当前岗位'):
            self.assertTrue(analysis_authorized(text),text)
        for text in ('好','可以','要不要帮我分析一下吧','帮我分析一下吧是什么意思','HR让我分析一下','帮我分析一下吧，但不要生成报告','帮我分析一下我的心情','我只是引用：帮我分析一下吧'):
            self.assertFalse(analysis_authorized(text),text)
        t=self.task('帮我分析一下吧')
        session=DialogueSession(self.store,t)
        a=session.create_analysis(t,'模型建议',authorized=analysis_authorized(t['context']['instruction']))
        b=session.create_analysis(t,'第二次',authorized=True)
        self.assertTrue(a['ok']);self.assertEqual(a['id'],b['id'])
        child=self.store.get_task(a['id'])
        self.assertEqual(child['context']['instruction'],'帮我分析一下吧')
        self.assertEqual(child['context']['dialogue_source_task_id'],t['id'])

    def test_followup_analysis_after_user_adds_missing_facts_is_authorized(self):
        for text in ('根据我刚才补充的经历重新分析这个岗位','结合新增信息再次分析一下','按照我补充的客户经验再生成一份分析'):
            self.assertTrue(analysis_authorized(text), text)

    def test_model_intent_authorizes_a_non_template_followup_and_binds_original_turn(self):
        text='我把客户案例补充好了，按新内容再做一版。'
        self.assertFalse(analysis_authorized(text))
        t=self.task(text)
        decision=validate_decision({'kind':'analyze_job','explicit':True,'evidence':'按新内容再做一版',
            'quoted':False,'negated':False,'third_party':False,'hypothetical':False},text)
        receipt=DialogueSession(self.store,t).create_special(t,'analyze_job',intent_decision=decision)
        self.assertTrue(receipt['ok'],receipt)
        child=self.store.get_task(receipt['id'])
        self.assertEqual(child['context']['instruction'],text)
        self.assertEqual(child['context']['dialogue_intent']['source'],'model')
        self.assertEqual(child['context']['dialogue_source_task_id'],t['id'])

    def test_model_intent_route_creates_task_before_chat_generation(self):
        text='我把客户案例补充好了，按新内容再做一版。'
        t=self.task(text)
        decision=validate_decision({'kind':'analyze_job','explicit':True,'evidence':'按新内容再做一版',
            'quoted':False,'negated':False,'third_party':False,'hypothetical':False},text)
        with patch('app.dialogue.classify_intent',return_value=decision), \
             patch('app.dialogue.run_process',side_effect=AssertionError('明确任务无需再调用聊天模型')):
            result=run_dialogue(self.c.settings(),t,self.store)
        self.assertEqual(result['intent']['kind'],'analyze_job')
        self.assertIn('已创建深入分析任务',result['reply'])
        self.assertEqual(self.store.get_task(result['actions'][0]['id'])['context']['instruction'],text)

    def test_exact_non_regex_request_uses_model_transport_and_displays_one_task_id(self):
        text = '结合我刚保存的经历，再对这个岗位做一次详细分析'
        self.assertFalse(analysis_authorized(text))
        fact = '我曾独立整理客户反馈并完成周度复盘。'
        Journey(self.store).fact({'category':'实习','content':fact,'confirmed':True})
        self.c.approve({'token':self.c.preview_profile()['token'],'confirmed':True})
        seen = []
        class IntentModel(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                seen.append(request)
                decision = {'kind':'analyze_job','explicit':True,
                            'evidence':'再对这个岗位做一次详细分析',
                            'quoted':False,'negated':False,'third_party':False,'hypothetical':False}
                body = json.dumps({'choices':[{'message':{'content':json.dumps(decision,ensure_ascii=False)},
                                                 'finish_reason':'stop'}]}).encode()
                self.send_response(200)
                self.send_header('Content-Length',str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        remote = ThreadingHTTPServer(('127.0.0.1',0),IntentModel)
        threading.Thread(target=remote.serve_forever,daemon=True).start()
        self.addCleanup(remote.server_close)
        self.addCleanup(remote.shutdown)
        self.c.save_settings({'base_url':f'http://127.0.0.1:{remote.server_port}/v1',
                              'api_key':'fictional-only','api_model':'fixture-intent'})
        parent = self.task(text)
        with patch('app.dialogue.run_process',side_effect=AssertionError('model authorization should create task')):
            result = run_dialogue(self.c.settings(),parent,self.store)
        self.assertEqual(len(seen),1)
        self.assertIn(text,seen[0]['messages'][0]['content'])
        self.assertEqual(len(result['actions']),1)
        child_id = result['actions'][0]['id']
        self.assertIn(child_id,result['reply'])
        child = self.store.get_task(child_id)
        self.assertEqual(child['kind'],'analyze_job')
        self.assertEqual(child['job_id'],self.job['id'])
        self.assertEqual(child['context']['instruction'],text)
        self.assertIn(fact,[f['content'] for f in child['context']['confirmed_facts']])
        self.assertEqual(len([task for task in self.store.state()['tasks'] if task['kind']=='analyze_job']),1)
        again = DialogueSession(self.store,parent).create_special(parent,'analyze_job',intent_decision=validate_decision(
            {'kind':'analyze_job','explicit':True,'evidence':'再对这个岗位做一次详细分析',
             'quoted':False,'negated':False,'third_party':False,'hypothetical':False},text))
        self.assertEqual(again['id'],child_id)

    def test_timeout_and_invalid_intent_keep_direct_rule_as_fallback(self):
        phrase = '请深入分析这个岗位'
        for index, failure in enumerate(('timeout', 'invalid')):
            parent = self.store.create_task({'kind':'companion_chat','job_id':self.job['id'],
                'instruction':phrase,'companion':True,'request_id':f'fallback-{index}'})
            parent = self.store.claim(parent['id'])
            effect = {'side_effect':Problem('意图请求超时')} if failure == 'timeout' else {'return_value':'not-json'}
            with patch('app.dialogue_intent.complete',**effect), \
                 patch('app.dialogue.run_process',side_effect=AssertionError('direct rule must route')):
                result = run_dialogue(self.c.settings(),parent,self.store)
            self.assertEqual(len(result['actions']),1)
            child_id = result['actions'][0]['id']
            self.assertIn(child_id,result['reply'])
            self.assertEqual(self.store.get_task(child_id)['context']['instruction'],phrase)
            self.store.cancel(child_id)
            self.store.cancel(parent['id'])

    def test_unreliable_intent_cannot_report_a_task_missing_from_ledger(self):
        parent = self.task('我最近有点犹豫，想聊聊近况',rid='uncertain')
        hallucination = {'reply':'已创建深入分析任务，正在处理。',
                         'history':[{'user':'我最近有点犹豫，想聊聊近况','assistant':'已创建深入分析任务，正在处理。'}],
                         'usage':{'requests':1,'input_tokens':1,'output_tokens':1},
                         'actions':[]}
        streamed = []
        def fake_chat(*args, **kwargs):
            kwargs['on_delta']('已创建')
            kwargs['on_delta']('已创建深入分析任务，正在处理。')
            return hallucination
        with patch('app.dialogue_intent.complete',return_value='not-json'), \
             patch('app.dialogue.run_process',side_effect=fake_chat):
            result = run_dialogue(self.c.settings(),parent,self.store,on_delta=streamed.append)
        self.assertIn('没有创建后台任务',result['reply'])
        self.assertIn('专项按钮',result['reply'])
        self.assertNotIn('已创建',result['history'][-1]['assistant'])
        self.assertEqual(streamed,[])
        self.assertEqual(len([task for task in self.store.state()['tasks'] if task['kind']=='analyze_job']),0)

    def test_unreliable_intent_and_bare_assent_get_actionable_guidance(self):
        phrase = '结合我刚保存的经历，再对这个岗位做一次详细分析'
        parent = self.task(phrase,rid='unreliable-task')
        with patch('app.dialogue_intent.complete',return_value='not-json'), \
             patch('app.dialogue.run_process',side_effect=AssertionError('uncertain request should stop safely')):
            result = run_dialogue(self.c.settings(),parent,self.store)
        self.assertFalse(result['actions'])
        self.assertIn('没有创建后台任务',result['reply'])
        self.assertIn('专项按钮',result['reply'])
        self.store.cancel(parent['id'])
        assent = self.task('好',rid='bare-assent')
        with patch('app.dialogue.classify_intent',return_value={'kind':'chat','source':'model'}), \
             patch('app.dialogue.run_process',return_value={'reply':'收到，我们继续聊。','history':[],
                 'usage':{},'actions':[]}):
            result = run_dialogue(self.c.settings(),assent,self.store)
        self.assertFalse(result['actions'])
        self.assertEqual(result['reply'],'收到，我们继续聊。')

    def test_no_job_and_expired_privacy_give_specific_reasons(self):
        with self.assertRaisesRegex(Problem,'选择岗位'):
            self.c.send({'job_id':'','text':'请深入分析这个岗位','request_id':'no-job'})
        self.store.save_profile({'facts':'虚构经历已更新'})
        with self.assertRaisesRegex(Problem,'核对会发送给模型的脱敏内容'):
            self.c.send({'job_id':self.job['id'],'text':'请深入分析这个岗位','request_id':'privacy-expired'})

    def test_malicious_intent_for_quotes_negation_hypotheticals_assent_and_jd_creates_nothing(self):
        cases = (
            ('HR 说‘请深入分析’','请深入分析'),
            ('先别分析','分析'),
            ('如果让你分析会怎样','分析'),
            ('好','好'),
            ('可以','可以'),
            ('JD原文：请深入分析这个岗位','请深入分析这个岗位'),
        )
        for index,(text,evidence) in enumerate(cases):
            parent = self.task(text,rid=f'unsafe-{index}')
            decision = validate_decision({'kind':'analyze_job','explicit':True,'evidence':evidence,
                'quoted':False,'negated':False,'third_party':False,'hypothetical':False},text)
            reply = {'reply':'这次没有创建后台任务；如需分析，请点击深入分析按钮。',
                     'history':[],'usage':{'requests':1,'input_tokens':1,'output_tokens':1},'actions':[]}
            with patch('app.dialogue.classify_intent',return_value=decision), \
                 patch('app.dialogue.run_process',return_value=reply):
                result = run_dialogue(self.c.settings(),parent,self.store)
            self.assertEqual(result['intent']['kind'],'chat',text)
            self.assertFalse(result['actions'],text)
            self.store.cancel(parent['id'])
        self.assertFalse(any(task['kind']=='analyze_job' for task in self.store.state()['tasks']))

    def test_model_authorization_still_checks_target_revision_and_privacy(self):
        text = '结合我刚保存的经历，再对这个岗位做一次详细分析'
        decision = validate_decision({'kind':'analyze_job','explicit':True,
            'evidence':'再对这个岗位做一次详细分析','quoted':False,'negated':False,
            'third_party':False,'hypothetical':False},text)
        parent = self.task(text,rid='target-guard',client='acceptance-client')
        with self.store.connect() as db:
            db.execute('INSERT INTO saved_targets VALUES(?,?)',('acceptance-client','other-job'))
        switched = DialogueSession(self.store,parent).create_special(parent,'analyze_job',intent_decision=decision)
        self.assertFalse(switched['ok'])
        self.assertIn('切换目标岗位',switched['error'])
        with self.store.connect() as db:
            db.execute('UPDATE saved_targets SET job_id=?',(self.job['id'],))
        self.store.save_job({**self.job,'jd':'更新后的虚构岗位要求。'})
        changed = DialogueSession(self.store,parent).create_special(parent,'analyze_job',intent_decision=decision)
        self.assertFalse(changed['ok'])
        self.assertIn('目标岗位已变化',changed['error'])
        self.store.cancel(parent['id'])
        fresh = self.task(text,rid='privacy-guard')
        self.store.save_profile({'facts':'档案变更使隐私批准失效'})
        private = DialogueSession(self.store,fresh).create_special(fresh,'analyze_job',intent_decision=decision)
        self.assertFalse(private['ok'])
        self.assertIn('隐私确认已变化',private['error'])
        self.assertFalse(any(task['kind']=='analyze_job' for task in self.store.state()['tasks']))

    def test_numeric_task_id_stays_exact_while_referenced_result_is_redacted(self):
        task_id = 'abcd1234567890123456efab12345678'
        with patch('app.store.uuid.uuid4',return_value=SimpleNamespace(hex=task_id)):
            artifact = self.store.create_task({'kind':'analyze_job','job_id':self.job['id'],
                                               'instruction':'虚构报告'})
        self.assertEqual(artifact['id'],task_id)
        claimed = self.store.claim(task_id)
        self.store.finish(task_id,claimed['claim_token'],{
            'summary':'唯一风险标记：回款节奏。',
            'markdown':'虚构姓名 电话13812345678。唯一风险标记：回款节奏。',
            'primary_output':'虚构姓名 电话13812345678。唯一风险标记：回款节奏。',
            'producer':'synthetic-test','mode':'agent'})
        history = self.c.history(self.job['id'])
        self.assertEqual(history['artifacts'][0]['task_id'],task_id)
        self.assertEqual(artifact_snapshot(self.store,self.job['id'],self.c.settings())[0]['task_id'],task_id)
        chat = self.c.send({'job_id':self.job['id'],'text':'围绕这个结果聊风险',
                            'reference_task_id':task_id,'request_id':'reference-long-id'})['task']
        snapshot = DialogueSession(self.store,self.store.claim(chat['id'])).snapshot(self.store.get_task(chat['id']))
        self.assertEqual(snapshot['selected_reference']['task_id'],task_id)
        self.assertIn('唯一风险标记',snapshot['selected_reference']['result']['primary_output'])
        self.assertNotIn('13812345678',json.dumps(snapshot,ensure_ascii=False))
        self.assertNotIn('虚构姓名',json.dumps(snapshot,ensure_ascii=False))

    def test_history_uses_readable_task_display_name(self):
        first = self.c.send({'job_id':self.job['id'],'kind':'analyze_job','text':'第一次分析','request_id':'display-one'})['task']
        self.store.cancel(first['id'])
        second = self.c.send({'job_id':self.job['id'],'kind':'analyze_job','text':'第二次分析','request_id':'display-two'})['task']
        names = {item['task_id']: item['display_name'] for item in self.c.history(self.job['id'])['turns']}
        self.assertEqual(names[first['id']], '分析 1')
        self.assertEqual(names[second['id']], '分析 2')
        self.assertNotIn('analyze_job', json.dumps(names, ensure_ascii=False))

    def test_model_can_route_hr_chat_without_blocking_on_its_parent_chat(self):
        text='根据我刚补充的内容，再写一条HR招呼。'
        t=self.task(text)
        decision=validate_decision({'kind':'suggest_reply','explicit':True,'evidence':'再写一条HR招呼',
            'quoted':False,'negated':False,'third_party':False,'hypothetical':False},text)
        receipt=DialogueSession(self.store,t).create_special(t,'suggest_reply',intent_decision=decision)
        self.assertTrue(receipt['ok'],receipt)
        self.assertEqual(self.store.get_task(receipt['id'])['kind'],'suggest_reply')

    def test_confirmed_chat_experience_persists_and_reaches_next_dialogue(self):
        original='我在实习时独立整理过客户反馈，并每周给团队做复盘。'
        task=self.c.send({'job_id':self.job['id'],'text':original,'request_id':'fact-origin'})['task']
        claimed=self.store.claim(task['id'])
        self.store.finish(task['id'],claimed['claim_token'],{
            'summary':'已收到','decision':'','strategy':'','primary_output':'这段经历可以作为复盘证据。',
            'questions':[],'markdown':'用户已补充本人经历。','mode':'agent','producer':'test','fact_candidate':True})
        self.assertTrue(next(t for t in self.c.history(self.job['id'])['turns'] if t['task_id']==task['id'])['fact_candidate'])
        self.assertEqual(Journey(self.store).state()['facts'],[])
        journey=Journey(self.store)
        draft=journey.chat_fact_draft({'task_id':task['id']})
        self.assertEqual(draft['content'],original)
        with self.assertRaises(Problem):
            journey.fact({'chat_task_id':task['id'],'content':original,'confirmed':False})
        saved=journey.fact({'chat_task_id':task['id'],'content':original,'category':'实习','confirmed':True})
        fact=next(f for f in saved['facts'] if f['id']=='chat-'+task['id'])
        self.assertEqual(fact['content'],original)
        self.assertFalse(self.c.ready())
        with self.assertRaises(Problem):
            self.c.send({'job_id':self.job['id'],'text':'先不重新确认','request_id':'before-approval'})
        revision=self.store.state()['profile']['revision']
        journey.fact({'chat_task_id':task['id'],'content':original,'category':'实习','confirmed':True})
        self.assertEqual(self.store.state()['profile']['revision'],revision)
        self.c.approve({'token':self.c.preview_profile()['token'],'confirmed':True})
        following=self.c.send({'job_id':self.job['id'],'text':'这段复盘经历适合怎么写？','request_id':'fact-followup'})['task']
        self.assertIn(original,[f['content'] for f in self.store.get_task(following['id'])['context']['confirmed_facts']])
        claimed_following=self.store.claim(following['id'])
        self.assertIn(original,[f['content'] for f in DialogueSession(self.store,claimed_following).snapshot(claimed_following)['confirmed_facts']])
        analysis=self.c.send({'job_id':self.job['id'],'kind':'analyze_job','text':'结合补充经历重新分析','request_id':'fact-analysis'})['task']
        self.assertIn(original,[f['content'] for f in self.store.get_task(analysis['id'])['context']['confirmed_facts']])

    def test_chat_only_experience_is_not_claimed_as_used_in_new_analysis(self):
        marker = 'LIME-UNCONFIRMED-77'
        original = '我在实习中完成过代号 ' + marker + ' 的客户复盘。'
        chat = self.c.send({'job_id':self.job['id'],'text':original,'request_id':'unconfirmed-chat'})['task']
        claimed = self.store.claim(chat['id'])
        self.store.finish(chat['id'],claimed['claim_token'],{
            'summary':'用户提及 ' + marker + '，尚未核对入档。',
            'markdown':'用户提及 ' + marker + '，尚未核对入档。',
            'primary_output':'可以核对这段经历后记入档案。',
            'producer':'synthetic-test','mode':'agent'})
        before = self.c.send({'job_id':self.job['id'],'kind':'analyze_job',
                              'text':'根据我刚才聊天补充的经历再分析这个岗位',
                              'request_id':'analysis-before-fact'})['task']
        self.assertFalse(self.store.get_task(before['id'])['context']['confirmed_facts'])
        self.assertNotIn(marker,prompt_for(self.store.get_task(before['id']),self.c.settings()))
        self.store.cancel(before['id'])
        Journey(self.store).fact({'chat_task_id':chat['id'],'category':'实习',
                                  'content':original,'confirmed':True})
        self.c.approve({'token':self.c.preview_profile()['token'],'confirmed':True})
        after = self.c.send({'job_id':self.job['id'],'kind':'analyze_job',
                             'text':'根据我保存的经历再分析这个岗位',
                             'request_id':'analysis-after-fact'})['task']
        self.assertIn(marker,prompt_for(self.store.get_task(after['id']),self.c.settings()))

    def test_deep_analysis_phrasing_reaches_intent_model_and_legacy_route_remains(self):
        for index, text in enumerate(('深度分析一下该岗位', '深度分析一下', '请深入分析这个岗位', '帮我详细分析这个岗位')):
            self.assertTrue(explicit_deep_analysis_request(text), text)
            self.assertTrue(analysis_authorized(text), text)
            task = self.c.send({'job_id': self.job['id'], 'text': text,
                                'request_id': f'deep-{index}'})['task']
            self.assertEqual(task['kind'], 'companion_chat')
            self.assertEqual(self.store.get_task(task['id'])['context']['instruction'], text)
            self.store.cancel(task['id'])
        self.c.save_settings({'dialogue_agent':False})
        legacy = self.c.send({'job_id':self.job['id'], 'text':'请深入分析这个岗位',
                              'request_id':'legacy-deep'})['task']
        self.assertEqual(legacy['kind'], 'analyze_job')
        self.store.cancel(legacy['id'])
        for text in ('HR说深度分析一下该岗位', '请不要深度分析这个岗位',
                     '如果方便就深度分析一下', '“深度分析一下该岗位”是什么意思'):
            self.assertFalse(explicit_deep_analysis_request(text), text)
            self.assertFalse(analysis_authorized(text), text)

    def test_valid_model_chat_overrides_old_analysis_rule(self):
        parent = self.task('请深入分析这个岗位', rid='model-chat-rule')
        reply = {'reply':'可以先聊聊你最在意的匹配点。','history':[],
                 'usage':{'requests':1,'input_tokens':1,'output_tokens':1},'actions':[]}
        with patch('app.dialogue.classify_intent',return_value={'kind':'chat','source':'model'}), \
             patch('app.dialogue.run_process',return_value=reply):
            result = run_dialogue(self.c.settings(),parent,self.store)
        self.assertEqual(result['reply'],reply['reply'])
        self.assertFalse(result['actions'])
        self.assertFalse(any(t['kind']=='analyze_job' for t in self.store.state()['tasks']))

    def test_selected_result_discussion_cannot_create_another_analysis(self):
        artifact = self.store.create_task({'kind':'analyze_job','job_id':self.job['id'],
                                           'instruction':'第一次分析'})
        claimed = self.store.claim(artifact['id'])
        self.store.finish(artifact['id'],claimed['claim_token'],{
            'summary':'长期发展风险在于客户复购。','primary_output':'长期发展风险在于客户复购。',
            'markdown':'长期发展风险在于客户复购。','producer':'synthetic-test','mode':'agent'})
        text = '/深入分析 该岗位是否适合长期发展？'
        task = self.c.send({'job_id':self.job['id'],'text':text,
                            'reference_task_id':artifact['id'],'request_id':'cited-question'})['task']
        self.assertEqual(task['kind'],'companion_chat')
        self.assertEqual(self.store.get_task(task['id'])['context']['reference_task_id'],artifact['id'])
        parent = self.store.claim(task['id'])
        session = DialogueSession(self.store,parent)
        self.assertEqual(session.snapshot(parent)['selected_reference']['task_id'],artifact['id'])
        with self.assertRaisesRegex(Problem,'用于讨论'):
            self.store.create_task({'kind':'analyze_job','job_id':self.job['id']},
                                   dialogue_parent=(parent['id'],parent['claim_token']))
        reply = {'reply':'这份结果提示客户复购风险，长期发展要继续核实留存情况。',
                 'history':[],'usage':{'requests':1,'input_tokens':1,'output_tokens':1},'actions':[]}
        with patch('app.dialogue.classify_intent',side_effect=AssertionError('引用不应进入建单意图判断')), \
             patch('app.dialogue.run_process',return_value=reply):
            result = run_dialogue(self.c.settings(),parent,self.store)
        self.assertEqual(result['reply'],reply['reply'])
        self.assertFalse(result['actions'])
        self.assertEqual(len([t for t in self.store.state()['tasks'] if t['kind']=='analyze_job']),1)

    def test_screenshot_hr_question_is_chat_even_if_model_votes_for_analysis(self):
        text = 'HR 没深聊几句就说可以来面试看看，请深入分析分析，这个岗位是否真的合适，感觉岗位留不下人'
        parent = self.task(text,rid='hr-question')
        decision = validate_decision({'kind':'analyze_job','explicit':True,
            'evidence':'请深入分析分析','quoted':False,'negated':False,
            'third_party':False,'hypothetical':False},text)
        self.assertEqual(decision['kind'],'chat')
        reply = {'reply':'HR 的邀请只说明愿意面试，不能证明岗位稳定；可以问离职率和团队目标。',
                 'history':[],'usage':{'requests':1,'input_tokens':1,'output_tokens':1},'actions':[]}
        with patch('app.dialogue.classify_intent',return_value=decision), \
             patch('app.dialogue.run_process',return_value=reply):
            result = run_dialogue(self.c.settings(),parent,self.store)
        self.assertEqual(result['reply'],reply['reply'])
        self.assertFalse(result['actions'])
        self.assertFalse(any(t['kind']=='analyze_job' for t in self.store.state()['tasks']))

    def test_live_api_route_and_explicit_button_preserved(self):
        t=self.task(); self.store.cancel(t['id'])
        direct=self.c.send({'job_id':self.job['id'],'kind':'analyze_job','text':'','request_id':'button'})['task']
        self.assertEqual(direct['kind'],'analyze_job')
        self.store.cancel(direct['id'])
        self.c.save_settings({'dialogue_agent':False})
        legacy=self.c.send({'job_id':self.job['id'],'text':'请深入分析这个岗位','request_id':'legacy'})['task']
        self.assertEqual(legacy['kind'],'analyze_job')

    def test_atomic_cross_connection_idempotency_and_source(self):
        t=self.task()
        def make(_):
            store=Store(self.temp.name)
            return store.create_task({'kind':'analyze_job','job_id':self.job['id'],'instruction':'模型改写'},dialogue_parent=(t['id'],t['claim_token']))
        with ThreadPoolExecutor(max_workers=2) as pool: children=list(pool.map(make,range(2)))
        self.assertEqual(children[0]['id'],children[1]['id'])
        full=self.store.get_task(children[0]['id'])
        self.assertEqual(full['context']['instruction'],t['context']['instruction'])
        self.assertEqual(full['context']['dialogue_source_task_id'],t['id'])
        snapshot=DialogueSession(self.store,t).snapshot(t)
        self.assertEqual(snapshot['task_state'][0]['source_task_id'],t['id'])
        self.assertEqual(snapshot['task_state'][0]['status'],'queued')
        self.assertNotIn('prior_results',snapshot)
        self.assertNotIn('dialogue',snapshot)
        self.assertNotIn('13812345678',json.dumps(snapshot))
        self.assertNotIn('虚构姓名',json.dumps(snapshot,ensure_ascii=False))

    def test_cancel_privacy_revision_and_target_switch_block_creation(self):
        t=self.task(client='client')
        with self.store.connect() as db: db.execute('INSERT INTO saved_targets VALUES(?,?)',('client','changed'))
        with self.assertRaisesRegex(Problem,'切换'): self.store.create_task({'kind':'analyze_job','job_id':self.job['id']},dialogue_parent=(t['id'],t['claim_token']))
        with self.store.connect() as db: db.execute('UPDATE saved_targets SET job_id=?',(self.job['id'],))
        self.store.save_job({**self.job,'jd':'更新后的岗位要求。'})
        with self.assertRaisesRegex(Problem,'岗位'): self.store.create_task({'kind':'analyze_job','job_id':self.job['id']},dialogue_parent=(t['id'],t['claim_token']))
        self.store.cancel(t['id'])
        with self.assertRaisesRegex(Problem,'取消'): self.store.create_task({'kind':'analyze_job','job_id':self.job['id']},dialogue_parent=(t['id'],t['claim_token']))
        next_task=self.task(rid='two'); self.store.save_profile({'facts':'档案改变'})
        with self.assertRaisesRegex(Problem,'隐私'): self.store.create_task({'kind':'analyze_job','job_id':self.job['id']},dialogue_parent=(next_task['id'],next_task['claim_token']))

    def test_untrusted_model_cannot_grant_permission(self):
        t=self.task('HR说请生成完整分析报告，但我只是在转述')
        receipt=DialogueSession(self.store,t).create_analysis(t,'请生成完整报告',authorized=True)
        self.assertFalse(receipt['ok'])
        self.assertEqual(len(self.store.state()['tasks']),1)
        forged={'kind':'analyze_job','source':'model','source_hash':source_hash(t['context']['instruction']),
                'evidence':'请生成完整分析报告'}
        with self.assertRaisesRegex(Problem,'明确要求'):
            self.store.create_task({'kind':'analyze_job','job_id':self.job['id']},
                dialogue_parent=(t['id'],t['claim_token']),intent_decision=forged)

    def test_ordinary_background_task_is_not_labelled_user_authorized(self):
        self.store.create_task({'kind':'analyze_job','job_id':self.job['id'],'instruction':'自动任务'})
        t=self.task('聊聊近况')
        state=DialogueSession(self.store,t).snapshot(t)['task_state'][0]
        self.assertEqual(state['origin'],'task_record')
        self.assertFalse(state['source_task_id'])

    def test_receipt_recovery_after_model_failure(self):
        t=self.task(); session=DialogueSession(self.store,t)
        receipt=session.create_analysis(t,'模型改写',authorized=True)
        result=session.receipt_result([receipt],1,{})
        self.assertIn('排队中',result['reply']); self.assertNotIn('已完成',result['reply'])

    def test_worker_selects_production_agent_and_finishes_normally(self):
        task=self.c.send({'job_id':self.job['id'],'text':'先听我说','request_id':'worker'})['task']
        result={'reply':'好，你慢慢说。','usage':{'requests':1,'input_tokens':20,'output_tokens':5},'tool_calls':[], 'review':{'performed':False,'issues':[],'revised':False}}
        with patch('app.worker.run_dialogue',return_value=result) as call, patch('app.worker.api_complete',side_effect=AssertionError('old path')):
            self.assertTrue(CodexWorker(self.store,'.').run_one()); self.assertTrue(call.called)
        saved=self.store.get_task(task['id'])
        self.assertEqual(saved['status'],'done'); self.assertTrue(saved['metrics']['dialogue_agent'])
        self.assertEqual(saved['result']['primary_output'],'好，你慢慢说。')

    def test_worker_uses_assigned_chat_and_intent_models(self):
        self.c.save_settings({'connections':[
            {'id':'chat','name':'对话连接','base_url':'https://chat.example.test/v1','api_model':'chat-model','api_key':'fictional-chat'},
            {'id':'intent','name':'意图连接','base_url':'https://intent.example.test/v1','api_model':'intent-model','api_key':'fictional-intent'},
        ],'task_models':{
            'daily_chat':{'connection_id':'chat','model':'chat-model'},
            'intent_judgment':{'connection_id':'intent','model':'intent-model'},
        },'task_models_confirmed':True})
        task=self.c.send({'job_id':self.job['id'],'text':'先听我说','request_id':'routed-worker'})['task']
        result={'reply':'好，你慢慢说。','usage':{'requests':2,'input_tokens':20,'output_tokens':5},
                'tool_calls':[],'review':{'performed':False,'issues':[],'revised':False},
                'intent':{'source':'model','kind':'chat'}}
        with patch('app.worker.run_dialogue',return_value=result) as call:
            self.assertTrue(CodexWorker(self.store,'.').run_one())
        args, kwargs=call.call_args
        self.assertEqual(args[0]['api_model'],'chat-model')
        self.assertEqual(kwargs['intent_settings']['api_model'],'intent-model')
        self.assertEqual(self.store.get_task(task['id'])['metrics']['model'],'chat-model')

    def test_missing_assigned_model_fails_task_without_leaving_a_running_lease(self):
        task=self.c.send({'job_id':self.job['id'],'text':'先听我说','request_id':'invalid-route'})['task']
        with patch('app.worker.resolve_task_model',side_effect=Problem('指派连接已失效')):
            self.assertTrue(CodexWorker(self.store,'.').run_one())
        saved=self.store.get_task(task['id'])
        self.assertEqual(saved['status'],'failed')
        self.assertIn('指派连接已失效',saved['error_text'])

if __name__=='__main__': unittest.main()
