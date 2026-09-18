import json
import tempfile
import unittest
from unittest.mock import patch
from app.closing import declares_joined, AUTHOR_NOTE
from app.companion import Companion
from app.store import Store, Problem
from app.worker import CodexWorker, prompt_for
from app.journey import Journey


class ClosingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.s=Store(self.tmp.name);self.c=Companion(self.s)
        self.s.save_profile({'name':'虚构同学','facts':'负责校园活动协调','preferences':''})
        self.c.save_settings({'provider':'api'})
        self.c.approve({'token':self.c.preview_profile()['token'],'confirmed':True})

    def send(self,text,kind='companion_chat',rid='one'):
        return self.c.send({'job_id':'','kind':kind,'text':text,'request_id':rid})['task']

    def test_explicit_first_person_only(self):
        for s in ['我入职了','我已经入职了，谢谢你！','告诉你个好消息，我今天正式入职啦！','我正式入职']:
            self.assertTrue(declares_joined(s),s)
        for s in ['准备入职','我明天入职','我还没入职','我没有入职','我拿到offer了','朋友入职了','他说我入职了','如果我入职了','“我入职了”怎么回复','我入职了吗？','我入职了？不确定','我入职了，但不是正式工作','帮我写我入职了的文案']:
            self.assertFalse(declares_joined(s),s)

    def test_closing_model_plus_local_author_and_snapshot(self):
        t=self.send('我已经入职了，谢谢你！')
        self.assertEqual(t['kind'],'closing_message')
        self.assertEqual(self.send('我已经入职了，谢谢你！')['id'],t['id'])
        p=prompt_for(self.s.get_task(t['id']),self.c.settings())
        self.assertNotIn(AUTHOR_NOTE,p);self.assertNotIn('已确认投递 0 次',p)
        with patch('app.worker.api_complete',return_value='祝你在新的阶段过得踏实。') as call:
            CodexWorker(self.s,'.',lane='chat').run_one()
            self.assertEqual(call.call_count,1)
        result=self.s.get_task(t['id'])['result']['primary_output']
        self.assertIn('祝你',result);self.assertIn('已确认投递 0 次',result);self.assertIn(AUTHOR_NOTE,result)
        self.assertEqual(Journey(self.s).state()['events'],[])
        follow=self.send('谢谢，我想先休息一下',rid='two')
        self.assertNotIn(AUTHOR_NOTE,prompt_for(self.s.get_task(follow['id']),self.c.settings()))

    def test_rest_is_model_chat_not_success(self):
        t=self.send('',kind='rest_message')
        with patch('app.worker.api_complete',return_value='今天先休息，我们下次再聊。'):
            CodexWorker(self.s,'.',lane='chat').run_one()
        output=self.s.get_task(t['id'])['result']['primary_output']
        self.assertNotIn(AUTHOR_NOTE,output);self.assertNotIn('本机记录',output)
        self.assertEqual(Journey(self.s).state()['events'],[])

    def test_forced_closing_and_record_cannot_trigger(self):
        with self.assertRaises(Problem):self.send('我入职了',kind='closing_message')
        with self.assertRaises(Problem):self.s.create_task({'kind':'closing_message','job_id':'','companion':True,'instruction':'还没入职','request_id':'bad'})
        job=self.s.save_job({'title':'测试岗','company':'测试公司','jd':'负责协调'})
        Journey(self.s).event({'kind':'joined','job_id':job['id'],'confirmed':True,'request_id':'event'})
        self.assertEqual(self.s.state()['tasks'],[])


if __name__=='__main__':unittest.main()
