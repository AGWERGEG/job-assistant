"""Single-user SQLite store, shared by the HTTP server and the agent CLI."""
import json
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
            db.execute("UPDATE meta SET value='9' WHERE key='schema_version'")
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
            return dict(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def add_document(self, doc_id, name, storage, extracted, status):
        with self.connect() as db:
            db.execute("INSERT INTO documents VALUES(?,?,?,?,?,?)", (doc_id, name, storage, extracted, status, time.time()))
            self.event(db, "document_uploaded", doc_id)

    def state(self):
        with self.connect() as db:
            tasks = [self.decode_task(row, private=False) for row in db.execute("SELECT * FROM tasks ORDER BY created DESC")]
            views = {r['task_id']: r['result_updated'] for r in db.execute('SELECT * FROM result_views')}
            for task in tasks:
                task['viewed'] = task['status'] == 'done' and views.get(task['id']) == task['updated']
            return {
                "profile": dict(db.execute("SELECT * FROM profile WHERE id=1").fetchone()),
                "jobs": [dict(r) for r in db.execute("SELECT * FROM jobs ORDER BY created DESC")],
                "documents": [dict(r) for r in db.execute("SELECT id,name,extracted,extraction_status,created FROM documents ORDER BY created DESC")],
                "tasks": tasks,
            }

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

    def create_task(self, value, bridge=None, conversation_override=None):
        require_object(value)
        kind, job_id = value.get("kind"), value.get("job_id")
        if kind not in TASK_KINDS or not isinstance(job_id, str):
            raise Problem("需要有效的任务类型和岗位 ID")
        if kind == 'closing_message':
            from .closing import declares_joined
            if value.get('companion') is not True or not declares_joined(value.get('instruction', '')):
                raise Problem('结语仅由聊天中明确的本人已入职陈述触发')
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            companion = value.get("companion") is True
            if companion:
                request_id = text_field(value.get("request_id", ""), "请求标识", 100, True)
                old = db.execute("SELECT t.* FROM messages m JOIN tasks t ON t.id=m.task_id WHERE m.request_id=?", (request_id,)).fetchone()
                if old:
                    if old["job_id"] != job_id or old['kind'] != kind or json.loads(old['context_json']).get('instruction') != value.get('instruction'):
                        raise Problem("请求标识与岗位不一致", 409)
                    return self.decode_task(old, private=False)
                pending = db.execute("SELECT t.kind FROM messages m JOIN tasks t ON t.id=m.task_id WHERE m.job_id=? AND t.status IN ('queued','running')", (job_id,)).fetchall()
                if any(task_lane(r['kind']) == task_lane(kind) for r in pending):
                    raise Problem("同一通道还有任务处理中；后台改简历不影响聊天，同类任务请完成或取消后继续", 409)
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
                raise Problem("先保存并确认个人经历；上传文件后需将文本核对到画像中")
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
                if previous['kind'] in ('rest_message', 'closing_message'):
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
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT t.job_id,t.kind FROM messages m JOIN tasks t ON t.id=m.task_id WHERE t.id=?', (task_id,)).fetchone()
            pending = db.execute("SELECT t.kind FROM messages m JOIN tasks t ON m.task_id=t.id WHERE m.job_id=? AND t.status IN ('queued','running') AND t.id!=?", (row['job_id'], task_id)).fetchall() if row else []
            if row and any(task_lane(r['kind']) == task_lane(row['kind']) for r in pending):
                raise Problem('同一通道还有任务处理中，请完成后再重试', 409)
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
