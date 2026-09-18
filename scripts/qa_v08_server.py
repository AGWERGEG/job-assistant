"""Isolated UI fixture server. Fictitious data + local SSE, never real AI."""
import json
import tempfile
import threading
import time
import sys
import argparse
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.store import Store
from app.companion import Companion
from app.server import make_server

parser=argparse.ArgumentParser()
parser.add_argument('--port',type=int,default=8424)
parser.add_argument('--delay',type=float,default=0)
args=parser.parse_args()

class Mock(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if not data.get('stream'):time.sleep(args.delay)
        if data.get('stream'):
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            prompt=data['messages'][-1]['content']
            pieces=['【本地模拟回复，非真实模型】先看看岗位的主要职责。','你有校园活动协调经历，可以作为相邻证据。','下一步建议确认日常工作中活动执行的比例。']
            if '用户选择休息/结束本轮求职' in prompt:pieces=['【本地模拟寄语】今天先休息，','想回来时再继续。']
            if '用户刚在聊天中明确表示本人已经入职' in prompt:pieces=['【本地模拟结语】恭喜迈入新阶段，','愿你工作踏实，也照顾好自己的生活。']
            for t in pieces:
                try:self.wfile.write(('data: '+json.dumps({'choices':[{'delta':{'content':t},'finish_reason':None}]},ensure_ascii=False)+'\n\n').encode());self.wfile.flush();time.sleep(1.4)
                except (BrokenPipeError,ConnectionResetError):return
            self.wfile.write(b'data: [DONE]\n\n');return
        result={'mode':'agent','producer':'fixture','summary':'本地模拟专业结果','decision':'测试：突出活动协调','strategy':'基于虚构档案','primary_output':'【虚构测试稿】\n个人简介\n具备活动协调和客户沟通经历。\n校园经历\n- 协调5名同学完成活动，整理报名和反馈。','questions':[],'markdown':'【仅验证工程流程】材料取舍：前置活动经历，不新增数字。'}
        prompt=data['messages'][-1]['content']
        if '完成“岗位面试逻辑卡”' in prompt:
            result.update(decision='【模拟】讲清协调与反馈',primary_output='【本地模拟面试卡】\n这场面试要证明什么\n能清楚沟通并跟进任务。\n60秒介绍\n我有校园活动协调经历。\n可能追问\n如何处理临时变更？\n真实经历\n协调5名同学，结果只说已知事实。\n反问\n日常主要服务哪些用户？\n面试前检查\n确认时间与形式。')
        if '完成“面试后复盘”' in prompt:
            result.update(decision='【模拟】把个人行动说具体',primary_output='【本地模拟复盘】\n已知与未知\n用户描述答得简短，无法推断面试结果。\n保留的做法\n不编造经验。\n改进回答\n按情境、行动、结果讲述。\n下一步\n练习一遍一分钟回答。')
        raw=json.dumps({'choices':[{'message':{'content':json.dumps(result,ensure_ascii=False)},'finish_reason':'stop'}]},ensure_ascii=False).encode()
        self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(raw)

mock=ThreadingHTTPServer(('127.0.0.1',0),Mock);threading.Thread(target=mock.serve_forever,daemon=True).start()
folder=tempfile.mkdtemp(prefix='job-v08-ui-');s=Store(folder)
s.save_profile({'name':'虚构同学','facts':'手机号：13800138000\n邮箱：demo@example.com\n负责校园活动协调、报名信息与复盘，协调5名同学推进执行。','preferences':'杭州运营助理'})
c=Companion(s);c.save_settings({'provider':'api','base_url':f'http://127.0.0.1:{mock.server_port}/v1','api_model':'local-ui-fixture','buddy_name':'小树'})
c.approve({'token':c.preview_profile()['token'],'confirmed':True})
j=s.save_job({'title':'虚构运营助理','company':'演示公司','jd':'负责活动执行、客户沟通和运营复盘。'*4,'conversation':'首次联系'})
print('QA http://127.0.0.1:'+str(args.port)+'/#job='+j['id'],flush=True)
make_server(folder,args.port,True,2).serve_forever()
