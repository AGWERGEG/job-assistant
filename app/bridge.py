"""Narrow, paired extension gateway. No cookies, files or candidate data APIs."""
import hashlib
import re
import secrets
import threading
import time
import uuid
from urllib.parse import urlparse

from .store import Problem, text_field, require_object
from .company import company_ref, bind, Company

PROMPT_VERSION = "companion-v5-privacy1"
EXTENSION_ORIGIN = re.compile(r"^chrome-extension://[a-p]{32}$")


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def normalize_capture(value):
    require_object(value)
    url = text_field(value.get("url", ""), "岗位链接", 2000, True)
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ("www.zhipin.com", "zhipin.com") or parsed.username or parsed.password:
        raise Problem("只接收 BOSS HTTPS 岗位来源")
    job_key = text_field(value.get("job_key", ""), "平台岗位标识", 200, True)
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,200}", job_key):
        raise Problem("平台岗位标识无效")
    # Bind the claimed identity to the actual detail URL, never the list URL.
    if parsed.path != f"/job_detail/{job_key}.html":
        raise Problem("岗位标识与来源链接不一致")
    title = text_field(value.get("title", ""), "岗位名称", 200, True)
    company = text_field(value.get("company", ""), "公司", 300, True)
    jd = text_field(value.get("jd", ""), "JD", 50000, True)
    if len(jd) < 40:
        raise Problem("JD 内容不足，等待详情加载或用选中文字方式补充")
    method = value.get("method", "dom")
    if method not in ("dom", "selection"):
        raise Problem("采集方式无效")
    # Discard tracking params, security tokens and fragments at the boundary.
    result={"job_key": job_key, "url": f"https://www.zhipin.com/job_detail/{job_key}.html",
            "title": title, "company": company, "jd": jd, "method": method}
    if value.get('company_key'):
        key,company_url=company_ref(value)
        result.update(company_key=key,company_url=company_url)
    return result


class Bridge:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()
        self.code = None
        self.code_until = 0
        self.failed_pairs = []
        self.clients = {}
        self.pairing_revision = secrets.token_hex(8)
        self.scopes = {}
        self.last_auto = {}
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS browser_captures (
                    source_key TEXT PRIMARY KEY, job_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, observed_at REAL NOT NULL, method TEXT NOT NULL);
            ''')

    def issue_code(self):
        with self.lock:
            self.code = secrets.token_hex(8)
            self.code_until = time.time() + 300
            return {"code": self.code, "expires_in": 300}

    def paired(self):
        with self.lock:
            return bool(self.clients)

    def pairing_state(self):
        with self.lock:
            return {"extension_paired": bool(self.clients), "extension_pairing_revision": self.pairing_revision}

    def disconnect(self, origin):
        with self.lock:
            self.clients.pop(origin, None)
        return {"disconnected": True}

    def pair(self, origin, value):
        with self.lock:
            now = time.time()
            self.failed_pairs = [t for t in self.failed_pairs if now - t < 60]
            if len(self.failed_pairs) >= 5:
                raise Problem("配对尝试过多，请一分钟后重试", 429)
            offered = value.get("code", "")
            valid = isinstance(offered, str) and self.code and self.code_until > now and secrets.compare_digest(offered, self.code)
            if not EXTENSION_ORIGIN.fullmatch(origin or "") or not valid:
                self.failed_pairs.append(now)
                raise Problem("配对码错误或已过期，请在本地工作台重新生成", 403)
            key = secrets.token_urlsafe(32)
            self.clients[origin] = key
            self.pairing_revision = secrets.token_hex(8)
            self.code = None
            return {"token": key, "version": "0.4.0", "scope": "job-capture-and-advice-only"}

    def authenticate(self, origin, token):
        with self.lock:
            expected = self.clients.get(origin or "")
            if not expected or not isinstance(token, str) or not secrets.compare_digest(expected, token):
                raise Problem("扩展未配对或服务已重启，请重新配对", 401)
        return origin

    def revoke_all(self):
        with self.lock:
            self.clients.clear()
            self.code = None
            for scope in self.scopes:
                self._cancel_queued(scope)
            self.scopes.clear()
            with self.store.connect() as db:db.execute('DELETE FROM saved_targets')
            return {"revoked": True}

    def restore(self,client,value):
        scope=self._scope(client,value);seq=value.get('seq')
        if type(seq) is not int or seq<1:raise Problem('恢复序号无效')
        with self.lock:
            old=self.scopes.get(scope)
            if old and seq<=old['seq']:raise Problem('旧的恢复请求',409)
            with self.store.connect() as db:
                row=db.execute('SELECT j.* FROM saved_targets s JOIN jobs j ON j.id=s.job_id WHERE s.client=?',(client,)).fetchone()
                if not row:return {'job':None,'seq':seq}
                ref=db.execute('SELECT company_key FROM job_companies WHERE job_id=?',(row['id'],)).fetchone()
            job={k:row[k] for k in ('id','title','company','url','revision')};job['company_key']=ref[0] if ref else ''
            self.scopes[scope]={'seq':seq,'job_id':row['id'],'revision':row['revision'],'confirmed':True}
            import re
            match=re.search(r'/job_detail/([A-Za-z0-9_-]+)\.html',row['url'])
            return {'seq':seq,'job':job,'capture':{'job_key':match[1] if match else '', 'url':row['url'],'title':row['title'],'company':row['company'],'company_key':job['company_key'],'method':'restored'}}

    def _cancel_queued(self, scope, except_task=None):
        with self.store.connect() as db:
            db.execute("UPDATE tasks SET status='cancelled',updated=? WHERE bridge_scope=? AND automatic=1 AND status='queued' AND id!=?",
                       (time.time(), scope, except_task or ""))

    def _scope(self, client, value):
        scope = text_field(value.get("scope", ""), "浏览会话", 200, True)
        return digest(client + ":" + scope)

    def capture(self, client, value):
        scope = self._scope(client, value)
        seq = value.get("seq")
        if type(seq) is not int or seq < 1:
            raise Problem("页面序号无效")
        with self.lock:
            previous = self.scopes.get(scope)
            if previous and seq <= previous["seq"]:
                raise Problem("页面已切换，忽略旧采集结果", 409)
            if value.get("capture") is None:
                self.scopes[scope] = {"seq": seq, "job_id": None}
                self._cancel_queued(scope)
                return {"seq": seq, "job": None}
            capture = normalize_capture(value["capture"])
            source_key = "boss:" + capture["job_key"]
            fingerprint = digest(capture["title"] + "\n" + capture["company"] + "\n" + capture["jd"])
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                record = db.execute("SELECT * FROM browser_captures WHERE source_key=?", (source_key,)).fetchone()
                job = db.execute("SELECT * FROM jobs WHERE id=?", (record["job_id"],)).fetchone() if record else None
                if job:
                    job_id = job["id"]
                    fields = (capture["title"], capture["company"], capture["url"], capture["jd"])
                    if fields != tuple(job[k] for k in ("title", "company", "url", "jd")):
                        db.execute("UPDATE jobs SET title=?,company=?,url=?,jd=?,revision=revision+1 WHERE id=?", fields + (job_id,))
                else:
                    job_id = uuid.uuid4().hex
                    db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,'',1,?)", (job_id, capture["title"], capture["company"], capture["url"], capture["jd"], time.time()))
                db.execute("INSERT OR REPLACE INTO browser_captures VALUES(?,?,?,?,?)", (source_key, job_id, fingerprint, time.time(), capture["method"]))
                job = dict(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
                if capture.get('company_key'):bind(db,job_id,capture,capture['company'])
            self.scopes[scope] = {"seq": seq, "job_id": job_id, "revision": job["revision"]}
            self._cancel_queued(scope)
            return {"seq": seq, "job": {**{k: job[k] for k in ("id", "title", "company", "url", "revision")}, 'company_key':capture.get('company_key','')}}

    def task(self, client, value):
        scope = self._scope(client, value)
        kind = value.get("kind")
        if kind not in ("analyze_job", "tailor_resume", "suggest_reply"):
            raise Problem("任务类型无效")
        instruction = text_field(value.get("instruction", ""), "补充要求", 5000)
        conversation = text_field(value.get("conversation", ""), "对话摘录", 12000)
        auto = value.get("automatic") is True
        if auto and (kind != "analyze_job" or instruction or conversation):
            raise Problem("自动跟随仅支持岗位判断")
        with self.lock:
            current = self.scopes.get(scope)
            if type(value.get("seq")) is not int or not current or not current.get("job_id") or current["seq"] != value.get("seq"):
                raise Problem("当前岗位已变化，请重新识别", 409)
            with self.store.connect() as db:
                profile = db.execute("SELECT revision FROM profile WHERE id=1").fetchone()[0]
                job = db.execute("SELECT * FROM jobs WHERE id=?", (current["job_id"],)).fetchone()
                if job["revision"] != current["revision"]:
                    raise Problem("岗位资料已在其他窗口修改，请重新识别", 409)
                company_row=db.execute('SELECT c.revision FROM companies c JOIN job_companies j ON c.company_key=j.company_key WHERE j.job_id=?',(job['id'],)).fetchone()
                cache_key = digest(json_key([PROMPT_VERSION, job["id"], job["revision"], profile, kind, instruction, conversation,company_row[0] if company_row else 0]))
                cached = db.execute("SELECT * FROM tasks WHERE cache_key=? AND status='done' ORDER BY updated DESC LIMIT 1", (cache_key,)).fetchone()
                if cached:
                    result = self.store.decode_task(cached, private=False)
                    return {"seq": current["seq"], "job_id": job["id"], "task": result, "cached": True}
                existing = db.execute("SELECT * FROM tasks WHERE bridge_scope=? AND cache_key=? AND status IN ('queued','running')", (scope, cache_key)).fetchone()
                if existing:
                    return {"seq": current["seq"], "job_id": job["id"], "task": self.store.decode_task(existing, private=False), "cached": False}
            if auto and time.time() - self.last_auto.get(client, 0) < 12:
                raise Problem("浏览较快，暂缓自动分析；停留后可点击判断岗位", 429)
            task = self.store.create_task({"job_id": job["id"], "kind": kind, "instruction": instruction},
                bridge={"scope": scope, "seq": current["seq"], "cache_key": cache_key, "automatic": auto},
                conversation_override=conversation if kind == "suggest_reply" else None)
            self._cancel_queued(scope, task["id"])
            if auto:
                self.last_auto[client] = time.time()
            return {"seq": current["seq"], "job_id": job["id"], "task": task, "cached": False}

    def result(self, client, value):
        scope = self._scope(client, value)
        with self.lock:
            current = self.scopes.get(scope)
            if type(value.get("seq")) is not int or not current or current["seq"] != value.get("seq") or not current.get("job_id"):
                raise Problem("当前岗位已变化", 409)
            task_id = text_field(value.get("task_id", ""), "任务 ID", 100, True)
            with self.store.connect() as db:
                task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
                profile = db.execute("SELECT revision FROM profile WHERE id=1").fetchone()[0]
                job = db.execute("SELECT revision FROM jobs WHERE id=?", (current["job_id"],)).fetchone()
                if not task or task["job_id"] != current["job_id"] or not task["cache_key"]:
                    raise Problem("任务不属于当前岗位", 403)
                decoded = self.store.decode_task(task)
                stale = decoded["context"]["profile"]["revision"] != profile or decoded["context"]["job"]["revision"] != job[0]
                public = self.store.decode_task(task, private=False)
                return {"seq": current["seq"], "job_id": current["job_id"], "stale": stale, "task": public}

    def companion_action(self, client, value, action):
        from .companion import Companion
        scope = self._scope(client, value)
        with self.lock:
            current = self.scopes.get(scope)
            if not current or not current.get('job_id') or type(value.get('seq')) is not int or value['seq'] != current['seq']:
                raise Problem('页面已变化，请重新确认岗位', 409)
            with self.store.connect() as db:
                job = db.execute('SELECT * FROM jobs WHERE id=?', (current['job_id'],)).fetchone()
                company = db.execute('SELECT company_key FROM job_companies WHERE job_id=?', (current['job_id'],)).fetchone()
            if action == 'sync':
                if not job or not current.get('confirmed'):
                    raise Problem('先确认目标岗位，再同步', 409)
                current['revision'] = job['revision']
                return {'seq':current['seq'], 'job':{**{k:job[k] for k in ('id','title','company','url','revision')},'company_key':company[0] if company else ''}}
            if not job or job['revision'] != current['revision']:
                raise Problem('岗位内容已更新，请重新识别并确认', 409)
            if action == 'confirm':
                current['confirmed'] = True
                with self.store.connect() as db:db.execute('INSERT OR REPLACE INTO saved_targets VALUES(?,?)',(client,current['job_id']))
                # Only an explicit “confirm this job” may advance the first-use loop.
                # This preserves the pinned-target rule: browsing never changes it.
                Companion(self.store).onboarding_job(current['job_id'])
                return {'confirmed': True, 'seq': current['seq'], 'job_id': current['job_id']}
            if not current.get('confirmed'):
                raise Problem('先确认这个岗位，再一起聊', 409)
            if action == 'company-save':
                return {'company':Company(self.store).ingest(current['job_id'],value.get('company',{})),'seq':current['seq'],'job_id':current['job_id']}
            if action == 'company-read':
                return {'company':Company(self.store).read(current['job_id']),'seq':current['seq'],'job_id':current['job_id']}
            companion = Companion(self.store)
            if action == 'history':
                return {**companion.history(current['job_id']), 'seq': current['seq'], 'job_id': current['job_id']}
            if action == 'talk':
                return {**companion.send({**value, 'job_id': current['job_id']}), 'seq': current['seq']}
            if action in ('cancel','retry'):
                task_id=text_field(value.get('task_id',''),'任务',100,True)
                with self.store.connect() as db:
                    if not db.execute('SELECT 1 FROM messages WHERE task_id=? AND job_id=?',(task_id,current['job_id'])).fetchone():raise Problem('任务不属于目标对话',403)
                task=self.store.cancel(task_id) if action=='cancel' else self.store.retry(task_id)
                task.pop('context',None);task.pop('claim_token',None)
                return {'task':task,'seq':current['seq'],'job_id':current['job_id']}
            raise Problem('未知对话动作')


def json_key(value):
    import json
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
