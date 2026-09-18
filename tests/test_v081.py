import io
import json
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from app.store import Store, Problem
from app.companion import Companion
from app.worker import CodexWorker, prompt_for
from app.resume_restore import preview_resume, checked_content
from app.resume_export import export_resume


class FixTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.s=Store(self.tmp.name)
        self.s.save_profile({'name':'虚构林同学','facts':'姓名：虚构林同学\n手机号：13800138000\n邮箱：demo@example.com\n负责活动协调','preferences':'杭州'})
        self.c=Companion(self.s);self.c.save_settings({'provider':'api','api_model':'mock'})
        self.c.approve({'token':self.c.preview_profile()['token'],'confirmed':True})
        self.job=self.s.save_job({'title':'运营助理','company':'虚构公司','jd':'活动协调'})

    def send(self,kind,req):
        return self.c.send({'kind':kind,'job_id':self.job['id'],'request_id':req,'text':'测试问题'})['task']

    def version(self,content):
        t=self.send('tailor_resume','resume');claim=self.s.claim(t['id'])
        self.s.finish(t['id'],claim['claim_token'],{'mode':'agent','producer':'fixture','summary':'完成','primary_output':content,'markdown':'说明'})
        return self.c.accept_resume({'task_id':t['id'],'content':content})['id'],t['id']

    def test_background_and_chat_concurrent_but_same_lane_duplicate_rejected(self):
        started=threading.Event();release=threading.Event();self.addCleanup(release.set)
        r=self.send('tailor_resume','resume')
        def mock(settings,prompt,structured=False,**kwargs):
            if structured:
                started.set();release.wait(4)
                return json.dumps({'mode':'agent','producer':'mock','summary':'完成','primary_output':'活动协调','markdown':'依据'})
            return '我们可以继续聊。'
        with patch('app.worker.api_complete',side_effect=mock):
            thread=threading.Thread(target=CodexWorker(self.s,Path.cwd(),lane='background').run_one)
            thread.start();self.assertTrue(started.wait(2))
            c=self.send('companion_chat','chat')
            with self.assertRaises(Problem):self.send('quick_analysis','again')
            with self.assertRaises(Problem):self.send('analyze_job','background-again')
            self.assertTrue(CodexWorker(self.s,Path.cwd(),lane='chat').run_one())
            self.assertEqual(self.s.get_task(c['id'])['status'],'done')
            self.assertEqual(self.s.get_task(r['id'])['status'],'running')
            release.set();thread.join(4)
            self.assertEqual(self.s.get_task(r['id'])['status'],'done')

    def test_retry_lanes_and_idempotency(self):
        r=self.send('tailor_resume','resume');claim=self.s.claim(r['id']);self.s.fail(r['id'],claim['claim_token'],'test','test')
        c=self.send('companion_chat','chat');self.s.retry(r['id'])
        self.assertEqual(self.send('companion_chat','chat')['id'],c['id'])
        self.assertEqual(len(self.s.queued_tasks('background')),1)
        self.assertEqual(len(self.s.queued_tasks('chat')),1)

    def test_local_restore_export_does_not_change_prompt_or_saved_version(self):
        v,t=self.version('姓名：[本地隐去]\n手机号：[本地隐去]\n邮箱：[邮箱]\n教育经历\n本科\n工作经历\n负责活动协调')
        task=self.s.get_task(t);before=prompt_for(task,self.c.settings())
        preview=preview_resume(self.s,v)
        for x in ('虚构林同学','13800138000','demo@example.com'):self.assertIn(x,preview['content']);self.assertNotIn(x,before)
        content=checked_content({'confirmed':True,'content':preview['content']})
        data,_=export_resume(self.s,v,'docx',content)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml=z.read('word/document.xml').decode();self.assertIn('13800138000',xml);self.assertIn('虚构林同学',xml)
        self.assertEqual(before,prompt_for(self.s.get_task(t),self.c.settings()))
        with self.s.connect() as db:self.assertIn('[本地隐去]',db.execute('SELECT content FROM resume_versions WHERE id=?',(v,)).fetchone()[0])
        self.s.save_profile({'name':'另一个人','facts':'手机号：13900139000','preferences':''})
        self.assertNotIn('13900139000',preview_resume(self.s,v)['content'])

    def test_missing_header_and_ambiguous_placeholders(self):
        v,_=self.version('工作经历\n在[本地隐去]负责活动协调')
        p=preview_resume(self.s,v);self.assertTrue(p['content'].startswith('姓名：虚构林同学'))
        self.assertIn('13800138000',p['content'])
        with self.assertRaises(Problem):checked_content({'confirmed':True,'content':p['content']})
        with self.assertRaises(Problem):checked_content({'content':'正常正文'})

    def test_duplicate_phones_not_guessed(self):
        self.s.save_profile({'name':'虚构林同学','facts':'手机号：13800138000\n手机号：13900139000','preferences':''})
        self.c.approve({'token':self.c.preview_profile()['token'],'confirmed':True})
        v,_=self.version('手机号：[手机号]\n负责协调')
        p=preview_resume(self.s,v);self.assertNotIn('13800138000',p['content']);self.assertIn('多个值',''.join(p['warnings']))

    def test_unlabelled_resume_contacts_restore_without_jd_contacts(self):
        self.s.save_profile({'name':'虚构林同学','facts':'13800138000 | demo@example.com\n活动协调','preferences':''})
        self.c.approve({'token':self.c.preview_profile()['token'],'confirmed':True})
        self.s.save_job({**self.job,'jd':'招聘咨询：13900139000 hr@example.net'})
        v,_=self.version('工作经历\n活动协调')
        p=preview_resume(self.s,v)['content']
        self.assertIn('13800138000',p);self.assertIn('demo@example.com',p)
        self.assertNotIn('13900139000',p);self.assertNotIn('hr@example.net',p)


if __name__=='__main__':unittest.main()
