from app.version import EXTENSION_ID
import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch
from app.store import Store, Problem, task_lane
from app.companion import Companion
from app.journey import Journey
from app.milestones import Milestones
from app.worker import CodexWorker, prompt_for
from app.server import make_server


class V09Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.s=Store(self.tmp.name);self.c=Companion(self.s);self.j=Journey(self.s);self.m=Milestones(self.s)
        self.s.save_profile({'name':'虚构测试者','facts':'协调5名同学完成活动。手机号：13800138000','preferences':'杭州'})
        self.c.save_settings({'provider':'api','persona':'gentle'})
        self.c.approve({'token':self.c.preview_profile()['token'],'confirmed':True})
        self.job=self.s.save_job({'title':'运营助理','company':'示例软件公司','jd':'负责商家使用指导与需求反馈'})

    def send(self,kind,text='',rid='one'):
        return self.c.send({'job_id':self.job['id'],'kind':kind,'text':text,'request_id':rid})['task']

    def event(self,kind,rid):
        return self.j.event({'job_id':self.job['id'],'kind':kind,'note':'私人备注不应进入分享文本','confirmed':True,'request_id':rid})

    def test_interview_task_context_privacy_and_concurrent_chat(self):
        t=self.send('interview_prep','线上业务一面\n会议密码：secret123\n手机号：13800138000')
        raw=self.s.get_task(t['id']);p=prompt_for(raw,self.c.settings())
        self.assertIn('STAR',p);self.assertIn('商家使用指导',p);self.assertIn('协调5名',p)
        self.assertIn('不是独立证据',p);self.assertIn('不要把“协调5名同学”',p)
        self.assertNotIn('secret123',p);self.assertNotIn('13800138000',p);self.assertNotIn('虚构测试者',p)
        self.assertEqual(task_lane(t['kind']),'background')
        self.send('companion_chat','有点紧张','chat')
        with self.assertRaises(Problem):self.send('interview_review','问了协作经历，我没能讲清楚分工。','review')
        self.assertTrue(self.c.history(self.job['id'])['turns'][0]['workbench'])
        self.assertEqual(self.j.state()['events'],[])

    def test_interview_worker_result_and_review_requires_actual_notes(self):
        with self.assertRaises(Problem):self.send('interview_review')
        t=self.send('interview_prep')
        result={'summary':'准备重点','decision':'讲清协调和反馈','strategy':'主打真实活动经历','primary_output':'面试准备卡\n两件事\n自我介绍\nSTAR经历','questions':['轮次是什么？'],'markdown':'基于岗位与真实经历'}
        with patch('app.worker.api_complete',return_value=json.dumps(result)):
            CodexWorker(self.s,'.',lane='background').run_one()
        self.assertEqual(self.s.get_task(t['id'])['status'],'done')
        review=self.send('interview_review','实际问了如何协调不同意见，我只回答沟通，没讲清行动。','review')
        p=prompt_for(self.s.get_task(review['id']),self.c.settings());self.assertIn('不根据沉默',p)
        self.assertIn('面试准备卡',p)
        self.assertEqual(self.j.state()['events'],[])

    def test_retrospective_empty_not_success_and_no_fake_statistics(self):
        r=self.m.retrospective();self.assertFalse(r['success']);self.assertEqual(r['dates'],'尚无记录')
        self.assertEqual(r['summary']['applications'],0);self.assertEqual(r['summary']['resume_versions'],0)
        self.send('suggest_reply');r=self.m.retrospective();self.assertEqual(r['summary']['greetings'],0)

    def test_success_requires_confirmation_and_undo_revokes(self):
        with self.assertRaises(Problem):self.j.event({'job_id':self.job['id'],'kind':'offer','request_id':'bad'})
        for kind,rid in [('applied','a'),('applied','b'),('greeting_sent','g'),('interview','i'),('offer','o')]:self.event(kind,rid)
        self.event('offer','o')
        r=self.m.retrospective();self.assertTrue(r['success'])
        self.assertEqual(r['summary']['applications'],2);self.assertEqual(r['summary']['companies'],1)
        self.assertEqual(r['summary']['offers'],1);self.assertEqual(r['summary']['greetings'],1)
        for secret in ('私人备注','虚构测试者','13800138000','示例软件公司'):self.assertNotIn(secret,r['text'])
        self.assertIn('作者',r['text']);self.j.remove_event({'id':'o'});self.assertFalse(self.m.retrospective()['success'])

    def test_span_includes_accepted_versions_but_not_generated_tasks(self):
        self.event('applied','a')
        with self.s.connect() as db:
            db.execute('UPDATE career_events SET at=172800')
            db.execute('INSERT INTO resume_versions VALUES(?,?,?,?,?)',('v','job','task','稿件',0))
        r=self.m.retrospective();self.assertEqual(r['summary']['span_days'],2)
        self.assertEqual(self.j.state()['summary']['span_days'],2)
        self.assertEqual(r['summary']['resume_versions'],1)

    def test_blessing_local_persona_and_opt_out_persists(self):
        with patch('app.worker.api_complete',side_effect=AssertionError('no model')):
            gentle=self.m.blessing()['text'];self.c.save_settings({'persona':'direct','celebrations':False})
            direct=self.m.blessing()['text'];self.assertNotEqual(gentle,direct)
            self.assertFalse(Companion(Store(self.tmp.name)).settings()['celebrations'])
            with self.assertRaises(Problem):self.m.blessing('offer')
            self.assertTrue(self.m.retrospective()['local'])

    def test_http_privacy_boundary_no_unpaired_bridge(self):
        server=make_server(self.tmp.name,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        base='http://127.0.0.1:'+str(server.server_port)
        token=server.session_token
        def post(path,headers):
            return urllib.request.urlopen(urllib.request.Request(base+path,b'{}',{'Content-Type':'application/json',**headers}))
        with self.assertRaises(urllib.error.HTTPError):post('/api/retrospective',{})
        with self.assertRaises(urllib.error.HTTPError):post('/bridge/blessing',{'Origin':'chrome-extension://'+EXTENSION_ID})
        with self.assertRaises(urllib.error.HTTPError) as error:post('/api/retrospective',{'X-Local-Token':token})
        self.assertEqual(error.exception.code,410)


if __name__=='__main__':unittest.main()
