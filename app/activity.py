"""Local result acknowledgement and source-bound, explicitly confirmed events."""
import hashlib
import time
from .store import Problem, text_field, task_lane
from .journey import Journey


class Activity:
    def __init__(self, store):self.store=store

    def viewed(self, value):
        task_id=text_field(value.get('task_id',''),'任务',100,True)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            task=db.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()
            if not task:raise Problem('任务不存在',404)
            if task['status']!='done' or task_lane(task['kind'])!='background':raise Problem('只有完成的后台结果可标为已查看',409)
            if type(value.get('result_updated')) not in (int,float) or value['result_updated']!=task['updated']:
                raise Problem('结果状态已变化，请刷新后查看',409)
            if value.get('viewed') is False:
                db.execute('DELETE FROM result_views WHERE task_id=?',(task_id,))
            elif value.get('viewed') is True:
                db.execute('INSERT OR REPLACE INTO result_views VALUES(?,?,?)',(task_id,task['updated'],time.time()))
            else:raise Problem('请明确查看状态')
        return {'task_id':task_id,'viewed':value['viewed']}

    def record(self, value):
        source=text_field(value.get('source_type',''),'来源类型',30,True)
        source_id=text_field(value.get('source_id',''),'来源',100,True)
        kind=text_field(value.get('kind',''),'进展类型',30,True)
        job_id=text_field(value.get('job_id',''),'岗位',100,True)
        if value.get('confirmed') is not True:raise Problem('请确认这是已经发生的实际进展')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if source=='version':
                row=db.execute('SELECT job_id FROM resume_versions WHERE id=?',(source_id,)).fetchone()
                allowed=('applied',)
            elif source=='task':
                row=db.execute("SELECT job_id,kind FROM tasks WHERE id=? AND status='done'",(source_id,)).fetchone()
                allowed={'suggest_reply':('greeting_sent','interview'),'interview_prep':('interview','interview_done'),'interview_review':('interview_done',)}.get(row['kind'] if row else '',())
            elif source=='job':
                row=db.execute('SELECT id AS job_id FROM jobs WHERE id=?',(source_id,)).fetchone()
                allowed=('interview',)
            else:raise Problem('记录来源无效')
            if not row or row['job_id']!=job_id or kind not in allowed:raise Problem('记录来源与岗位或动作不匹配',409)
            # One quick acknowledgement per source/action, including retry and
            # reload. Repeated real actions can still be added in full records.
            eid='quick-'+hashlib.sha256(f'{source}:{source_id}:{kind}'.encode()).hexdigest()
            existing=db.execute('SELECT * FROM career_events WHERE id=?',(eid,)).fetchone()
            if existing and (existing['job_id']!=job_id or existing['kind']!=kind):raise Problem('记录标识冲突',409)
            if not existing:db.execute('INSERT INTO career_events VALUES(?,?,?,?,?)',(eid,job_id,kind,'快捷确认（'+source+' '+source_id[:8]+'）',time.time()))
        return {'event_id':eid,'already_recorded':bool(existing),'journey':Journey(self.store).state()}
