"""Small local workflow: verified facts, user-confirmed events, text diffs."""
import difflib
import json
import time
import uuid
from . import runtime
from .store import Problem, text_field

KINDS={'applied':'已投递','greeting_sent':'已发招呼','interview':'收到面试邀请','interview_done':'面试完成','offer':'收到offer','joined':'已入职'}
CATEGORIES=('教育','工作','实习','项目','校园','技能','补充')


class Journey:
    def __init__(self, store):self.store=store

    def state(self):
        with self.store.connect() as db:
            rows=[dict(r) for r in db.execute('SELECT e.*,j.title,j.company FROM career_events e LEFT JOIN jobs j ON e.job_id=j.id ORDER BY at DESC')]
            facts=[dict(r) for r in db.execute('SELECT * FROM profile_facts ORDER BY created')]
            version_times=[r[0] for r in db.execute('SELECT created FROM resume_versions')]
            versions=len(version_times)
            apps=[r for r in rows if r['kind']=='applied']
            # Canonical company identity when known; otherwise display-name
            # dedup only, explicitly labelled as records, never inferred sends.
            companies=set()
            for r in apps:
                ref=db.execute('SELECT company_key FROM job_companies WHERE job_id=?',(r['job_id'],)).fetchone()
                companies.add('id:'+ref[0] if ref else 'name:'+(r['company'] or r['job_id']).strip())
        times=[r['at'] for r in rows]+version_times
        span=round((max(times)-min(times))/86400,1) if times else 0
        return {'events':rows,'facts':facts,'labels':KINDS,'categories':CATEGORIES,'summary':{'applications':len(apps),'companies':len(companies),'greetings':sum(r['kind']=='greeting_sent' for r in rows),'resume_versions':versions,'span_days':span},'note':'仅统计用户确认记录；生成/复制不等于发送或投递，跨度按首末进展或验收版本记录计算。'}

    def event(self,value):
        if value.get('confirmed') is not True:raise Problem('请确认这是实际发生的求职动作')
        kind=value.get('kind');job=text_field(value.get('job_id',''),'岗位',100,True)
        if kind not in KINDS:raise Problem('进展类型无效')
        eid=text_field(value.get('request_id',''),'请求标识',100,True)
        note=text_field(value.get('note',''),'备注',1000)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM jobs WHERE id=?',(job,)).fetchone():raise Problem('先选择一个岗位')
            old=db.execute('SELECT * FROM career_events WHERE id=?',(eid,)).fetchone()
            if old and (old['job_id']!=job or old['kind']!=kind or old['note']!=note):raise Problem('请求标识冲突',409)
            if not old:db.execute('INSERT INTO career_events VALUES(?,?,?,?,?)',(eid,job,kind,note,time.time()))
        return self.state()

    def remove_event(self,value):
        with self.store.connect() as db:db.execute('DELETE FROM career_events WHERE id=?',(text_field(value.get('id',''),'记录',100,True),))
        return self.state()

    def chat_fact_draft(self, value):
        task_id = text_field(value.get('task_id', ''), '对话任务', 100, True)
        with self.store.connect() as db:
            row = db.execute('SELECT kind,status,context_json,job_id FROM tasks WHERE id=?', (task_id,)).fetchone()
            if not row or row['kind'] != 'companion_chat' or row['status'] not in ('done','failed','cancelled'):
                raise Problem('只能从已结束的本人对话核对经历', 409)
            context = json.loads(row['context_json'])
            if context.get('companion') is not True or not context.get('instruction', '').strip():
                raise Problem('这条对话没有可核对的用户原话', 409)
            existing = db.execute('SELECT content FROM profile_facts WHERE id=?', ('chat-' + task_id,)).fetchone()
        return {'task_id': task_id, 'job_id': row['job_id'], 'content': context['instruction'],
                'source': '用户聊天核对 · ' + task_id[:8], 'saved': bool(existing)}

    def fact(self,value):
        if value.get('confirmed') is not True:raise Problem('请先核对事实')
        category=value.get('category','补充')
        if category not in CATEGORIES:raise Problem('事实类型无效')
        content=text_field(value.get('content',''),'事实',4000,True)
        source=text_field(value.get('source','用户确认'),'来源',200)
        fid=text_field(value.get('id',''),'事实编号',100) or uuid.uuid4().hex
        chat_task_id=text_field(value.get('chat_task_id',''),'对话任务',100)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if chat_task_id:
                row=db.execute('SELECT kind,status,context_json FROM tasks WHERE id=?',(chat_task_id,)).fetchone()
                if not row or row['kind']!='companion_chat' or row['status'] not in ('done','failed','cancelled') or json.loads(row['context_json']).get('companion') is not True:
                    raise Problem('只能记录已结束的本人对话原话',409)
                fid='chat-'+chat_task_id
                source='用户聊天核对 · '+chat_task_id[:8]
            previous=db.execute('SELECT category,content,source FROM profile_facts WHERE id=?',(fid,)).fetchone()
            if not previous or (previous['category'],previous['content'],previous['source'])!=(category,content,source):
                # Keep confirmed corrections as explicit facts; reapprove privacy
                # after every change before any new task can leave the machine.
                db.execute('INSERT OR REPLACE INTO profile_facts VALUES(?,?,?,?,?)',(fid,category,content,source,time.time()))
                db.execute('UPDATE profile SET revision=revision+1 WHERE id=1')
        return self.state()

    def remove_fact(self,value):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            count=db.execute('DELETE FROM profile_facts WHERE id=?',(text_field(value.get('id',''),'事实',100,True),)).rowcount
            if count:db.execute('UPDATE profile SET revision=revision+1 WHERE id=1')
        return self.state()

    def compare(self,value):
        with self.store.connect() as db:
            a=db.execute('SELECT * FROM resume_versions WHERE id=?',(text_field(value.get('a',''),'旧版',100,True),)).fetchone()
            b=db.execute('SELECT * FROM resume_versions WHERE id=?',(text_field(value.get('b',''),'新版',100,True),)).fetchone()
        if not a or not b or a['job_id']!=b['job_id']:raise Problem('请选择同一岗位的两个验收版本')
        return {'diff':''.join(difflib.unified_diff(a['content'].splitlines(True),b['content'].splitlines(True),fromfile='旧版',tofile='新版')) or '两个版本内容相同'}

    def export_data(self):
        # Intentionally omit API key and transient bridge credentials.
        data=self.store.state();data['journey']=self.state()
        with self.store.connect() as db:
            originals=[]
            for row in db.execute('SELECT id,kind,job_id,context_json,created FROM tasks ORDER BY created'):
                context=json.loads(row['context_json'])
                original=context.get('instruction')
                if isinstance(original,str) and original.strip():
                    originals.append({'task_id':row['id'],'kind':row['kind'],'job_id':row['job_id'],
                                      'created':row['created'],'text':original})
            data['user_originals']=originals
            data['resume_versions']=[dict(r) for r in db.execute('SELECT * FROM resume_versions ORDER BY created')]
            data['mock_interview_packages']=[dict(r) for r in db.execute('SELECT * FROM mock_interview_packages ORDER BY created')]
            data['mock_interview_results']=[dict(r) for r in db.execute('SELECT * FROM mock_interview_results ORDER BY created')]
            data['profile_import_drafts']=[dict(r) for r in db.execute('SELECT * FROM profile_import_drafts ORDER BY created')]
            data['job_links']=[dict(r) for r in db.execute('SELECT * FROM job_links ORDER BY updated')]
            data['job_recruiters']=[dict(r) for r in db.execute('SELECT * FROM job_recruiters ORDER BY observed')]
            data['hr_chat_bindings']=[dict(r) for r in db.execute('SELECT * FROM hr_chat_bindings ORDER BY updated')]
            data['companies']=[dict(r) for r in db.execute('SELECT * FROM companies ORDER BY company_key')]
            data['job_companies']=[dict(r) for r in db.execute('SELECT * FROM job_companies ORDER BY job_id')]
            data['company_evidence']=[dict(r) for r in db.execute('SELECT * FROM company_evidence ORDER BY observed')]
            data['job_company_research']=[dict(r) for r in db.execute('SELECT * FROM job_company_research ORDER BY observed')]
        return json.dumps(data,ensure_ascii=False,indent=2).encode()

    def erase(self,value):
        with runtime.lock:
            if any(path==str(self.store.db) for path,_ in runtime.active):raise Problem('后台连接尚未退出，请稍候再删除',409)
            return self._erase(value)

    def _erase(self,value):
        if value.get('confirmation')!='删除本机全部求职资料':raise Problem('请输入“删除本机全部求职资料”确认')
        # Require quiescence so another worker cannot recreate deleted state.
        with self.store.connect() as db:
            db.execute('PRAGMA secure_delete=ON')
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM tasks WHERE status IN ('running','queued')").fetchone():raise Problem('先等待或取消所有任务，再删除资料',409)
            for table in ('profile_import_drafts','mock_interview_results','mock_interview_packages','result_views','messages','resume_versions','career_events','profile_facts','tasks','documents','events','job_company_research','job_companies','company_evidence','companies','saved_targets','hr_chat_bindings','job_recruiters','job_links','jobs'):
                db.execute('DELETE FROM '+table)
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='browser_captures'").fetchone():db.execute('DELETE FROM browser_captures')
            db.execute("UPDATE profile SET name='',preferences='',facts='',revision=revision+1 WHERE id=1")
            db.execute('DELETE FROM companion_settings')
        # Only owned upload files and DB backups in this selected data folder.
        # No recursion and no paths supplied by the browser.
        removed=0
        for folder,patterns in (('uploads',('*',)),('drafts',('*',)),('backups',('*.sqlite3','*.sqlite3-wal','*.sqlite3-shm'))):
            base=self.store.directory/folder
            if base.is_dir() and not base.is_symlink():
                for pattern in patterns:
                    for file in base.glob(pattern):
                        if file.is_file() and not file.is_symlink():file.unlink();removed+=1
        with self.store.connect() as db:
            db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            db.execute('VACUUM')
        return {'deleted':True,'files_removed':removed,'note':'已删除当前数据目录内资料、上传原件及应用备份；应用之外手动导出的文件不受影响。文件系统或系统备份不提供安全擦除保证。'}
