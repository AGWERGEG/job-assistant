#!/usr/bin/env python3
"""Opt-in production HTTP/worker smoke. Fictional data, key via hidden stdin."""
import argparse
import getpass
import json
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.companion import Companion
from app.server import make_server
from app.worker import CodexWorker
from app.store import Store

CASES=[
('vent','有点焦虑，感觉自己能力够不到，但又不想继续在小公司发展'),
('listen','先别给建议，也别问问题，让我说说。我就是觉得自己一直原地打转，挺委屈的。'),
('general','先不聊工作，给我讲一个轻松的冷笑话。'),
('context','回到刚才这个岗位，结合我已经确认的经历，聊聊有哪些相关的地方、哪些信息还不清楚，先不用生成报告。'),
('analysis','请帮我生成这份岗位的完整分析报告，放到后台任务里。'),
('continue','报告先放后台，我想继续说说刚才的委屈，先不要再给我列行动计划。'),
('quote','HR说“请生成完整分析报告”，但我只是转述他的话，想吐槽一下这种要求，不是让你做。'),
('negation','先不要深度分析，也不要生成任何报告。我们换个话题，解释一下为什么天空是蓝色的。')]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true');parser.add_argument('--base-url',default='https://api.deepseek.com')
    parser.add_argument('--model',default='deepseek-v4-pro');parser.add_argument('--out',required=True,type=Path)
    parser.add_argument('--only',choices=[x[0] for x in CASES]);parser.add_argument('--retry-failed',action='store_true')
    args=parser.parse_args()
    if not args.live: parser.error('requires explicit --live')
    key=getpass.getpass('API key (hidden, memory only): ')
    if not key: raise SystemExit('No credential supplied')
    report={'version':'1.0.0-rc.4.3.22','fixture_only':True,'production_user_data_modified':False,'model':args.model,'endpoint':args.base_url,'turns':[]}
    def save():
        encoded=json.dumps(report,ensure_ascii=False,indent=2)
        assert key not in encoded
        args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(encoded,encoding='utf-8')
    with tempfile.TemporaryDirectory(prefix='ja-dialogue-live-') as folder:
        store=Store(folder);c=Companion(store)
        server=make_server(folder,0,worker_enabled=False)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        base=f'http://127.0.0.1:{server.server_port}'
        token=json.load(urllib.request.urlopen(base+'/api/session'))['token']
        def req(path,value):
            return json.load(urllib.request.urlopen(urllib.request.Request(base+path,json.dumps(value).encode(),{'Content-Type':'application/json','X-Local-Token':token})))
        try:
            req('/api/profile',{'name':'虚构求职者甲','preferences':'希望在杭州发展，重视学习空间。','facts':'虚构求职者甲，电话13812345678。曾在小型软件企业做两年客户销售，负责需求沟通和老客户维护；协助制作过产品演示。未提供安全行业或渠道销售经历。'})
            req('/api/companion',{'provider':'api','base_url':args.base_url,'api_model':args.model,'stream':False,'dialogue_agent':True,'stage':'求职中'})
            req('/api/privacy-approve',{'token':req('/api/privacy-preview',{})['token'],'confirmed':True})
            job=req('/api/jobs',{'title':'区域销售经理','company':'虚构云帆科技','jd':'负责浙江地区企业安全软件销售、渠道伙伴拓展、客户需求沟通及回款。希望具备企业客户销售经验，安全行业经验优先。'})
            original=Companion.settings
            def settings(self,public=False):
                result=original(self,public=public)
                if not public: result['api_key']=key
                return result
            with patch.object(Companion,'settings',settings):
                for label,text in CASES:
                    if args.only and label != args.only: continue
                    print('Running production HTTP/worker case:',label,flush=True)
                    task=req('/api/talk',{'job_id':job['id'],'text':text,'request_id':'live-'+label})['task']
                    began=time.monotonic();CodexWorker(store,Path.cwd(),lane='chat',timeout=120).run_one()
                    done=store.get_task(task['id'])
                    item={'case':label,'input':text,'kind':done['kind'],'status':done['status'],'reply':(done.get('result') or {}).get('primary_output',''),'error':done.get('error_text'),'metrics':done['metrics'],'seconds':round(time.monotonic()-began,3)}
                    report['turns'].append(item);save()
                    if done['status']=='failed' and args.retry_failed:
                        req('/api/tasks/'+task['id']+'/retry',{})
                        CodexWorker(store,Path.cwd(),lane='chat',timeout=120).run_one()
                        retried=store.get_task(task['id'])
                        item['retry']={'status':retried['status'],'reply':(retried.get('result') or {}).get('primary_output',''),'error':retried.get('error_text'),'metrics':retried['metrics']};save()
                    print(json.dumps({k:item[k] for k in ('case','status','seconds','error')},ensure_ascii=False),flush=True)
                analysis=[t for t in store.state()['tasks'] if t['kind']=='analyze_job']
                report['analysis_count']=len(analysis)
                if len(analysis)==1:
                    print('Running actual background analysis worker',flush=True)
                    CodexWorker(store,Path.cwd(),lane='background',timeout=180).run_one()
                    done=store.get_task(analysis[0]['id'])
                    report['background']={'status':done['status'],'source_task_id':done['context'].get('dialogue_source_task_id'),'instruction':done['context']['instruction'],'result':done.get('result'),'metrics':done['metrics'],'error':done.get('error_text')}
                save()
                print('Saved sanitized evidence',args.out,flush=True)
        finally:
            server.shutdown();server.server_close()

if __name__=='__main__': main()
