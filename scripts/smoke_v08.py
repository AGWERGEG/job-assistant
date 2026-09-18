"""Three bounded real calls using existing provider config, fictitious facts only.

Run explicitly: python scripts/smoke_v08.py --config-data /existing/data --out /scratch/report.json
Credentials are read in memory, never copied into the report or printed.
"""
import argparse,json,sqlite3,tempfile,time,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.store import Store
from app.companion import Companion
from app.worker import CodexWorker

def main():
 p=argparse.ArgumentParser();p.add_argument('--config-data',required=True);p.add_argument('--out',required=True);p.add_argument('--interview',action='store_true',help='仅测试v0.9面试准备和复盘两次调用');a=p.parse_args()
 db=sqlite3.connect('file:'+str(Path(a.config_data).resolve()/'assistant.sqlite3')+'?mode=ro',uri=True)
 row=db.execute('SELECT value FROM companion_settings WHERE id=1').fetchone();db.close()
 settings=json.loads(row[0]);report=[]
 with tempfile.TemporaryDirectory(prefix='job-real-v08-') as tmp:
  s=Store(tmp);s.save_profile({'name':'虚构测试者','facts':'本科应届生，协调5名同学完成校园活动，负责报名整理、活动通知和复盘。曾完成商家服务行业课程研究。','preferences':'杭州运营或客户成功实习'})
  c=Companion(s);c.approve({'token':c.preview_profile()['token'],'confirmed':True})
  config=c.settings();config.update({k:settings[k] for k in ('provider','base_url','api_model','api_key','json_mode') if k in settings});config['stream']=True
  j=s.save_job({'title':'客户成功实习生（虚构）','company':'虚构商家软件公司','jd':'协助商家使用门店软件、整理问题与反馈、配合培训及跟进使用情况。本科在校或应届，有沟通和表格整理能力。','conversation':'请介绍与客户服务相关的经历。'})
  for index,kind in enumerate(('interview_prep','interview_review') if a.interview else ('quick_analysis','tailor_resume','suggest_reply')):
   t=c.send({'kind':kind,'job_id':j['id'],'text':('业务一面，线上形式，想讲清校园协调与商家服务的关联。' if kind=='interview_prep' else '实际被问：如何协调不同意见？我只答了沟通，没有讲清自己负责什么，想改进回答。' if kind=='interview_review' else '测试请精简，简历仅改摘要与3条经历；不要编造事实。'),'request_id':'smoke-'+str(index)})['task']
   original=Companion.settings
   def get_settings(self,public=False):
    if self.store.directory==s.directory and not public:return config
    return original(self,public)
   with patch.object(Companion,'settings',get_settings):CodexWorker(s,'.',timeout=120).run_one()
   r=s.get_task(t['id']);result=r.get('result') or {}
   report.append({'kind':kind,'status':r['status'],'metrics':r['metrics'],'error':r.get('error_text'),'output':result.get('primary_output',''),'strategy':result.get('strategy','')})
   print(json.dumps({k:v for k,v in report[-1].items() if k not in ('output','strategy')},ensure_ascii=False),flush=True)
   if r['status']!='done':break
 Path(a.out).parent.mkdir(parents=True,exist_ok=True);Path(a.out).write_text(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
