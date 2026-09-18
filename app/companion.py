"""Local companion settings, persistent job conversations and draft acceptance."""
import json
import re
import time
import uuid
from urllib.parse import urlparse

from .privacy import fingerprint, redact, safe_context, terms_from
from .store import Problem, require_object, text_field, TASK_KINDS, task_lane

PERSONAS = {
    "gentle": {"title": "温柔搭子", "hello": "我是你的 AI 求职搭子。先从一个岗位、一件小事开始，我陪你一起理清楚。", "prompt": "温和、具体，先接住感受再给一个可执行的小步骤。不空泛鼓励，不保证录用。"},
    "direct": {"title": "直球搭子", "hello": "我是你的 AI 求职搭子。机会一起挑，材料一起改，有疑虑我们直接说清楚。", "prompt": "直接、坦诚、有分寸。先说判断再说理由，不讽刺、不说教，不把资料缺失当能力不足。"},
}
DEFAULTS = {"persona": "gentle", "buddy_name": "小伴", "user_name": "", "stage": "应届生", "private_terms": "", "provider": "codex", "base_url": "", "api_model": "", "api_key": "", "json_mode": True, "privacy_approved": "", "onboarded": False,
            "guide_connection_ready": False, "guide_persona_ready": False, "guide_job_id": "", "guide_first_task_id": "", "guide_review_task_id": "", "guide_completed": False, "guide_version": ""}


class Companion:
    def __init__(self, store):
        self.store = store

    def settings(self, public=False):
        with self.store.connect() as db:
            row = db.execute("SELECT value FROM companion_settings WHERE id=1").fetchone()
        stored = json.loads(row[0]) if row else {}
        value = {**DEFAULTS, **stored}
        # Existing confirmed users should not be dropped back into a brand-new tutorial.
        if not stored.get("guide_version") and value.get("onboarded"):
            value["guide_completed"] = True
        if public:
            value["guide"] = self.onboarding_state(value)
            value["has_api_key"] = bool(value.pop("api_key", ""))
            value.pop("privacy_approved", None)
            value["personas"] = PERSONAS
        return value

    def onboarding_state(self, settings=None):
        settings = settings or self.settings()
        if settings.get("guide_completed"):
            return {"active": False, "step": "complete", "job": None}
        override = settings.get("guide_view", "")
        if override in ("pairing", "connection", "persona", "profile", "privacy", "browse"):
            return {"active": True, "step": override, "job": None, "reviewing": True}
        with self.store.connect() as db:
            profile = db.execute("SELECT facts FROM profile WHERE id=1").fetchone()[0]
            job = db.execute("SELECT id,title,company FROM jobs WHERE id=?", (settings.get("guide_job_id", ""),)).fetchone()
            rows = {r["id"]: r for r in db.execute("SELECT id,job_id,kind,status FROM tasks WHERE id IN (?,?)", (settings.get("guide_first_task_id", ""), settings.get("guide_review_task_id", "")))}
        if not settings.get("guide_connection_ready"):
            return {"active": True, "step": "connection", "job": None}
        if not settings.get("guide_persona_ready"):
            return {"active": True, "step": "persona", "job": None}
        if not profile.strip():
            return {"active": True, "step": "profile", "job": None}
        if not self.ready():
            return {"active": True, "step": "privacy", "job": None}
        if not job:
            return {"active": True, "step": "browse", "job": None}
        public_job = dict(job)
        first = rows.get(settings.get("guide_first_task_id", ""))
        if not first or first["job_id"] != job["id"] or first["status"] in ("failed", "cancelled"):
            return {"active": True, "step": "first_reply", "job": public_job}
        if first["status"] != "done":
            return {"active": True, "step": "first_reply_wait", "job": public_job, "task_id": first["id"]}
        return {"active": True, "step": "first_success", "job": public_job, "task_id": first["id"]}

    def _save_guide(self, db, settings):
        db.execute("INSERT OR REPLACE INTO companion_settings VALUES(1,?)", (json.dumps(settings, ensure_ascii=False),))

    def onboarding_action(self, value):
        require_object(value)
        action = text_field(value.get("action", ""), "引导动作", 40, True)
        current_step = self.onboarding_state().get("step")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value FROM companion_settings WHERE id=1").fetchone()
            stored = json.loads(row[0]) if row else {}
            settings = {**DEFAULTS, **stored}
            if not stored.get("guide_version") and settings.get("onboarded"):
                settings["guide_completed"] = True
            elif not settings.get("guide_version"):
                settings["guide_version"] = "v0103"
            if action == "connection":
                if settings["provider"] == "api" and (not settings["base_url"] or not settings["api_model"]):
                    raise Problem("请先填写兼容地址和模型名称，再继续")
                settings["guide_connection_ready"] = True
                settings.pop("guide_view", None)
            elif action == "persona":
                if settings["persona"] not in PERSONAS or not settings["buddy_name"]:
                    raise Problem("请先选择角色并填写搭子称呼")
                settings["guide_persona_ready"] = True
                settings.pop("guide_view", None)
            elif action == "review-task":
                task_id = text_field(value.get("task_id", ""), "引导任务", 100, True)
                task = db.execute("SELECT id,job_id,kind FROM tasks WHERE id=?", (task_id,)).fetchone()
                if not task or task["job_id"] != settings.get("guide_job_id") or task["kind"] not in ("analyze_job", "tailor_resume", "interview_prep"):
                    raise Problem("请选择当前引导岗位的深入分析、岗位简历或面试准备卡")
                settings["guide_review_task_id"] = task_id
            elif action == "complete":
                task_id = settings.get("guide_first_task_id", "")
                task = db.execute("SELECT job_id,status FROM tasks WHERE id=?", (task_id,)).fetchone()
                if not task or task["job_id"] != settings.get("guide_job_id") or task["status"] != "done":
                    raise Problem("先完成第一次岗位判断，再结束首次引导")
                settings["guide_completed"] = True
            elif action == "skip":
                settings["guide_completed"] = True
                settings["guide_version"] = "v0112"
                settings.pop("guide_view", None)
            elif action == "back":
                # Pairing is runtime-only; all other steps come from persisted guide state.
                current = "pairing" if value.get("step") == "pairing" else current_step
                previous={"connection":"pairing","persona":"connection","profile":"persona","privacy":"profile","browse":"privacy","first_reply":"browse","first_reply_wait":"browse","first_success":"browse"}.get(current)
                if not previous:
                    raise Problem("当前步骤没有可返回的上一步")
                settings["guide_view"] = previous
            elif action == "connection-settings":
                settings["guide_view"] = "connection"
            elif action == "continue":
                settings.pop("guide_view", None)
            elif action == "restart":
                settings.update(guide_version="v0103", guide_completed=False, guide_connection_ready=True, guide_persona_ready=True,
                                guide_job_id="", guide_first_task_id="", guide_review_task_id="", guide_view="connection")
            else:
                raise Problem("未知引导动作")
            self._save_guide(db, settings)
        return {**self.settings(public=True), "ready": self.ready()}

    def onboarding_job(self, job_id):
        # Resolve readiness before opening the write transaction: ready() reads the
        # profile and settings through its own short-lived connection.
        ready = self.ready()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value FROM companion_settings WHERE id=1").fetchone()
            stored = json.loads(row[0]) if row else {}
            settings = {**DEFAULTS, **stored}
            if not stored.get("guide_version") and settings.get("onboarded"):
                settings["guide_completed"] = True
            if not settings.get("guide_completed") and ready:
                settings.update(guide_job_id=job_id, guide_first_task_id="", guide_review_task_id="")
                self._save_guide(db, settings)

    def onboarding_first_task(self, job_id, task):
        if task.get("kind") not in ("quick_analysis", "companion_chat"):
            return
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value FROM companion_settings WHERE id=1").fetchone()
            stored = json.loads(row[0]) if row else {}
            settings = {**DEFAULTS, **stored}
            if (not settings.get("guide_completed") and settings.get("guide_job_id") == job_id
                    and (not settings.get("guide_first_task_id") or
                         db.execute("SELECT status FROM tasks WHERE id=?", (settings["guide_first_task_id"],)).fetchone()[0] in ("failed", "cancelled"))):
                settings["guide_first_task_id"] = task["id"]
                self._save_guide(db, settings)

    def profile(self):
        with self.store.connect() as db:
            return dict(db.execute("SELECT * FROM profile WHERE id=1").fetchone())

    def ready(self):
        settings = self.settings()
        return bool(settings["onboarded"] and settings["privacy_approved"] == fingerprint(self.profile(), settings))

    def save_settings(self, value):
        require_object(value)
        # Read/modify/write under a transaction to avoid losing a concurrent key update.
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value FROM companion_settings WHERE id=1").fetchone()
            stored = json.loads(row[0]) if row else {}
            settings = {**DEFAULTS, **stored}
            if not stored.get("guide_version"):
                if settings.get("onboarded"):
                    settings["guide_completed"] = True
                else:
                    settings["guide_version"] = "v0103"
            if 'base_url' in value and text_field(value['base_url'], '兼容地址', 1000).rstrip('/') != settings['base_url'].rstrip('/'):
                # A key saved for one endpoint is not silently reused at another.
                settings['api_key'] = ''
            for key, limit in (("buddy_name", 24), ("user_name", 40), ("stage", 40), ("private_terms", 6000), ("base_url", 1000), ("api_model", 200), ("api_key", 1000)):
                if key in value:
                    item = text_field(value[key], key, limit)
                    if key != "api_key" or item:
                        settings[key] = item
            if value.get("clear_api_key") is True:
                settings["api_key"] = ""
            for key, allowed in (("persona", PERSONAS), ("provider", ("codex", "api"))):
                if key in value:
                    if value[key] not in allowed:
                        raise Problem("角色或接入方式无效")
                    settings[key] = value[key]
            if not settings["buddy_name"]:
                raise Problem("请给搭子一个称呼")
            if "json_mode" in value:
                settings["json_mode"] = value["json_mode"] is True
            if 'stream' in value:settings['stream']=value['stream'] is True
            if 'celebrations' in value:settings['celebrations']=value['celebrations'] is True
            if settings["base_url"]:
                validate_url(settings["base_url"])
            db.execute("INSERT OR REPLACE INTO companion_settings VALUES(1,?)", (json.dumps(settings, ensure_ascii=False),))
        return self.settings(public=True)

    def preview_profile(self):
        settings, profile = self.settings(), self.profile()
        preview = safe_context({"profile": profile}, settings)
        with self.store.connect() as db:facts=[dict(r) for r in db.execute('SELECT id,category,content,source FROM profile_facts ORDER BY created')]
        facts=redact(facts,[profile.get('name',''),settings['user_name']],terms_from(settings))
        return {"token": fingerprint(profile, settings), "preview": {**preview['profile'], 'career_stage': preview['career_stage'],'confirmed_facts':facts},
                "note": "本地规则会移除已识别的姓名、号码、邮箱、链接及敏感词。未标注人名、地址和独特经历可能仍可识别，请补充敏感词后再次预览。"}

    def approve(self, value):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value FROM companion_settings WHERE id=1").fetchone()
            stored = json.loads(row[0]) if row else {}
            settings = {**DEFAULTS, **stored}
            was_onboarded = bool(settings.get("onboarded"))
            profile = dict(db.execute("SELECT * FROM profile WHERE id=1").fetchone())
            expected = fingerprint(profile, settings)
            if value.get("token") != expected or value.get("confirmed") is not True:
                raise Problem("档案已变化，请重新预览并确认", 409)
            if not profile["facts"].strip():
                raise Problem("先填写或上传简历经历")
            if not settings.get("guide_version"):
                if was_onboarded:
                    settings["guide_completed"] = True
                else:
                    settings["guide_version"] = "v0103"
            settings.update(privacy_approved=expected, onboarded=True)
            db.execute("INSERT OR REPLACE INTO companion_settings VALUES(1,?)", (json.dumps(settings, ensure_ascii=False),))
        return {"ready": True}

    def history(self, job_id):
        job_id = text_field(job_id, '岗位', 100)
        with self.store.connect() as db:
            rows = db.execute("SELECT t.* FROM messages m JOIN tasks t ON t.id=m.task_id WHERE m.job_id=? ORDER BY m.created DESC LIMIT 60", (job_id,)).fetchall()
            versions = [dict(r) for r in db.execute("SELECT id,task_id,created FROM resume_versions WHERE job_id=? ORDER BY created DESC", (job_id,))]
        turns = []
        for row in reversed(rows):
            task = self.store.decode_task(row)
            result = task.get("result") or {}
            stale = False
            if result:
                with self.store.connect() as db:
                    p = db.execute("SELECT revision FROM profile WHERE id=1").fetchone()[0]
                    j = db.execute("SELECT revision FROM jobs WHERE id=?", (job_id,)).fetchone()
                stale = result.get("profile_revision") != p or result.get("job_revision") != (j[0] if j else 0)
                from .company import Company
                background=Company(self.store).read(job_id)
                if background and result.get('company_revision',0)!=background['revision']:stale=True
            turns.append({"task_id": task["id"], "kind": task["kind"], "text": task["context"].get("instruction", ""),
                          "status": task["status"], "created": task["created"], "updated": task["updated"], "error": task.get("error_text"),
                          "reply": result.get("primary_output") or result.get("summary", ""), "partial":task.get('partial_text','') if task['status']=='running' else '', "stale": stale,
                          "workbench": task_lane(task["kind"]) == 'background', "metrics": task.get("metrics", {})})
        settings = self.settings()
        # Extension history never receives raw profile, local source text, or secrets.
        return redact({"turns": turns, "versions": versions}, [self.profile().get("name", ""), settings["user_name"]], terms_from(settings))

    def send(self, value):
        if not self.ready():
            raise Problem("请先到工作台完成认识搭子和脱敏档案确认", 409)
        kind = value.get("kind", "companion_chat")
        if kind not in TASK_KINDS or kind == 'closing_message':
            raise Problem("对话动作无效")
        message = text_field(value.get("text", ""), "消息", 6000)
        defaults = {"quick_analysis": "帮我快速看看这个岗位值得尝试吗？", "analyze_job": "请深入分析这个岗位。", "tailor_resume": "帮我针对这个岗位优化简历。", "suggest_reply": "帮我写一条联系 HR 的招呼。"}
        defaults['interview_prep'] = '请结合这个岗位、公司资料和我的真实经历，准备一张面试逻辑卡。轮次和形式暂未补充，请说明假设。'
        defaults['rest_message'] = '今天先休息，结束这一轮找工作。请留给我一段简短寄语，不再安排任务。'
        message = message or defaults.get(kind, "")
        if not message:
            raise Problem("先跟搭子说点什么")
        if kind == 'interview_review' and len(message.strip()) < 12:
            raise Problem('请至少写下一个实际面试问题、你的回答或卡住的地方，再一起复盘')
        from .closing import declares_joined
        if kind == 'companion_chat' and declares_joined(message):
            kind = 'closing_message'
        if kind == 'companion_chat' and value.get('job_id'):
            # Route only explicit action requests, not statements about feelings
            # or quotations such as “HR 让我改简历”. Everything else stays chat.
            if re.match(r'^(?:请|帮我|请帮我)(?:针对这个岗位|针对该岗位)?(?:优化|修改|改一下|改写|改)简历', message):
                kind = 'tailor_resume'
            elif re.match(r'^(?:请|帮我|请帮我)(?:写|准备)(?:一条|个|一段)?(?:HR招呼|HR 招呼|招呼|开场白)', message):
                kind = 'suggest_reply'
            elif re.match(r'^(?:请|帮我|请帮我)(?:深入|深度)分析', message):
                kind = 'analyze_job'
        job_id = value.get("job_id", "")
        task = self.store.create_task({"kind": kind, "job_id": job_id, "instruction": message, "companion": True,
                                       "request_id": text_field(value.get("request_id", ""), "请求标识", 100, True)})
        if job_id:
            self.onboarding_first_task(job_id, task)
        return {"task": task, "job_id": job_id}

    def accept_resume(self, value):
        task = self.store.get_task(text_field(value.get("task_id", ""), "任务", 100, True))
        if task["kind"] != "tailor_resume" or task["status"] != "done":
            raise Problem("只能验收已经完成的简历任务")
        content = text_field(value.get("content", ""), "简历正文", 30000, True)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            p = db.execute("SELECT revision FROM profile WHERE id=1").fetchone()[0]
            j = db.execute("SELECT revision FROM jobs WHERE id=?", (task["job_id"],)).fetchone()
            if not j or task["result"].get("profile_revision") != p or task["result"].get("job_revision") != j[0]:
                raise Problem("档案或岗位已变化，请重新生成后验收", 409)
            old = db.execute("SELECT id FROM resume_versions WHERE task_id=? AND content=?", (task["id"], content)).fetchone()
            version = old[0] if old else uuid.uuid4().hex
            if not old:
                db.execute("INSERT INTO resume_versions VALUES(?,?,?,?,?)", (version, task["job_id"], task["id"], content, time.time()))
        return {"id": version, "saved": True}


def validate_url(value):
    parsed = urlparse(value)
    if (parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or (parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"))):
        raise Problem("兼容地址需为 HTTPS（本机可用 HTTP），不能包含密钥、查询参数或账号")
    return value.rstrip("/")
