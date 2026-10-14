"""Single-user SQLite store, shared by the HTTP server and the agent CLI."""
import json
import hashlib
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

TASK_KINDS = {"analyze_job", "tailor_resume", "suggest_reply", "companion_chat", "quick_analysis", "interview_prep", "interview_review", "rest_message", "closing_message"}


def task_lane(kind):
    return 'background' if kind in ('analyze_job', 'tailor_resume', 'interview_prep', 'interview_review') else 'chat'


class Problem(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def text_field(value, name, limit=80000, required=False):
    if not isinstance(value, str) or len(value) > limit:
        raise Problem(f"{name} 必须为不超过 {limit} 字的文本")
    value = value.strip()
    if required and not value:
        raise Problem(f"请填写 {name}")
    return value


def require_object(value):
    if not isinstance(value, dict):
        raise Problem("请求必须是 JSON 对象")
    return value


class Store:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != 'nt':
            self.directory.chmod(0o700)
        self.db = self.directory / "assistant.sqlite3"
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT OR IGNORE INTO meta VALUES ('schema_version', '1');
                CREATE TABLE IF NOT EXISTS profile (
                    id INTEGER PRIMARY KEY CHECK (id=1), name TEXT NOT NULL,
                    preferences TEXT NOT NULL, facts TEXT NOT NULL, revision INTEGER NOT NULL);
                INSERT OR IGNORE INTO profile VALUES (1, '', '', '', 0);
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, company TEXT NOT NULL,
                    url TEXT NOT NULL, jd TEXT NOT NULL, conversation TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, storage_name TEXT NOT NULL,
                    extracted TEXT NOT NULL, extraction_status TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, job_id TEXT NOT NULL,
                    status TEXT NOT NULL, context_json TEXT NOT NULL, claim_token TEXT,
                    lease_until REAL, attempts INTEGER NOT NULL DEFAULT 0,
                    result_json TEXT, created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, at REAL NOT NULL, type TEXT NOT NULL, entity_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS companion_settings (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS messages (request_id TEXT PRIMARY KEY, task_id TEXT UNIQUE NOT NULL, job_id TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS resume_versions (id TEXT PRIMARY KEY, job_id TEXT NOT NULL, task_id TEXT NOT NULL, content TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS saved_targets (client TEXT PRIMARY KEY, job_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS job_links (
                    id TEXT PRIMARY KEY, job_id TEXT NOT NULL, kind TEXT NOT NULL,
                    url TEXT NOT NULL, title TEXT NOT NULL, company TEXT NOT NULL,
                    source_site TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                    UNIQUE(job_id, kind, url));
                CREATE TABLE IF NOT EXISTS job_recruiters (
                    job_id TEXT PRIMARY KEY, recruiter_name TEXT NOT NULL,
                    source_url TEXT NOT NULL, observed REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS hr_chat_bindings (
                    conversation_key TEXT PRIMARY KEY, job_id TEXT NOT NULL,
                    source_site TEXT NOT NULL, recruiter_name TEXT NOT NULL,
                    company TEXT NOT NULL, job_title TEXT NOT NULL,
                    url TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS career_events (id TEXT PRIMARY KEY,job_id TEXT NOT NULL,kind TEXT NOT NULL,note TEXT NOT NULL,at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS profile_facts (id TEXT PRIMARY KEY,category TEXT NOT NULL,content TEXT NOT NULL,source TEXT NOT NULL,created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS result_views (task_id TEXT PRIMARY KEY, result_updated REAL NOT NULL, viewed_at REAL NOT NULL);
            ''')
            columns = {r[1] for r in db.execute("PRAGMA table_info(tasks)")}
            if "error_text" not in columns:
                db.execute("ALTER TABLE tasks ADD COLUMN error_text TEXT")
            if "worker_id" not in columns:
                db.execute("ALTER TABLE tasks ADD COLUMN worker_id TEXT")
            if "metrics_json" not in columns:
                db.execute("ALTER TABLE tasks ADD COLUMN metrics_json TEXT")
            if 'partial_text' not in columns:
                db.execute("ALTER TABLE tasks ADD COLUMN partial_text TEXT NOT NULL DEFAULT ''")
            for name, definition in (("bridge_scope", "TEXT"), ("cache_key", "TEXT"), ("automatic", "INTEGER NOT NULL DEFAULT 0"), ("priority", "INTEGER NOT NULL DEFAULT 0")):
                if name not in columns:
                    db.execute(f"ALTER TABLE tasks ADD COLUMN {name} {definition}")
            db.execute("CREATE INDEX IF NOT EXISTS tasks_cache ON tasks(cache_key,status)")
            db.execute("UPDATE meta SET value='5' WHERE key='schema_version'")
            from .company import init_tables
            init_tables(db)
            from .mock_interview import init_tables as init_mock_interviews
            init_mock_interviews(db)
            from .profile_import import init_tables as init_profile_imports
            init_profile_imports(db)
            db.execute("UPDATE meta SET value='11' WHERE key='schema_version'")
            # Older databases already have jobs.url; expose it through the unified link history.
            rows = db.execute("SELECT id,title,company,url FROM jobs WHERE url!=''").fetchall()
            from .bridge import safe_recruitment_url
            for row in rows:
                try: clean_url,site = safe_recruitment_url(row['url'],'job_detail')
                except Problem: continue
                db.execute("INSERT OR IGNORE INTO job_links VALUES(?,?,?,?,?,?,?,?,?)",
                           (uuid.uuid4().hex,row['id'],'job_detail',clean_url,row['title'],row['company'],site,time.time(),time.time()))
        try:
            os.chmod(self.db, 0o600)
        except OSError:
            pass

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def event(self, db, kind, entity):
        db.execute("INSERT INTO events(at,type,entity_id) VALUES(?,?,?)", (time.time(), kind, entity))

    def save_profile(self, value):
        require_object(value)
        fields = [text_field(value.get(k, ""), k) for k in ("name", "preferences", "facts")]
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT name,preferences,facts FROM profile WHERE id=1').fetchone()
            if tuple(fields) == tuple(old):
                return dict(db.execute('SELECT * FROM profile WHERE id=1').fetchone())
            db.execute("UPDATE profile SET name=?, preferences=?, facts=?, revision=revision+1 WHERE id=1", fields)
            self.event(db, "profile_saved", "1")
        return self.state()["profile"]

    def save_job(self, value):
        require_object(value)
        fields = [text_field(value.get(k, ""), k, required=k in ("title", "jd"))
                  for k in ("title", "company", "url", "jd", "conversation")]
        if fields[2] and not fields[2].startswith(("https://", "http://")):
            raise Problem("来源链接仅支持 http 或 https")
        job_id = str(value.get("id") or uuid.uuid4().hex)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            exists = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if value.get("id") and not exists:
                raise Problem("岗位不存在", 404)
            if exists:
                if tuple(fields) == tuple(exists[k] for k in ("title", "company", "url", "jd", "conversation")):
                    return dict(exists)
                db.execute("UPDATE jobs SET title=?,company=?,url=?,jd=?,conversation=?,revision=revision+1 WHERE id=?", fields + [job_id])
            else:
                db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,1,?)", [job_id] + fields + [time.time()])
            self.event(db, "job_saved", job_id)
            if fields[2]:
                from .bridge import safe_recruitment_url
                try: clean_url,site = safe_recruitment_url(fields[2],'job_detail')
                except Problem: clean_url = ''
                if clean_url:
                    now = time.time()
                    existing_link = db.execute("SELECT id,created FROM job_links WHERE job_id=? AND kind='job_detail' AND url=?", (job_id, clean_url)).fetchone()
                    if existing_link:
                        db.execute("UPDATE job_links SET title=?,company=?,source_site=?,updated=? WHERE id=?", (fields[0],fields[1],site,now,existing_link['id']))
                    else:
                        db.execute("INSERT INTO job_links VALUES(?,?,?,?,?,?,?,?,?)", (uuid.uuid4().hex,job_id,'job_detail',clean_url,fields[0],fields[1],site,now,now))
            return dict(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def save_job_link(self, value):
        require_object(value)
        job_id = text_field(value.get('job_id',''),'岗位',100,True)
        kind = text_field(value.get('kind',''),'类型',30,True)
        if kind != 'job_detail': raise Problem('HR 会话必须经过招聘者、企业和岗位核验')
        from .bridge import safe_recruitment_url
        url,site = safe_recruitment_url(value.get('url',''),kind)
        with self.connect() as db:
            job = db.execute('SELECT title,company FROM jobs WHERE id=?',(job_id,)).fetchone()
            if not job: raise Problem('岗位不存在',404)
            now=time.time(); row=db.execute('SELECT id FROM job_links WHERE job_id=? AND kind=? AND url=?',(job_id,kind,url)).fetchone()
            lid=row['id'] if row else uuid.uuid4().hex
            db.execute('INSERT OR REPLACE INTO job_links VALUES(?,?,?,?,?,?,?,?,?)',(lid,job_id,kind,url,job['title'],job['company'],site,now if not row else db.execute('SELECT created FROM job_links WHERE id=?',(lid,)).fetchone()[0],now))
            return dict(db.execute('SELECT * FROM job_links WHERE id=?',(lid,)).fetchone())

    def list_job_links(self, job_id=''):
        with self.connect() as db:
            q='SELECT * FROM job_links'; args=[]
            if job_id: q+=' WHERE job_id=?'; args=[job_id]
            q+=' ORDER BY updated DESC'
            links=[dict(r) for r in db.execute(q,args)]
            for link in links:
                if link['kind']=='hr_chat': link['kind']='hr_chat_legacy'
            rows=db.execute('SELECT b.*,j.title,j.company AS job_company FROM hr_chat_bindings b '
                            'JOIN jobs j ON j.id=b.job_id'+(' WHERE b.job_id=?' if job_id else '')+
                            ' ORDER BY b.updated DESC',([job_id] if job_id else []))
            links.extend({'id':r['conversation_key'],'job_id':r['job_id'],'kind':'hr_chat',
                          'url':r['url'],'title':r['title'],'company':r['job_company'],
                          'source_site':r['source_site'],'created':r['created'],
                          'updated':r['updated'],'recruiter_name':r['recruiter_name']}
                         for r in rows)
            return sorted(links,key=lambda row:row['updated'],reverse=True)

    def save_job_recruiter(self, job_id, name, source_url):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO job_recruiters VALUES(?,?,?,?)',
                       (job_id,name,source_url,time.time()))

    def recruiter_for_job(self, job_id):
        with self.connect() as db:
            row=db.execute('SELECT r.recruiter_name FROM job_recruiters r JOIN jobs j ON j.id=r.job_id '
                           'WHERE r.job_id=? AND r.source_url=j.url',(job_id,)).fetchone()
            return row['recruiter_name'] if row else ''

    def chat_binding(self, key):
        with self.connect() as db:
            row=db.execute('SELECT b.*,j.title,j.company AS job_company FROM hr_chat_bindings b '
                           'JOIN jobs j ON j.id=b.job_id WHERE b.conversation_key=?',(key,)).fetchone()
            return dict(row) if row else None

    def bind_chat(self, chat, job_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            from .chat_links import match_job
            job=db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
            if not job: raise Problem('岗位不存在',404)
            recruiter=db.execute('SELECT recruiter_name FROM job_recruiters WHERE job_id=? AND source_url=?',
                                 (job_id,job['url'])).fetchone()
            reason=match_job(chat,job,recruiter['recruiter_name'] if recruiter else '')
            if reason: raise Problem('关联核验失败：'+reason,409)
            old=db.execute('SELECT job_id FROM hr_chat_bindings WHERE conversation_key=?',
                           (chat['key'],)).fetchone()
            if old and old['job_id']!=job_id:
                raise Problem('此 HR 会话已绑定其他岗位，请先解绑再重新绑定',409)
            now=time.time()
            db.execute('INSERT OR REPLACE INTO hr_chat_bindings VALUES(?,?,?,?,?,?,?,?,?)',
                       (chat['key'],job_id,chat['site'],chat['recruiter_name'],chat['company'],
                        chat['job_title'],chat['url'],now if not old else
                        db.execute('SELECT created FROM hr_chat_bindings WHERE conversation_key=?',
                                   (chat['key'],)).fetchone()[0],now))
        return self.chat_binding(chat['key'])

    def unbind_chat(self, key, expected_job_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT job_id FROM hr_chat_bindings WHERE conversation_key=?',(key,)).fetchone()
            if not row or row['job_id']!=expected_job_id:
                raise Problem('绑定已变化，请刷新当前 HR 会话后再试',409)
            db.execute('DELETE FROM hr_chat_bindings WHERE conversation_key=?',(key,))
        return {'unbound':True}

    def add_document(self, doc_id, name, storage, extracted, status):
        with self.connect() as db:
            db.execute("INSERT INTO documents VALUES(?,?,?,?,?,?)", (doc_id, name, storage, extracted, status, time.time()))
            self.event(db, "document_uploaded", doc_id)

    def state(self, summary=False):
        with self.connect() as db:
            if summary:
                tasks = [dict(row) for row in db.execute(
                    "SELECT id,kind,job_id,status,attempts,error_text,created,updated,metrics_json,partial_text "
                    "FROM tasks ORDER BY created DESC")]
                summaries = {row['id']: {'summary': (row['summary'] or '')[:1000],
                                         'decision': (row['decision'] or '')[:500]}
                             for row in db.execute(
                                 "SELECT id,json_extract(result_json,'$.summary') AS summary,"
                                 "json_extract(result_json,'$.decision') AS decision FROM tasks "
                                 "WHERE status='done' AND result_json IS NOT NULL")}
                for task in tasks:
                    task['metrics'] = json.loads(task.pop('metrics_json') or '{}')
                    task.pop('partial_text', None)
                    task['result'] = summaries.get(task['id'])
            else:
                tasks = [self.decode_task(row, private=False) for row in db.execute("SELECT * FROM tasks ORDER BY created DESC")]
            from .task_labels import display_name
            counters = {}
            for task in sorted(tasks, key=lambda item: (item.get('created', 0), item.get('id', ''))):
                if task.get('kind') not in ('tailor_resume', 'analyze_job', 'quick_analysis', 'interview_prep', 'interview_review', 'suggest_reply'):
                    continue
                key = (task.get('job_id', ''), task.get('kind', ''))
                counters[key] = counters.get(key, 0) + 1
                task['display_index'] = counters[key]
                task['display_name'] = display_name(task['kind'], counters[key])
            views = {r['task_id']: r['result_updated'] for r in db.execute('SELECT * FROM result_views')}
            for task in tasks:
                task['viewed'] = task['status'] == 'done' and views.get(task['id']) == task['updated']
            return {
                "profile": dict(db.execute("SELECT * FROM profile WHERE id=1").fetchone()),
                "jobs": [dict(r) for r in db.execute("SELECT * FROM jobs ORDER BY created DESC")],
                "documents": [dict(r) for r in db.execute("SELECT id,name,extracted,extraction_status,created FROM documents ORDER BY created DESC")],
                "tasks": tasks,
            }

    def state_tag(self):
        """Poll metadata without repeatedly loading every historical report."""
        with self.connect() as db:
            value = [tuple(db.execute('SELECT revision FROM profile WHERE id=1').fetchone()),
                     tuple(db.execute('SELECT COUNT(*),COALESCE(SUM(revision),0) FROM jobs').fetchone()),
                     tuple(db.execute('SELECT COUNT(*),COALESCE(MAX(id),0),COALESCE(MAX(at),0) FROM events').fetchone()),
                     tuple(db.execute('SELECT COUNT(*),COALESCE(MAX(viewed_at),0) FROM result_views').fetchone()),
                     [tuple(row) for row in db.execute('SELECT id,status,updated,metrics_json,partial_text FROM tasks ORDER BY id')]]
        return '"' + hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest() + '"'

    @staticmethod
    def decode_task(row, private=True):
        value = dict(row)
        value["context"] = json.loads(value.pop("context_json"))
        value["result"] = json.loads(value.pop("result_json")) if value.get("result_json") else None
        value.pop("result_json", None)
        value["metrics"] = json.loads(value.pop("metrics_json", None) or "{}")
        if not private:
            value.pop("claim_token", None)
            value.pop("context", None)
        return value

    def queued_tasks(self, lane=None):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM tasks WHERE status='queued' OR (status='running' AND lease_until<?) ORDER BY priority DESC, created ASC", (time.time(),))
            return [self.decode_task(r, private=False) for r in rows if lane is None or task_lane(r['kind']) == lane]

    def get_task(self, task_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise Problem("任务不存在", 404)
            return self.decode_task(row)

    def create_task(self, value, bridge=None, conversation_override=None, *, dialogue_parent=None, target_client=None,
                    intent_decision=None):
        require_object(value)
        kind, job_id = value.get("kind"), value.get("job_id")
        reference_task_id = value.get('reference_task_id', '') or ''
        if reference_task_id and (not isinstance(reference_task_id, str) or len(reference_task_id) > 100):
            raise Problem('引用任务无效')
        if not isinstance(kind, str) or kind not in TASK_KINDS or not isinstance(job_id, str):
            raise Problem("需要有效的任务类型和岗位 ID")
        if kind == 'closing_message':
            from .closing import declares_joined
            if value.get('companion') is not True or not declares_joined(value.get('instruction', '')):
                raise Problem('结语仅由聊天中明确的本人已入职陈述触发')
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if dialogue_parent is not None:
                parent_id, parent_token = dialogue_parent
                parent = db.execute("SELECT * FROM tasks WHERE id=?", (parent_id,)).fetchone()
                if not parent or parent['kind'] != 'companion_chat' or parent['status'] != 'running' or parent['claim_token'] != parent_token or parent['lease_until'] < time.time():
                    raise Problem('对话已取消或过期，没有创建任务', 409)
                origin = json.loads(parent['context_json'])
                if origin.get('reference_task_id'):
                    raise Problem('本轮已选定专项成果用于讨论；如需新报告，请先取消引用，再点击对应专项按钮', 409)
                from .dialogue import analysis_authorized
                from .dialogue_intent import authorizes, rule_fallback_kind
                model_authorized = authorizes(intent_decision, origin['instruction'], kind)
                legacy_authorized = ((intent_decision is None and kind == 'analyze_job'
                                      and analysis_authorized(origin['instruction']))
                                     or (isinstance(intent_decision, dict)
                                         and intent_decision.get('source') == 'rule'
                                         and intent_decision.get('kind') == kind
                                         and rule_fallback_kind(origin['instruction']) == kind))
                if job_id != parent['job_id'] or not (model_authorized or legacy_authorized):
                    raise Problem('这条消息没有明确要求创建该任务，请使用对应快捷按钮', 409)
                from .companion import DEFAULTS
                from .privacy import fingerprint
                row = db.execute('SELECT value FROM companion_settings WHERE id=1').fetchone()
                settings = {**DEFAULTS, **(json.loads(row[0]) if row else {})}
                profile_now = dict(db.execute('SELECT * FROM profile WHERE id=1').fetchone())
                job_now = db.execute('SELECT revision FROM jobs WHERE id=?', (job_id,)).fetchone()
                if not settings['onboarded'] or settings['privacy_approved'] != fingerprint(profile_now, settings) or fingerprint(origin['profile'], settings) != settings['privacy_approved']:
                    raise Problem('档案或隐私确认已变化，没有创建任务', 409)
                if not job_now or job_now[0] != origin['job']['revision']:
                    raise Problem('目标岗位已变化，没有创建任务', 409)
                existing_action = db.execute('SELECT t.* FROM messages m JOIN tasks t ON t.id=m.task_id WHERE m.request_id=?', ('dialogue-analysis-' + parent_id,)).fetchone()
                if existing_action:
                    if existing_action['kind'] != kind:
                        raise Problem('本轮对话已创建另一类任务，没有重复创建', 409)
                    return self.decode_task(existing_action, private=False)
                client = origin.get('_dialogue_target_client')
                if client:
                    selected = db.execute('SELECT job_id FROM saved_targets WHERE client=?', (client,)).fetchone()
                    if not selected or selected[0] != job_id:
                        raise Problem('已切换目标岗位，没有创建任务', 409)
                # Reuse the original turn, not model-authored instruction text.
                value = {**value, 'instruction': origin['instruction'], 'companion': True,
                         'request_id': 'dialogue-analysis-' + parent_id}
            companion = value.get("companion") is True
            if companion:
                request_id = text_field(value.get("request_id", ""), "请求标识", 100, True)
                old = db.execute("SELECT t.* FROM messages m JOIN tasks t ON t.id=m.task_id WHERE m.request_id=?", (request_id,)).fetchone()
                if old:
                    if old["job_id"] != job_id or old['kind'] != kind or json.loads(old['context_json']).get('instruction') != value.get('instruction') or json.loads(old['context_json']).get('reference_task_id','') != reference_task_id:
                        raise Problem("请求标识与岗位不一致", 409)
                    return self.decode_task(old, private=False)
                pending = db.execute("SELECT t.kind FROM messages m JOIN tasks t ON t.id=m.task_id WHERE m.job_id=? AND t.status IN ('queued','running') AND t.id!=?", (job_id, dialogue_parent[0] if dialogue_parent else '')).fetchall()
                if any(task_lane(r['kind']) == task_lane(kind) for r in pending):
                    raise Problem("同类请求还在处理中；后台改简历时仍可聊天，请等待或取消后再提交同类请求", 409)
            reference = None
            if reference_task_id:
                reference = db.execute('SELECT * FROM tasks WHERE id=?', (reference_task_id,)).fetchone()
                if not reference or reference['job_id'] != job_id or reference['status'] != 'done' or reference['kind'] not in ('tailor_resume','analyze_job','interview_prep','interview_review','suggest_reply'):
                    raise Problem('引用任务必须是当前岗位已完成的专业成果', 409)
            job = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            profile = dict(db.execute("SELECT * FROM profile WHERE id=1").fetchone())
            if not job and kind in ("companion_chat", "rest_message", "closing_message") and not job_id:
                job = {"id": "", "title": "日常求职对话", "company": "", "jd": "", "conversation": "", "revision": 0}
            if not job:
                raise Problem("岗位不存在", 404)
            job = dict(job)
            if conversation_override is not None:
                job["conversation"] = text_field(conversation_override, "对话摘录", 12000)
            if not profile["facts"].strip():
                if kind not in ('quick_analysis','companion_chat','rest_message','closing_message'):
                    raise Problem("先补充真实经历后，才能生成简历、HR 招呼或个人匹配建议")
                from .companion import DEFAULTS
                from .privacy import fingerprint
                saved = db.execute('SELECT value FROM companion_settings WHERE id=1').fetchone()
                settings = {**DEFAULTS, **(json.loads(saved[0]) if saved else {})}
                if (not settings.get('guide_profile_skipped') or not settings.get('onboarded')
                        or settings.get('privacy_approved') != fingerprint(profile, settings)):
                    raise Problem('先在工作台启用空白档案并确认脱敏预览', 409)
            if kind == "suggest_reply" and companion and not job["conversation"].strip():
                job["conversation"] = "首次联系 HR 的招呼；如本轮消息提供了 HR 问题，优先回应问题。"
            if kind == "suggest_reply" and not job["conversation"].strip():
                raise Problem("先填写 HR 消息或开场沟通需求")
            prior = []
            seen_kinds = set()
            for previous in db.execute(
                "SELECT kind,result_json,updated FROM tasks WHERE job_id=? AND status='done' AND result_json IS NOT NULL ORDER BY updated DESC",
                (job_id,),
            ):
                # Chat replies may discuss experiences that the user has not
                # yet confirmed. They are never strategy evidence for a new
                # professional task; chat continuity has its own channel.
                if previous['kind'] in ('rest_message', 'closing_message', 'companion_chat'):
                    continue
                if previous["kind"] in seen_kinds:
                    continue
                result = json.loads(previous["result_json"])
                if result.get("mode") != "agent":
                    continue
                if not result.get("strategy") and not result.get("primary_output"):
                    continue
                if result.get("profile_revision") != profile["revision"] or result.get("job_revision") != job["revision"]:
                    continue
                seen_kinds.add(previous["kind"])
                prior.append({
                    "kind": previous["kind"],
                    # Keep follow-up prompts small. The full prior markdown is
                    # still stored in SQLite and shown to the user, but only
                    # the decision/strategy and a bounded draft are needed to
                    # preserve continuity for the next model call.
                    "summary": result.get("summary", "")[:1000],
                    "decision": result.get("decision", "")[:500],
                    "strategy": result.get("strategy", "")[:2000],
                    "primary_output": result.get("primary_output", "")[:6000],
                    "questions": result.get("questions", [])[:2],
                    "markdown": result.get("markdown", "")[:4000],
                })
                if len(prior) >= 3:
                    break
            context = {
                "profile": profile,
                "job": dict(job),
                "instruction": text_field(value.get("instruction", ""), "instruction", 5000),
                "prior_results": prior,
            }
            if reference:
                rr = json.loads(reference['result_json'] or '{}')
                context['reference_task_id'] = reference_task_id
                context['reference'] = {'task_id': reference['id'], 'kind': reference['kind'], 'source': rr.get('source',''), 'profile_revision': rr.get('profile_revision'), 'job_revision': rr.get('job_revision'), 'stale': rr.get('profile_revision') != profile['revision'] or rr.get('job_revision') != job['revision'], 'result': {'summary': rr.get('summary','')[:1000], 'decision': rr.get('decision','')[:500], 'strategy': rr.get('strategy','')[:2000], 'primary_output': rr.get('primary_output','')[:6000], 'markdown': rr.get('markdown','')[:12000]}}
            context['confirmed_facts']=[dict(r) for r in db.execute('SELECT id,category,content,source FROM profile_facts ORDER BY created DESC LIMIT 80')]
            if kind == 'closing_message':
                from .closing import closing_snapshot
                context['_closing_summary'] = closing_snapshot(db)
            from .company import dossier
            company_data=dossier(db,job_id)
            if company_data:
                # Keep the original evidence in SQLite; send a bounded selection
                # rather than every historical recruitment page in every chat.
                picked=[];remaining=18000
                for e in company_data['evidence']:
                    encoded=json.dumps(e,ensure_ascii=False)
                    if len(encoded)>remaining:continue
                    picked.append(e);remaining-=len(encoded)
                    if len(picked)>=10:break
                context['company_background']={**company_data,'evidence':picked,'context_coverage':f"本轮选取{len(picked)}条材料，档案现有{len(company_data['evidence'])}条；未使用部分可在工作台查看"}
                # Company evidence is versioned independently of the target JD.
                context['company_revision']=company_data['revision']
            if companion:
                history = []
                rows = db.execute("SELECT t.context_json,t.result_json FROM messages m JOIN tasks t ON t.id=m.task_id WHERE m.job_id=? AND t.status='done' ORDER BY m.created DESC LIMIT 8", (job_id,)).fetchall()
                for previous in reversed(rows):
                    c, r = json.loads(previous[0]), json.loads(previous[1])
                    if r.get("profile_revision") == profile["revision"] and r.get("job_revision") == job["revision"]:
                        reply = r.get('primary_output', '')
                        if '_closing_summary' in c:
                            reply = reply.split('\n\n这一程的本机记录', 1)[0]
                        history.append({"user": c.get("instruction", ""), "assistant": reply[:4000]})
                context["dialogue"] = history
                accepted_rows = db.execute("SELECT v.content,t.result_json FROM resume_versions v JOIN tasks t ON t.id=v.task_id WHERE v.job_id=? ORDER BY v.created DESC", (job_id,)).fetchall()
                for accepted in accepted_rows:
                    original = json.loads(accepted[1])
                    if original.get('profile_revision') == profile['revision'] and original.get('job_revision') == job['revision']:
                        context["accepted_resume"] = accepted[0][:12000]
                        break
                context["companion"] = True
            if dialogue_parent is not None:
                context['dialogue_source_task_id'] = dialogue_parent[0]
                if intent_decision is not None:
                    context['dialogue_intent'] = {key: intent_decision[key] for key in ('kind', 'source', 'evidence')
                                                  if key in intent_decision}
            if target_client:
                context['_dialogue_target_client'] = target_client
            if bridge:
                context["bridge"] = bridge
            # A click retry on unchanged input returns the same outstanding task.
            encoded = json.dumps(context, ensure_ascii=False, sort_keys=True)
            old = db.execute("SELECT * FROM tasks WHERE kind=? AND context_json=? AND status IN ('queued','running')", (kind, encoded)).fetchone()
            if old:
                return self.decode_task(old, private=False)
            task_id, now = uuid.uuid4().hex, time.time()
            db.execute("INSERT INTO tasks(id,kind,job_id,status,context_json,created,updated) VALUES(?,?,?,'queued',?,?,?)", (task_id, kind, job_id, encoded, now, now))
            if companion:
                db.execute("INSERT INTO messages VALUES(?,?,?,?)", (request_id, task_id, job_id, now))
                db.execute("UPDATE tasks SET priority=20 WHERE id=?", (task_id,))
            if bridge:
                db.execute("UPDATE tasks SET bridge_scope=?,cache_key=?,automatic=?,priority=? WHERE id=?", (bridge["scope"], bridge["cache_key"], int(bridge["automatic"]), 5 if bridge["automatic"] else 10, task_id))
            self.event(db, "task_created", task_id)
            return self.decode_task(db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone(), private=False)

    def claim(self, task_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise Problem("任务不存在", 404)
            now = time.time()
            if row["status"] not in ("queued", "running") or (row["status"] == "running" and row["lease_until"] > now):
                raise Problem("任务已完成或正在被其他执行者处理", 409)
            token = uuid.uuid4().hex
            db.execute("UPDATE tasks SET status='running',claim_token=?,lease_until=?,attempts=attempts+1,error_text=NULL,updated=? WHERE id=?", (token, now + 900, now, task_id))
            self.event(db, "task_claimed", task_id)
            return self.decode_task(db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())

    def finish(self, task_id, token, result):
        require_object(result)
        submitted = dict(result)
        text_field(result.get("summary"), "summary", 2000, True)
        text_field(result.get("markdown"), "markdown", 100000, True)
        text_field(result.get("producer"), "producer", 200, True)
        for key, limit in (("decision", 500), ("strategy", 4000), ("primary_output", 30000)):
            if key in result:
                text_field(result.get(key), key, limit)
        questions = result.get("questions", [])
        if not isinstance(questions, list) or len(questions) > 2 or any(not isinstance(q, str) or not q.strip() or len(q) > 500 for q in questions):
            raise Problem("result.questions 必须是不超过 2 项的非空文本列表")
        if result.get("mode") not in ("agent", "demo"):
            raise Problem("result.mode 必须是 agent 或 demo")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise Problem("任务不存在", 404)
            if row["status"] != "running" or row["claim_token"] != token or row["lease_until"] < time.time():
                raise Problem("任务凭据无效或租约过期；请重新领取", 409)
            context = json.loads(row["context_json"])
            profile_rev = db.execute("SELECT revision FROM profile WHERE id=1").fetchone()[0]
            job_row = db.execute("SELECT revision FROM jobs WHERE id=?", (row["job_id"],)).fetchone()
            job_rev = job_row[0] if job_row else 0
            result = {k: submitted[k] for k in ("summary", "markdown", "producer", "mode")}
            for key in ("decision", "strategy", "primary_output", "questions"):
                if key in submitted:
                    result[key] = submitted[key]
            if row['kind'] == 'companion_chat' and type(submitted.get('fact_candidate')) is bool:
                result['fact_candidate'] = submitted['fact_candidate']
            result["stale_at_completion"] = profile_rev != context["profile"]["revision"] or job_rev != context["job"]["revision"]
            result["profile_revision"] = context["profile"]["revision"]
            result["job_revision"] = context["job"]["revision"]
            if context.get('company_revision') is not None:
                result['company_revision']=context['company_revision']
            db.execute("UPDATE tasks SET status='done',result_json=?,error_text=NULL,claim_token=NULL,lease_until=NULL,updated=? WHERE id=?", (json.dumps(result, ensure_ascii=False), time.time(), task_id))
            self.event(db, "task_finished", task_id)
        return self.get_task(task_id)

    def fail(self, task_id, token, message, worker_id=""):
        message = text_field(message, "message", 5000, True)
        with self.connect() as db:
            cursor = db.execute("UPDATE tasks SET status='failed',error_text=?,worker_id=?,claim_token=NULL,lease_until=NULL,updated=? WHERE id=? AND status='running' AND claim_token=?", (message, worker_id, time.time(), task_id, token))
            if cursor.rowcount != 1:
                raise Problem("任务凭据无效或租约已失效", 409)
            self.event(db, "task_failed", task_id)
        return self.get_task(task_id)

    def retry(self, task_id):
        task_id = text_field(task_id, '任务编号', 100, True)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            original = db.execute('SELECT context_json,job_id FROM tasks WHERE id=?', (task_id,)).fetchone()
            if original:
                context = json.loads(original['context_json'])
                profile = db.execute('SELECT revision FROM profile WHERE id=1').fetchone()
                job = db.execute('SELECT revision FROM jobs WHERE id=?', (original['job_id'],)).fetchone()
                if (profile[0] != context.get('profile', {}).get('revision')
                        or (job and job[0] != context.get('job', {}).get('revision'))):
                    raise Problem('资料已更新；请核对脱敏后创建新任务，原任务已保留', 409)
            row = db.execute('SELECT t.job_id,t.kind FROM messages m JOIN tasks t ON t.id=m.task_id WHERE t.id=?', (task_id,)).fetchone()
            pending = db.execute("SELECT t.kind FROM messages m JOIN tasks t ON m.task_id=t.id WHERE m.job_id=? AND t.status IN ('queued','running') AND t.id!=?", (row['job_id'], task_id)).fetchall() if row else []
            if row and any(task_lane(r['kind']) == task_lane(row['kind']) for r in pending):
                raise Problem('同类请求还在处理中，请等待或取消后再重试', 409)
            cursor = db.execute("UPDATE tasks SET status='queued',error_text=NULL,partial_text='',metrics_json=NULL,claim_token=NULL,lease_until=NULL,updated=? WHERE id=? AND status='failed'", (time.time(), task_id))
            if cursor.rowcount != 1:
                raise Problem("只有失败任务可以重试", 409)
            self.event(db, "task_retried", task_id)
        return self.get_task(task_id)

    def cancel(self, task_id):
        with self.connect() as db:
            cursor = db.execute("UPDATE tasks SET status='cancelled',partial_text='',claim_token=NULL,lease_until=NULL,updated=? WHERE id=? AND status IN ('queued','running','failed')", (time.time(), task_id))
            if cursor.rowcount != 1:
                raise Problem("只有等待、运行或失败任务可以取消", 409)
            self.event(db, "task_cancelled", task_id)
        return self.get_task(task_id)

    def release(self, task_id, token):
        with self.connect() as db:
            cursor = db.execute("UPDATE tasks SET status='queued',claim_token=NULL,lease_until=NULL,updated=? WHERE id=? AND status='running' AND claim_token=?", (time.time(), task_id, token))
            if cursor.rowcount != 1:
                raise Problem("任务凭据无效", 409)
            self.event(db, "task_released", task_id)
        return {"released": task_id}

    def record_metrics(self, task_id, values):
        with self.connect() as db:
            db.execute("UPDATE tasks SET metrics_json=? WHERE id=?", (json.dumps(values), task_id))

    def still_running(self, task_id, token):
        with self.connect() as db:
            return bool(db.execute("SELECT 1 FROM tasks WHERE id=? AND status='running' AND claim_token=?", (task_id,token)).fetchone())

    def progress(self, task_id, token, text, metrics):
        with self.connect() as db:
            db.execute("UPDATE tasks SET partial_text=?,metrics_json=? WHERE id=? AND status='running' AND claim_token=?", (text,json.dumps(metrics),task_id,token))
