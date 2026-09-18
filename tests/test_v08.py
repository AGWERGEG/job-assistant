import io
import json
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

from app.store import Store,Problem
from app.journey import Journey
from app.companion import Companion
from app.bridge import Bridge
from app.worker import CodexWorker
from app.providers import complete
from app.resume_export import export_resume
from app import runtime


class V08Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.s=Store(self.tmp.name);self.s.save_profile({'name':'测试甲','facts':'负责客户沟通与活动复盘','preferences':'杭州'})
        self.c=Companion(self.s);self.j=Journey(self.s)
        self.c.approve({'token':self.c.preview_profile()['token'],'confirmed':True})
        self.job=self.s.save_job({'title':'运营助理','company':'公司A','jd':'负责客户沟通和复盘','conversation':'初次招呼'})

    def task(self,kind='quick_analysis',request='request1'):
        return self.c.send({'job_id':self.job['id'],'kind':kind,'request_id':request})['task']

    def done(self,t,content='教育经历\n本科毕业\n工作经历\n负责客户沟通与活动复盘'):
        c=self.s.claim(t['id']);self.s.finish(t['id'],c['claim_token'],{'mode':'agent','producer':'test','summary':'完成','primary_output':content,'markdown':'依据来自已确认事实'})
        return self.c.accept_resume({'task_id':t['id'],'content':content})['id']

    def test_confirmed_events_counts_undo_idempotency(self):
        with self.assertRaises(Problem):self.j.event({'kind':'applied','job_id':self.job['id'],'request_id':'x'})
        v={'kind':'applied','job_id':self.job['id'],'request_id':'a','confirmed':True}
        self.j.event(v);self.j.event(v)
        self.j.event({**v,'request_id':'b','kind':'greeting_sent'})
        state=self.j.state()['summary'];self.assertEqual(state['companies'],1);self.assertEqual(state['greetings'],1);self.assertEqual(state['applications'],1)
        self.j.remove_event({'id':'b'});self.assertEqual(self.j.state()['summary']['greetings'],0)

    def test_facts_require_review_and_enter_prompt(self):
        self.j.fact({'category':'工作','content':'我负责6个客户的需求访谈','source':'用户纠正','confirmed':True})
        self.assertFalse(self.c.ready())
        preview=self.c.preview_profile();self.assertIn('6个客户',str(preview))
        self.c.approve({'token':preview['token'],'confirmed':True})
        t=self.task();self.assertIn('6个客户',json.dumps(self.s.get_task(t['id'])['context'],ensure_ascii=False))

    def test_restore_after_backend_restart_and_revoke(self):
        b=Bridge(self.s);client='chrome-extension://'+'a'*32
        payload={'job_key':'job123','url':'https://www.zhipin.com/job_detail/job123.html','title':'运营','company':'公司A','jd':'负责客户沟通、校园活动和日常运营复盘。'*4}
        saved=b.capture(client,{'scope':'old','seq':1,'capture':payload})['job']
        b.companion_action(client,{'scope':'old','seq':1},'confirm')
        fresh=Bridge(Store(self.tmp.name));r=fresh.restore(client,{'scope':'new','seq':1})
        self.assertEqual(r['job']['id'],saved['id']);self.assertEqual(r['capture']['job_key'],'job123')
        self.assertIsNone(fresh.restore('other',{'scope':'new','seq':1})['job'])
        fresh.revoke_all();self.assertIsNone(fresh.restore(client,{'scope':'new2','seq':1})['job'])

    def test_bridge_cancel_never_returns_private_task_context(self):
        b=Bridge(self.s);client='chrome-extension://'+'c'*32
        capture={'job_key':'job456','url':'https://www.zhipin.com/job_detail/job456.html','title':'运营','company':'公司A','jd':'负责客户沟通、校园活动和日常运营复盘。'*4}
        b.capture(client,{'scope':'s','seq':1,'capture':capture});b.companion_action(client,{'scope':'s','seq':1},'confirm')
        t=b.companion_action(client,{'scope':'s','seq':1,'text':'帮我看岗位','kind':'companion_chat','request_id':'a'},'talk')['task']
        r=b.companion_action(client,{'scope':'s','seq':1,'task_id':t['id']},'cancel')
        self.assertNotIn('context',r['task']);self.assertNotIn('claim_token',r['task'])

    def test_cancel_running_rejects_late_result_and_progress(self):
        t=self.task();c=self.s.claim(t['id'])
        self.s.progress(t['id'],c['claim_token'],'部分回复',{})
        self.s.cancel(t['id']);self.s.progress(t['id'],c['claim_token'],'不应回来',{})
        self.assertEqual(self.s.get_task(t['id'])['partial_text'],'')
        with self.assertRaises(Problem):self.s.finish(t['id'],c['claim_token'],{'mode':'agent','producer':'test','summary':'late','markdown':'late'})

    def test_codex_cancel_stops_process_without_late_write(self):
        import sys
        from app.worker import run_codex
        start=time.monotonic()
        with self.assertRaises(Problem):
            run_codex([sys.executable,'-c','import time; time.sleep(10)'],'',Path(self.tmp.name),15,lambda:time.monotonic()-start>.3)
        self.assertLess(time.monotonic()-start,3)

    def test_streaming_private_term_split_not_published(self):
        self.c.save_settings({'provider':'api','base_url':'http://127.0.0.1:1/v1','api_model':'fake','private_terms':'陈晓雨'})
        self.c.approve({'token':self.c.preview_profile()['token'],'confirmed':True})
        t=self.task();observed=[]
        def fake(settings,prompt,**kwargs):
            for text in ['陈晓','陈晓雨的电话138123','陈晓雨的电话13812345678。']:
                kwargs['on_delta'](text);observed.append(self.s.get_task(t['id'])['partial_text']);time.sleep(.21)
            return '陈晓雨的电话13812345678。'
        with patch('app.worker.api_complete',side_effect=fake):CodexWorker(self.s,'.').run_one()
        self.assertNotIn('陈晓',str(observed));self.assertNotIn('138123',str(observed))

    def test_data_export_omits_api_key_and_includes_saved_versions(self):
        self.c.save_settings({'api_key':'synthetic-secret'})
        self.done(self.task('tailor_resume'))
        result=json.loads(self.j.export_data())
        self.assertEqual(len(result['resume_versions']),1);self.assertNotIn('synthetic-secret',json.dumps(result))

    def test_stream_midway_progress_and_first_response_time(self):
        events=[]
        self.c.save_settings({'provider':'api','base_url':'http://127.0.0.1:1/v1','api_model':'fake','stream':True})
        t=self.task()
        def fake(settings,prompt,**kwargs):
            kwargs['on_delta']('先核对工作重心。');events.append(self.s.get_task(t['id'])['partial_text'])
            time.sleep(.21);kwargs['on_delta']('先核对工作重心。再准备一段真实经历。')
            return '先核对工作重心。再准备一段真实经历。'
        with patch('app.worker.api_complete',side_effect=fake):CodexWorker(self.s,'.').run_one()
        done=self.s.get_task(t['id']);self.assertEqual(done['status'],'done');self.assertIn('先核对',events[0]);self.assertIn('first_response_seconds',done['metrics'])

    def test_real_http_sse_protocol_and_truncated_stream(self):
        received=[]
        class Fake(BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def do_POST(self):
                value=json.loads(self.rfile.read(int(self.headers['Content-Length'])));received.append(value)
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                for delta in ['你好。','这是逐段回复。']:
                    self.wfile.write(('data: '+json.dumps({'choices':[{'delta':{'content':delta},'finish_reason':None}]},ensure_ascii=False)+'\n\n').encode());self.wfile.flush()
                if value['model']!='broken':self.wfile.write(b'data: [DONE]\n\n')
        server=ThreadingHTTPServer(('127.0.0.1',0),Fake);threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        cfg={'base_url':f'http://127.0.0.1:{server.server_port}/v1','api_model':'test'};parts=[]
        result=complete(cfg,'test',on_delta=parts.append)
        self.assertEqual(result,'你好。这是逐段回复。');self.assertEqual(len(parts),2);self.assertTrue(received[0]['stream'])
        with self.assertRaises(Problem):complete({**cfg,'api_model':'broken'},'test',on_delta=parts.append)

    def test_resume_compare_and_word_pdf_exports(self):
        t=self.task('tailor_resume');a=self.done(t);b=self.c.accept_resume({'task_id':t['id'],'content':'教育经历\n本科毕业\n工作经历\n负责客户访谈与复盘，整理反馈。'})['id']
        self.assertIn('客户访谈',self.j.compare({'a':a,'b':b})['diff'])
        data,_=export_resume(self.s,b,'docx')
        with zipfile.ZipFile(io.BytesIO(data)) as z:self.assertIn('客户访谈',z.read('word/document.xml').decode())
        pdf,_=export_resume(self.s,b,'pdf');self.assertTrue(pdf.startswith(b'%PDF'))
        from pypdf import PdfReader
        self.assertIn('客户访谈',PdfReader(io.BytesIO(pdf)).pages[0].extract_text())

    def test_erase_includes_backups_and_rejects_active_or_unconfirmed(self):
        t=self.task()
        with self.assertRaises(Problem):self.j.erase({'confirmation':'删除本机全部求职资料'})
        self.s.cancel(t['id'])
        with self.assertRaises(Problem):self.j.erase({'confirmation':'yes'})
        for folder,name in [('uploads','abc.docx'),('backups','before.sqlite3')]:
            p=Path(self.tmp.name)/folder;p.mkdir();(p/name).write_bytes(b'private')
        with runtime.lock:runtime.active.add((str(self.s.db),'pending'))
        try:
            with self.assertRaises(Problem):self.j.erase({'confirmation':'删除本机全部求职资料'})
        finally:runtime.active.discard((str(self.s.db),'pending'))
        result=self.j.erase({'confirmation':'删除本机全部求职资料'})
        self.assertTrue(result['deleted']);self.assertEqual(result['files_removed'],2);self.assertFalse(self.s.state()['tasks']);self.assertFalse(self.s.state()['profile']['facts'])

if __name__=='__main__':unittest.main()
