"""Narrow, paired extension gateway. No cookies, files or candidate data APIs."""
import hashlib
import hmac
import re
import secrets
import threading
import time
import uuid
from urllib.parse import urlparse, urlunparse

from .store import Problem, text_field, require_object
from .company import company_ref, source_url as company_source_url, bind, Company
from .version import EXTENSION_ID, EXTENSION_NAME, VERSION, is_extension_origin

PROMPT_VERSION = "companion-v5-privacy1"
# Kept as a narrow compatibility export for the server's CORS and preflight
# checks. Unlike the old pattern, this only matches this shipped extension.
EXTENSION_ORIGIN = re.compile(r"^chrome-extension://" + re.escape(EXTENSION_ID) + r"$")


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

JOB_KEY = re.compile(r"^[A-Za-z0-9._~-]{4,200}$")


def extension_name_hint(name, extension_id):
    return f"{name} · {extension_id}"


def source_identity(url):
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return None
    if host in ("www.zhipin.com", "zhipin.com"):
        match = re.fullmatch(r"/job_detail/([A-Za-z0-9_-]{4,200})\.html", parsed.path)
        return ("boss", match.group(1)) if match else None
    if host == "zhaopin.com" or host.endswith(".zhaopin.com"):
        match = re.fullmatch(r"/jobdetail/([A-Za-z0-9._~-]{4,200})\.(?:htm|html)", parsed.path, re.I)
        if not match:
            match = re.fullmatch(r"/(?:position|job)/([A-Za-z0-9._~-]{4,200})(?:/|\.(?:htm|html))?", parsed.path, re.I)
        return ("zhaopin", match.group(1)) if match else None
    if host == "58.com" or host.endswith(".58.com"):
        match = re.fullmatch(r"/zp[^/]+/([A-Za-z0-9_-]{8,200})\.(?:shtml|html)", parsed.path, re.I)
        if not match and re.search(r"(?:job|zhaopin|detail)[/_-]", parsed.path, re.I):
            raw = parsed.path.rstrip("/").rsplit("/", 1)[-1]
            raw = re.sub(r"\.(?:shtml|html?)$", "", raw, flags=re.I)
            match = re.fullmatch(r"([A-Za-z0-9._~-]{4,200})", raw)
        return ("58", match.group(1)) if match else None
    return None


def safe_recruitment_url(raw, kind):
    url = text_field(raw, '招聘网页链接', 2000, True)
    try: parsed = urlparse(url)
    except ValueError: raise Problem('招聘网页链接无效')
    host = (parsed.hostname or '').lower()
    site = 'boss' if host in ('www.zhipin.com','zhipin.com') else 'zhaopin' if host == 'zhaopin.com' or host.endswith('.zhaopin.com') else '58' if host == '58.com' or host.endswith('.58.com') else ''
    try: valid_port = parsed.port in (None,443)
    except ValueError: valid_port = False
    if parsed.scheme != 'https' or not site or parsed.username or parsed.password or not valid_port:
        raise Problem('只允许记录支持招聘网站的 HTTPS 链接')
    if kind == 'job_detail' and not source_identity(url):
        raise Problem('请先打开独立岗位详情页录入 JD')
    if kind == 'hr_chat' and not re.search(r'/chat|/geek/chat|/im/',parsed.path,re.I):
        raise Problem('当前页面不是可识别的 HR 聊天页')
    # Chat identifiers often live in the query string. Keep it for exact
    # matching; the record stays local and is never sent to a model.
    return urlunparse(('https',host,parsed.path,'',parsed.query, '')),site


def normalize_capture(value):
    require_object(value)
    url = text_field(value.get("url", ""), "岗位链接", 2000, True)
    parsed = urlparse(url)
    host=(parsed.hostname or '').lower()
    if parsed.scheme != "https" or parsed.username or parsed.password or not (host in ("www.zhipin.com","zhipin.com") or host=='zhaopin.com' or host.endswith('.zhaopin.com') or host=='58.com' or host.endswith('.58.com')):
        raise Problem("只接收支持招聘网站的 HTTPS 岗位来源")
    job_key = text_field(value.get("job_key", ""), "平台岗位标识", 200, True)
    if not JOB_KEY.fullmatch(job_key):
        raise Problem("平台岗位标识无效")
    # Bind every claimed identity to its canonical public detail URL.
    identity = source_identity(url)
    if not identity or identity[1] != job_key:
        raise Problem("岗位标识与来源链接不一致")
    site = identity[0]
    title = text_field(value.get("title", ""), "岗位名称", 200, True)
    company = text_field(value.get("company", ""), "公司", 300, True)
    jd = text_field(value.get("jd", ""), "JD", 50000, True)
    if len(jd) < 40:
        raise Problem("JD 内容不足，等待详情加载或用选中文字方式补充")
    method = value.get("method", "dom")
    if method not in ("dom", "selection"):
        raise Problem("采集方式无效")
    # Discard tracking params, security tokens and fragments at the boundary.
    result={"job_key": job_key, "url": (f"https://www.zhipin.com/job_detail/{job_key}.html" if site=='boss' else f"{parsed.scheme}://{parsed.netloc}{parsed.path}"),
            "title": title, "company": company, "jd": jd, "method": method, "source_site": site}
    if site == 'boss' and value.get('recruiter_name'):
        result['recruiter_name'] = text_field(value['recruiter_name'], '招聘者姓名', 100, True)
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
        self.pair_requests = {}
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
            now = time.time()
            self.pair_requests = {key: request for key, request in self.pair_requests.items() if request["expires"] > now}
            return {"extension_paired": bool(self.clients), "extension_pairing_revision": self.pairing_revision,
                    "extension_pair_requests": sum(1 for request in self.pair_requests.values() if request["status"] == "pending")}

    def discover(self, origin):
        if not is_extension_origin(origin):
            raise Problem("只允许浏览器扩展发现本机服务", 403)
        return {"ok": True, "version": VERSION, "pairing": "confirmation"}

    def server_proof(self, origin, nonce):
        if not is_extension_origin(origin):
            raise Problem("只允许浏览器扩展验证本机服务", 403)
        if not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{64}", nonce):
            raise Problem("服务验证随机数无效")
        with self.lock:
            token = self.clients.get(origin)
            if not token:
                raise Problem("扩展未配对或服务已重启，请重新配对", 401)
            proof = hmac.new(token.encode("utf-8"), nonce.encode("ascii"), hashlib.sha256).hexdigest()
        return {"version": VERSION, "nonce": nonce, "proof": proof}

    def request_pair(self, origin):
        if not is_extension_origin(origin):
            raise Problem("只允许浏览器扩展申请连接", 403)
        with self.lock:
            now = time.time()
            self.pair_requests = {key: request for key, request in self.pair_requests.items() if request["expires"] > now}
            for request_id, request in self.pair_requests.items():
                if request["origin"] == origin and request["status"] == "pending":
                    return {"request_id": request_id, "expires_in": max(1, int(request["expires"] - now))}
            if len(self.pair_requests) >= 20:
                raise Problem("本机连接申请过多，请稍后重试", 429)
            request_id = secrets.token_urlsafe(32)
            self.pair_requests[request_id] = {"origin": origin, "status": "pending", "expires": now + 300, "token": ""}
            return {"request_id": request_id, "expires_in": 300}

    def pair_request_info(self, request_id):
        with self.lock:
            request = self.pair_requests.get(request_id)
            if not request or request["expires"] <= time.time():
                self.pair_requests.pop(request_id, None)
                raise Problem("连接申请不存在或已过期，请从侧栏重新发起", 404)
            extension_id = request["origin"].removeprefix("chrome-extension://")
            return {"request_id": request_id, "status": request["status"],
                    "extension_id": extension_id, "extension_name": EXTENSION_NAME,
                    "extension_hint": extension_name_hint(EXTENSION_NAME, extension_id),
                    "expires_in": max(1, int(request["expires"] - time.time()))}

    def approve_pair_request(self, request_id, confirmed):
        if confirmed is not True:
            raise Problem("请明确确认连接这个侧栏")
        with self.lock:
            request = self.pair_requests.get(request_id)
            if not request or request["expires"] <= time.time():
                self.pair_requests.pop(request_id, None)
                raise Problem("连接申请不存在或已过期，请从侧栏重新发起", 404)
            if request["status"] != "approved":
                token = secrets.token_urlsafe(32)
                request["token"] = token
                request["status"] = "approved"
                self.clients[request["origin"]] = token
                self.pairing_revision = secrets.token_hex(8)
            return {"approved": True, **self.pair_request_info(request_id)}

    def pair_request_status(self, origin, request_id):
        if not is_extension_origin(origin):
            raise Problem("只允许浏览器扩展查询连接申请", 403)
        with self.lock:
            request = self.pair_requests.get(request_id)
            if not request or request["expires"] <= time.time():
                self.pair_requests.pop(request_id, None)
                raise Problem("连接申请不存在或已过期，请重新发起", 404)
            if request["origin"] != origin:
                raise Problem("连接申请不属于当前扩展", 403)
            response = {"status": request["status"], "expires_in": max(1, int(request["expires"] - time.time()))}
            if request["status"] == "approved":
                response["token"] = request["token"]
                response["version"] = VERSION
            return response

    def disconnect(self, origin):
        with self.lock:
            self.clients.pop(origin, None)
            self.pair_requests = {key: request for key, request in self.pair_requests.items() if request["origin"] != origin}
        return {"disconnected": True}

    def pair(self, origin, value):
        with self.lock:
            now = time.time()
            self.failed_pairs = [t for t in self.failed_pairs if now - t < 60]
            if len(self.failed_pairs) >= 5:
                raise Problem("配对尝试过多，请一分钟后重试", 429)
            offered = value.get("code", "")
            valid = isinstance(offered, str) and self.code and self.code_until > now and secrets.compare_digest(offered, self.code)
            if not is_extension_origin(origin) or not valid:
                self.failed_pairs.append(now)
                raise Problem("配对码错误或已过期，请在本地工作台重新生成", 403)
            key = secrets.token_urlsafe(32)
            self.clients[origin] = key
            self.pairing_revision = secrets.token_hex(8)
            self.code = None
            return {"token": key, "version": VERSION, "scope": "job-capture-and-advice-only"}

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
            self.pair_requests.clear()
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
            identity=source_identity(row['url'])
            return {'seq':seq,'job':job,'capture':{'job_key':identity[1] if identity else '', 'source_site':identity[0] if identity else '', 'url':row['url'],'title':row['title'],'company':row['company'],'company_key':job['company_key'],'method':'restored'}}

    def jobs(self, client, value):
        self._scope(client,value)
        with self.store.connect() as db:
            rows=db.execute("SELECT j.id,j.title,j.company,j.url,j.revision,COALESCE(MAX(m.created),0) AS last_chat_at FROM jobs j LEFT JOIN messages m ON m.job_id=j.id GROUP BY j.id ORDER BY last_chat_at DESC,j.created DESC").fetchall()
            return {'jobs':[{k:r[k] for k in ('id','title','company','revision','last_chat_at')} for r in rows]}

    def select(self, client, value):
        scope=self._scope(client,value); seq=value.get('seq')
        if type(seq) is not int or seq<1:raise Problem('切换序号无效')
        job_id=text_field(value.get('job_id',''),'岗位',100,True)
        with self.lock:
            old=self.scopes.get(scope)
            if old and seq<=old['seq']:raise Problem('旧的切换请求',409)
            with self.store.connect() as db:
                job=db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
                if not job:raise Problem('岗位不存在',404)
                ref=db.execute('SELECT company_key FROM job_companies WHERE job_id=?',(job_id,)).fetchone()
                db.execute('INSERT OR REPLACE INTO saved_targets VALUES(?,?)',(client,job_id))
            self.scopes[scope]={'seq':seq,'job_id':job_id,'revision':job['revision'],'confirmed':True}
            self._cancel_queued(scope)
            identity=source_identity(job['url'])
            public={k:job[k] for k in ('id','title','company','url','revision')};public['company_key']=ref[0] if ref else ''
            return {'seq':seq,'job':public,'capture':{'job_key':identity[1] if identity else '', 'source_site':identity[0] if identity else '', 'url':job['url'],'title':job['title'],'company':job['company'],'company_key':public['company_key'],'method':'selected'}}

    def links(self, client, value):
        self._scope(client,value)
        job_id=text_field(value.get('job_id',''),'岗位',100,True)
        with self.store.connect() as db:
            if not db.execute('SELECT 1 FROM jobs WHERE id=?',(job_id,)).fetchone():raise Problem('岗位不存在',404)
        return {'links':[{'kind':link['kind'],'url':link['url'],'updated':link['updated']}
                         for link in self.store.list_job_links(job_id)]}

    def link_context(self, client, value):
        self._scope(client,value)
        from .chat_links import chat_identity, match_job
        chat=chat_identity(value.get('chat'))
        link=self.store.chat_binding(chat['key'])
        if link:
            with self.store.connect() as db:
                job=db.execute('SELECT * FROM jobs WHERE id=?',(link['job_id'],)).fetchone()
            reason=match_job(chat,job,self.store.recruiter_for_job(link['job_id'])) if job else '岗位已不存在'
            if link['recruiter_name']!=chat['recruiter_name'] or link['company']!=chat['company'] or link['job_title']!=chat['job_title']:
                reason=reason or '会话信息与已保存绑定不一致'
            return {'link':{'job_id':link['job_id'],'title':link['title'],
                            'company':link['job_company'],'recruiter_name':link['recruiter_name']},
                    'conflict':reason,'matches':[],'legacy':False,
                    'recruiter_verified':bool(self.store.recruiter_for_job(link['job_id']))}
        matches=[]
        for job in self.store.state()['jobs']:
            if not match_job(chat,job,self.store.recruiter_for_job(job['id'])):
                matches.append({'id':job['id'],'title':job['title'],'company':job['company'],
                                'recruiter_verified':bool(self.store.recruiter_for_job(job['id']))})
        with self.store.connect() as db:
            legacy=bool(db.execute("SELECT 1 FROM job_links WHERE kind='hr_chat' AND url=? LIMIT 1",
                                   (chat['url'],)).fetchone())
        return {'link':None,'conflict':'','matches':matches,'legacy':legacy}

    def link_save(self, client, value):
        from .chat_links import chat_identity, match_job
        scope=self._scope(client,value)
        chat=chat_identity(value.get('chat'))
        job_id=text_field(value.get('job_id',''),'岗位',100,True)
        with self.lock:
            current=self.scopes.get(scope)
            if not current or not current.get('confirmed') or value.get('seq')!=current['seq'] or current['job_id']!=job_id:
                raise Problem('请先手动选定待关联岗位',409)
            with self.store.connect() as db:
                job=db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
            if not job: raise Problem('岗位不存在',404)
            reason=match_job(chat,job,self.store.recruiter_for_job(job_id))
            if reason: raise Problem('关联核验失败：'+reason,409)
            return {'link':self.store.bind_chat(chat,job_id)}

    def link_unbind(self, client, value):
        from .chat_links import chat_identity
        self._scope(client,value)
        chat=chat_identity(value.get('chat'))
        job_id=text_field(value.get('job_id',''),'岗位',100,True)
        return self.store.unbind_chat(chat['key'],job_id)

    def resume_import(self, client, value):
        """Persist only an explicitly requested online-resume draft locally."""
        from .profile_import import ProfileImport
        # Authentication is enforced by the HTTP boundary. The client argument
        # is intentionally not stored, so extension identity never enters a CV.
        return ProfileImport(self.store).save(value)

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
            source_key = capture.get('source_site','boss') + ":" + capture["job_key"]
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
                if capture.get('recruiter_name'):
                    db.execute('INSERT OR REPLACE INTO job_recruiters VALUES(?,?,?,?)',
                               (job_id,capture['recruiter_name'],capture['url'],time.time()))
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
                if job['url']:
                    url,_=safe_recruitment_url(job['url'],'job_detail')
                    self.store.save_job_link({'job_id':job['id'],'kind':'job_detail','url':url})
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
            if action == 'company-bind':
                data=value.get('company')
                key,company_url=company_ref(data)
                source=company_source_url(data.get('source_url',''))
                if source!=job['url']:
                    try:source_key,_=company_ref({**data,'company_url':source})
                    except Problem:raise Problem('请从当前目标岗位或对应公司页确认公司关联',409)
                    if source_key!=key:raise Problem('请从当前目标岗位或对应公司页确认公司关联',409)
                identity=source_identity(job['url'])
                if not identity or data.get('source_site')!=identity[0]:
                    raise Problem('公司与目标岗位不是同一招聘站点',409)
                with self.store.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    old=db.execute('SELECT company_key FROM job_companies WHERE job_id=?',(job['id'],)).fetchone()
                    if old and old[0]!=key:
                        raise Problem('目标岗位已经关联其他公司，未更改',409)
                    bind(db,job['id'],data,text_field(data.get('name',''),'公司名称',300,True))
                current['company_key']=key
                return {'seq':current['seq'],'job_id':job['id'],'company_key':key,'company_url':company_url}
            if action == 'company-read':
                return {'company':Company(self.store).read(current['job_id']),'seq':current['seq'],'job_id':current['job_id']}
            companion = Companion(self.store)
            if action == 'history':
                return {**companion.history(current['job_id']), 'seq': current['seq'], 'job_id': current['job_id']}
            if action == 'talk':
                return {**companion.send({**value, 'job_id': current['job_id']}, target_client=client), 'seq': current['seq']}
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
