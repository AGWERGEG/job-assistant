"""Release smoke: real local HTTP, synthetic API, worker, export and restart."""
import io
import json
import tempfile
import threading
import time
import unittest
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from app.server import make_server


class ReleaseSmoke(unittest.TestCase):
    def test_onboard_worker_export_and_restart(self):
        requests=[]
        class Model(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_POST(self):
                value=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append(value)
                result={'mode':'agent','producer':'synthetic','summary':'虚构岗位判断','decision':'可以尝试','strategy':'突出真实沟通经历','primary_output':'个人简介\n负责校园活动协调，善于整理需求。','questions':[],'markdown':'测试说明'}
                text=json.dumps(result,ensure_ascii=False) if value.get('response_format') else '可以先了解岗位的客户沟通要求。'
                data=json.dumps({'choices':[{'message':{'content':text},'finish_reason':'stop'}]},ensure_ascii=False).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        model=ThreadingHTTPServer(('127.0.0.1',0),Model);threading.Thread(target=model.serve_forever,daemon=True).start()
        servers=[]
        def stop(server):
            server.worker_stop.set();server.shutdown()
            for thread in server.worker_threads: thread.join(timeout=3)
            server.server_close()
        with tempfile.TemporaryDirectory() as folder:
            try:
                def start():
                    server=make_server(folder,0,worker_enabled=True);servers.append(server)
                    threading.Thread(target=server.serve_forever,daemon=True).start()
                    return server
                server=start()
                origin='chrome-extension://'+'a'*32
                token='';bridge_token=''
                def req(path,value=None,extension=False):
                    headers={}
                    if value is not None:headers={'Content-Type':'application/json','X-Local-Token':token}
                    if extension:headers.update(Origin=origin,**{'X-Bridge-Token':bridge_token})
                    with urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{server.server_port}'+path,
                            data=json.dumps(value).encode() if value is not None else None,headers=headers)) as response:
                        data=response.read()
                        return json.loads(data) if 'application/json' in response.headers.get('Content-Type','') else data
                token=req('/api/session')['token']
                self.assertEqual(req('/api/companion')['guide']['step'],'pairing')
                code=req('/api/extension-code',{})['code']
                bridge_token=req('/bridge/pair',{'code':code},True)['token']
                req('/api/companion',{'provider':'api','base_url':f'http://127.0.0.1:{model.server_port}/v1','api_model':'synthetic','api_key':'synthetic-key','stream':False})
                self.assertTrue(req('/api/connection-test',{})['ok'])
                req('/api/onboarding',{'action':'connection'});req('/api/onboarding',{'action':'persona'})
                profile={'name':'虚构小林','facts':'姓名：虚构小林\n电话：13800000000\n邮箱：fixture@example.com\n负责校园活动协调。'}
                req('/api/profile',profile)
                preview=req('/api/privacy-preview',{})
                req('/api/privacy-approve',{'token':preview['token'],'confirmed':True})
                req('/api/onboarding',{'action':'back'});req('/api/onboarding',{'action':'back'})
                req('/api/profile',profile);self.assertEqual(req('/api/onboarding',{'action':'continue'})['guide']['step'],'browse')
                capture={'job_key':'release001','url':'https://www.zhipin.com/job_detail/release001.html','title':'虚构客户助理','company':'虚构公司','jd':'负责客户沟通与校园活动需求整理，跟进活动安排与复盘。'*3,'method':'dom'}
                job=req('/bridge/capture',{'scope':'release','seq':1,'capture':capture},True)['job']
                req('/bridge/confirm',{'scope':'release','seq':1},True)
                def run(kind):
                    task=req('/bridge/talk',{'scope':'release','seq':1,'kind':kind,'text':'','request_id':kind},True)['task']
                    end=time.monotonic()+8
                    while time.monotonic()<end:
                        saved=next(t for t in req('/api/state')['tasks'] if t['id']==task['id'])
                        if saved['status'] in ('done','failed'):break
                        time.sleep(.05)
                    self.assertEqual(saved['status'],'done',saved.get('error_text'))
                    return saved
                run('quick_analysis');req('/bridge/onboarding-complete',{},True)
                resume=run('tailor_resume')
                version=req('/api/resume-accept',{'task_id':resume['id'],'content':resume['result']['primary_output']})['id']
                restored=req('/api/resume-export-preview',{'version_id':version})['content']
                self.assertIn('13800000000',restored)
                for fmt in ('docx','pdf'):
                    data=req('/api/resume-download',{'version_id':version,'content':restored,'confirmed':True,'format':fmt})
                    if fmt=='pdf':self.assertTrue(data.startswith(b'%PDF'))
                    else:
                        with zipfile.ZipFile(io.BytesIO(data)) as archive:self.assertIn('虚构小林',archive.read('word/document.xml').decode())
                for value in requests:
                    prompt=value['messages'][0]['content']
                    self.assertNotIn('13800000000',prompt);self.assertNotIn('fixture@example.com',prompt);self.assertNotIn('虚构小林',prompt)
                original=next(j for j in req('/api/state')['jobs'] if j['id']==job['id'])
                req('/api/jobs',{**original,'jd':original['jd']+'用户核对补充。'})
                synced=req('/bridge/sync',{'scope':'release','seq':1},True)
                self.assertEqual(synced['job']['revision'],original['revision']+1)
                stop(server);servers.remove(server);server=start()
                token=req('/api/session')['token'];code=req('/api/extension-code',{})['code']
                bridge_token=req('/bridge/pair',{'code':code},True)['token']
                saved=req('/bridge/restore',{'scope':'restarted','seq':1},True)
                self.assertEqual(saved['job']['id'],job['id'])
                self.assertFalse(req('/api/companion')['guide']['active'])
                self.assertEqual(len(req('/api/resume-versions',{'job_id':job['id']})['versions']),1)
            finally:
                for server in servers:stop(server)
                model.shutdown();model.server_close()
