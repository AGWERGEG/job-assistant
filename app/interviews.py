"""Persisted, job-scoped mock interview state machine."""
import json
import time
import uuid

from .store import Problem, require_object, text_field


STAGES = ("introduction", "experience", "role", "pressure", "candidate_questions")
STAGE_LABELS = {"introduction": "60 秒自我介绍", "experience": "经历追问", "role": "岗位专项", "pressure": "压力与澄清", "candidate_questions": "用户反问"}
STAGE_QUOTAS = {"introduction": 1, "experience": 2, "role": 2, "pressure": 1, "candidate_questions": 1}


def init_tables(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS interview_sessions (
        id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, job_id TEXT NOT NULL,
        resume_version_id TEXT NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL,
        goal TEXT NOT NULL, context_json TEXT NOT NULL, pending_task_id TEXT,
        current_turn_id TEXT, paused_from TEXT, recap_json TEXT,
        created REAL NOT NULL, updated REAL NOT NULL, ended REAL);
      CREATE TABLE IF NOT EXISTS interview_turns (
        id TEXT PRIMARY KEY, session_id TEXT NOT NULL, turn_no INTEGER NOT NULL,
        stage TEXT NOT NULL, question TEXT NOT NULL, answer_status TEXT NOT NULL,
        answer_text TEXT NOT NULL, task_id TEXT NOT NULL, created REAL NOT NULL,
        answered REAL, UNIQUE(session_id,turn_no));
      CREATE INDEX IF NOT EXISTS interview_sessions_job ON interview_sessions(job_id,created DESC);
      CREATE INDEX IF NOT EXISTS interview_turns_session ON interview_turns(session_id,turn_no);
    ''')


class Interviews:
    def __init__(self, store, companion):
        self.store, self.companion = store, companion

    def _row(self, session_id):
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM interview_sessions WHERE id=?', (session_id,)).fetchone()
        if not row:
            raise Problem('模拟面试会话不存在', 404)
        return dict(row)

    def _public(self, row):
        with self.store.connect() as db:
            turns = [dict(r) for r in db.execute('SELECT * FROM interview_turns WHERE session_id=? ORDER BY turn_no', (row['id'],))]
        value = {k: row[k] for k in ('id','job_id','resume_version_id','status','stage','goal','current_turn_id','created','updated','ended')}
        value['stage_label'] = STAGE_LABELS.get(row['stage'], row['stage'])
        value['turns'] = turns
        value['recap'] = json.loads(row['recap_json']) if row.get('recap_json') else None
        value['progress'] = {'answered': sum(t['answer_status']=='confirmed' for t in turns), 'total': sum(STAGE_QUOTAS.values())}
        return value

    def sync(self, session_id):
        row = self._row(session_id)
        task_id = row.get('pending_task_id')
        if not task_id:
            return self._public(row)
        task = self.store.get_task(task_id)
        if task['status'] in ('queued','running'):
            return self._public(row)
        now = time.time()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT * FROM interview_sessions WHERE id=?', (session_id,)).fetchone()
            if not current or current['pending_task_id'] != task_id:
                return self._public(dict(current))
            if task['status'] == 'done' and task['kind'] == 'interview_question':
                question = text_field((task.get('result') or {}).get('primary_output',''), '面试问题', 3000, True)
                number = db.execute('SELECT count(*) FROM interview_turns WHERE session_id=?', (session_id,)).fetchone()[0] + 1
                turn_id = uuid.uuid4().hex
                db.execute('INSERT INTO interview_turns VALUES(?,?,?,?,?,?,?,?,?,NULL)',
                           (turn_id, session_id, number, current['stage'], question, 'pending', '', task_id, now))
                db.execute("UPDATE interview_sessions SET status='awaiting_answer',current_turn_id=?,pending_task_id=NULL,updated=? WHERE id=?",
                           (turn_id, now, session_id))
            elif task['status'] == 'done' and task['kind'] == 'interview_recap':
                recap = task.get('result') or {}
                db.execute("UPDATE interview_sessions SET status='completed',pending_task_id=NULL,recap_json=?,updated=?,ended=? WHERE id=?",
                           (json.dumps(recap, ensure_ascii=False), now, now, session_id))
            else:
                db.execute("UPDATE interview_sessions SET status='failed',pending_task_id=NULL,updated=? WHERE id=?", (now, session_id))
        return self._public(self._row(session_id))

    def list(self, job_id):
        job_id = text_field(job_id, '岗位', 100, True)
        with self.store.connect() as db:
            ids = [r[0] for r in db.execute('SELECT id FROM interview_sessions WHERE job_id=? ORDER BY created DESC LIMIT 30', (job_id,))]
        return {'sessions': [self.sync(i) for i in ids], 'stage_labels': STAGE_LABELS}

    def get(self, session_id):
        return self.sync(text_field(session_id, '会话', 100, True))

    def start(self, value):
        require_object(value)
        if not self.companion.ready():
            raise Problem('请先完成档案脱敏确认', 409)
        job_id = text_field(value.get('job_id',''), '岗位', 100, True)
        version_id = text_field(value.get('resume_version_id',''), '简历版本', 100, True)
        request_id = text_field(value.get('request_id',''), '请求标识', 100, True)
        goal = text_field(value.get('goal',''), '模拟目标', 1000) or '完成一轮岗位模拟面试，重点检验表达是否具体、真实并贴合岗位。'
        with self.store.connect() as db:
            old = db.execute('SELECT id,job_id,resume_version_id,goal FROM interview_sessions WHERE request_id=?', (request_id,)).fetchone()
            if old:
                if old['job_id'] != job_id or old['resume_version_id'] != version_id or old['goal'] != goal:
                    raise Problem('请求标识与模拟面试不一致', 409)
                return self.get(old['id'])
            job = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            version = db.execute('SELECT * FROM resume_versions WHERE id=? AND job_id=?', (version_id, job_id)).fetchone()
            if not job or not version:
                raise Problem('请选择当前岗位的一份已验收简历', 409)
            session_id, now = uuid.uuid4().hex, time.time()
            snapshot = {'job': dict(job), 'resume_version': {'id': version['id'], 'content': version['content']},
                        'profile_revision': self.companion.profile()['revision']}
            db.execute('INSERT INTO interview_sessions VALUES(?,?,?,?,?,?,?,?,NULL,NULL,NULL,NULL,?,?,NULL)',
                       (session_id, request_id, job_id, version_id, 'starting', STAGES[0], goal, json.dumps(snapshot, ensure_ascii=False), now, now))
        self._queue_question(session_id)
        return self.get(session_id)

    def _task_context(self, row):
        snapshot = json.loads(row['context_json'])
        with self.store.connect() as db:
            turns = [dict(r) for r in db.execute("SELECT stage,question,answer_status,answer_text FROM interview_turns WHERE session_id=? ORDER BY turn_no", (row['id'],))]
        # Only user-confirmed answer text is sent back to the model. Skipped turns
        # keep their question but never manufacture an answer.
        return {'interview_session': {'id': row['id'], 'goal': row['goal'], 'stage': row['stage'],
                                      'stage_label': STAGE_LABELS[row['stage']], 'selected_resume': snapshot['resume_version'],
                                      'turns': turns}}

    def _queue_question(self, session_id):
        row = self._row(session_id)
        task = self.store.create_task({'kind':'interview_question','job_id':row['job_id'],
            'instruction':f"生成模拟面试的下一个问题。当前阶段：{STAGE_LABELS[row['stage']]}。每轮只问一个问题。"},
            extra_context=self._task_context(row))
        with self.store.connect() as db:
            db.execute("UPDATE interview_sessions SET status='generating_question',pending_task_id=?,updated=? WHERE id=?", (task['id'],time.time(),session_id))

    def _queue_recap(self, session_id):
        row = self._row(session_id)
        with self.store.connect() as db:
            confirmed = db.execute("SELECT count(*) FROM interview_turns WHERE session_id=? AND answer_status='confirmed'", (session_id,)).fetchone()[0]
        if not confirmed:
            recap = {'summary':'本轮没有已确认回答','decision':'先完成至少一道回答再复盘','strategy':'不根据空白记录评价表现','primary_output':'本轮尚无你确认过的回答，因此没有生成表现评价。可以重新开始，先完成 60 秒自我介绍。','questions':[],'markdown':'没有已确认回答；未调用模型。','mode':'demo','producer':'本机规则'}
            now=time.time()
            with self.store.connect() as db:db.execute("UPDATE interview_sessions SET status='completed',pending_task_id=NULL,recap_json=?,updated=?,ended=? WHERE id=?",(json.dumps(recap,ensure_ascii=False),now,now,session_id))
            return
        task = self.store.create_task({'kind':'interview_recap','job_id':row['job_id'],
            'instruction':'根据本轮模拟面试中用户确认的回答生成结构化复盘。'}, extra_context=self._task_context(row))
        with self.store.connect() as db:db.execute("UPDATE interview_sessions SET status='generating_recap',pending_task_id=?,current_turn_id=NULL,updated=? WHERE id=?",(task['id'],time.time(),session_id))

    def _advance(self, session_id):
        row = self._row(session_id)
        with self.store.connect() as db:
            count = db.execute('SELECT count(*) FROM interview_turns WHERE session_id=? AND stage=?', (session_id,row['stage'])).fetchone()[0]
        if count < STAGE_QUOTAS[row['stage']]:
            self._queue_question(session_id); return
        index = STAGES.index(row['stage'])
        if index + 1 >= len(STAGES):
            self._queue_recap(session_id); return
        with self.store.connect() as db:db.execute('UPDATE interview_sessions SET stage=?,updated=? WHERE id=?',(STAGES[index+1],time.time(),session_id))
        self._queue_question(session_id)

    def answer(self, value):
        require_object(value)
        session_id = text_field(value.get('session_id',''), '会话', 100, True)
        if value.get('confirmed') is not True:
            raise Problem('请先核对并确认回答文字')
        answer = text_field(value.get('answer',''), '回答', 8000, True)
        self.sync(session_id); row = self._row(session_id)
        if row['status'] != 'awaiting_answer' or not row['current_turn_id']:
            raise Problem('当前没有等待确认的面试问题', 409)
        now=time.time()
        with self.store.connect() as db:
            changed=db.execute("UPDATE interview_turns SET answer_status='confirmed',answer_text=?,answered=? WHERE id=? AND session_id=? AND answer_status='pending'",(answer,now,row['current_turn_id'],session_id)).rowcount
            if not changed:raise Problem('这道题已经处理',409)
            db.execute("UPDATE interview_sessions SET status='advancing',current_turn_id=NULL,updated=? WHERE id=?",(now,session_id))
        self._advance(session_id)
        return self.get(session_id)

    def control(self, value):
        require_object(value)
        session_id=text_field(value.get('session_id',''),'会话',100,True);action=text_field(value.get('action',''),'动作',30,True)
        self.sync(session_id);row=self._row(session_id);now=time.time()
        if action == 'pause':
            if row['status'] not in ('generating_question','awaiting_answer'):raise Problem('当前状态不能暂停',409)
            if row.get('pending_task_id'):
                try:self.store.cancel(row['pending_task_id'])
                except Problem:pass
            with self.store.connect() as db:db.execute("UPDATE interview_sessions SET status='paused',paused_from=?,pending_task_id=NULL,updated=? WHERE id=?",(row['status'],now,session_id))
        elif action == 'resume':
            if row['status']!='paused':raise Problem('会话没有暂停',409)
            if row.get('current_turn_id'):
                with self.store.connect() as db:db.execute("UPDATE interview_sessions SET status='awaiting_answer',paused_from=NULL,updated=? WHERE id=?",(now,session_id))
            else:self._queue_question(session_id)
        elif action == 'skip':
            if row['status']!='awaiting_answer' or not row.get('current_turn_id'):raise Problem('当前没有可跳过的问题',409)
            with self.store.connect() as db:
                db.execute("UPDATE interview_turns SET answer_status='skipped',answered=? WHERE id=? AND answer_status='pending'",(now,row['current_turn_id']))
                db.execute("UPDATE interview_sessions SET status='advancing',current_turn_id=NULL,updated=? WHERE id=?",(now,session_id))
            self._advance(session_id)
        elif action == 'end':
            if row['status'] in ('completed','generating_recap'):return self.get(session_id)
            if row.get('pending_task_id'):
                try:self.store.cancel(row['pending_task_id'])
                except Problem:pass
            with self.store.connect() as db:db.execute("UPDATE interview_sessions SET status='ending',pending_task_id=NULL,current_turn_id=NULL,updated=? WHERE id=?",(now,session_id))
            self._queue_recap(session_id)
        elif action == 'retry':
            if row['status']!='failed':raise Problem('只有失败会话可以重试',409)
            self._queue_question(session_id)
        else:raise Problem('未知面试控制动作')
        return self.get(session_id)
