"""Local UI API. No model, remote fetch, browser control or submission endpoints."""
import json
import os
import secrets
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .documents import import_document
from .store import Problem, Store, require_object
from .bridge import Bridge, EXTENSION_ORIGIN
from .companion import Companion
from .journey import Journey
from .activity import Activity

WEB = Path(__file__).resolve().parent.parent / "web"
LIMIT = 8 * 1024 * 1024


def make_server(directory, port=8421, worker_enabled=False, worker_count=None):
    store = Store(directory)
    token = secrets.token_urlsafe(32)
    bridge = Bridge(store)
    companion = Companion(store)
    journey=Journey(store)
    activity=Activity(store)

    def workbench_settings():
        public = {**companion.settings(public=True), "ready": companion.ready(), **bridge.pairing_state()}
        guide = public['guide']
        if guide['active'] and not public['extension_paired']:
            public['guide'] = {**guide, 'step': 'pairing'}
        return public

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # Avoid logging arbitrary URLs / candidate content.
            pass

        def send(self, status, body, content_type="application/json; charset=utf-8"):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            origin = self.headers.get("Origin", "")
            if urlparse(self.path).path.startswith("/bridge/") and EXTENSION_ORIGIN.fullmatch(origin):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def check(self, write=False):
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if self.headers.get("Host") not in allowed:
                raise Problem("拒绝未知 Host", 403)
            origin = self.headers.get("Origin")
            if urlparse(self.path).path.startswith("/bridge/"):
                if not EXTENSION_ORIGIN.fullmatch(origin or ""):
                    raise Problem("只允许已配对扩展访问", 403)
                if urlparse(self.path).path != "/bridge/pair":
                    bridge.authenticate(origin, self.headers.get("X-Bridge-Token"))
                return
            if origin and origin not in {"http://" + h for h in allowed}:
                raise Problem("拒绝跨站请求", 403)
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                raise Problem("拒绝跨站请求", 403)
            if write and self.headers.get("X-Local-Token") != token:
                raise Problem("本地会话已失效，请刷新页面", 403)

        def do_OPTIONS(self):
            origin = self.headers.get("Origin", "")
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if self.headers.get("Host") not in allowed or not urlparse(self.path).path.startswith("/bridge/") or not EXTENSION_ORIGIN.fullmatch(origin):
                return self.send(403, {"error": "跨站请求不被允许"})
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Bridge-Token")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Vary", "Origin")
            self.end_headers()

        def do_GET(self):
            try:
                self.check()
                path = urlparse(self.path).path
                if path == "/api/state":
                    return self.send(200, store.state())
                if path == "/api/companion":
                    return self.send(200, workbench_settings())
                if path == "/api/session":
                    bundled = Path("/Applications/ChatGPT.app/Contents/Resources/codex")
                    return self.send(200, {"token": token, "version": "1.0.0-rc.1", "execution": "codex-worker" if worker_enabled else "manual-agent-bridge", "worker_available": bool(shutil.which("codex") or bundled.is_file()), "data_dir": str(store.directory), "project_dir": str(WEB.parent)})
                if path == "/api/health":
                    return self.send(200, {"ok": True, "version": "1.0.0-rc.1", "worker_enabled": worker_enabled})
                if path=='/api/journey':return self.send(200,journey.state())
                if path=='/api/data-export':return self.send(200,journey.export_data(),'application/json; charset=utf-8')
                if path.startswith('/api/resume-export/'):
                    from .resume_export import export_resume
                    name=path.removeprefix('/api/resume-export/')
                    version,sep,kind=name.rpartition('.')
                    if not sep:raise Problem('导出格式缺失')
                    data,mime=export_resume(store,version,kind)
                    return self.send(200,data,mime)
                if path.startswith("/api/export/"):
                    task_id = path.removeprefix("/api/export/")
                    task = store.get_task(task_id)
                    if task["status"] != "done":
                        raise Problem("任务尚未完成", 409)
                    result = task["result"]
                    questions = "\n".join(f"- {q}" for q in result.get("questions", [])) or "- 无"
                    content = (f"# 求职助手结果\n\n类型：{task['kind']}\n来源：{result['producer']}\n模式：{result['mode']}\n\n"
                               f"## 决策\n\n{result.get('decision') or result['summary']}\n\n"
                               f"## 核心结果\n\n{result.get('primary_output') or result['summary']}\n\n"
                               f"## 补充问题\n\n{questions}\n\n## 详细说明\n\n{result['markdown']}\n")
                    return self.send(200, content.encode(), "text/markdown; charset=utf-8")
                if path == "/theme.css":
                    return self.send(200, (WEB.parent / "extension" / "theme.css").read_bytes(), "text/css; charset=utf-8")
                files = {"/workspace.js": ("workspace.js", "text/javascript; charset=utf-8"), "/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"), "/style.css": ("style.css", "text/css; charset=utf-8"), "/extra.css": ("extra.css", "text/css; charset=utf-8")}
                if path not in files:
                    raise Problem("页面不存在", 404)
                filename, kind = files[path]
                return self.send(200, (WEB / filename).read_bytes(), kind)
            except Problem as e:
                self.send(e.status, {"error": str(e)})

        def do_POST(self):
            try:
                self.check(write=True)
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    raise Problem("请使用 application/json", 415)
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    raise Problem("Content-Length 无效")
                if size <= 0 or size > LIMIT:
                    raise Problem("请求体大小无效，最大 8 MB", 413)
                try:
                    value = require_object(json.loads(self.rfile.read(size)))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    raise Problem("JSON 无效")
                path = urlparse(self.path).path
                if path == '/api/resume-export-preview':
                    from .resume_restore import preview_resume
                    return self.send(200, preview_resume(store, value.get('version_id', '')))
                if path == '/api/resume-download':
                    from .resume_restore import checked_content
                    from .resume_export import export_resume
                    content = checked_content(value)
                    data, mime = export_resume(store, value.get('version_id', ''), value.get('format', ''), content)
                    return self.send(200, data, mime)
                if path in ('/api/retrospective', '/api/blessing', '/bridge/blessing'):
                    raise Problem('寄语已移到聊天，请刷新工作台或重载新版扩展', 410)
                if path.startswith("/bridge/"):
                    origin = self.headers.get("Origin")
                    if path == "/bridge/pair":
                        response = bridge.pair(origin, value)
                    elif path == "/bridge/capture":
                        response = bridge.capture(origin, value)
                    elif path == "/bridge/task":
                        response = bridge.task(origin, value)
                    elif path == "/bridge/result":
                        response = bridge.result(origin, value)
                    elif path == '/bridge/restore':
                        response=bridge.restore(origin,value)
                    elif path == "/bridge/status":
                        with store.connect() as db:
                            ready = bool(db.execute("SELECT facts FROM profile WHERE id=1").fetchone()[0].strip())
                        settings = companion.settings()
                        public = companion.settings(public=True)
                        response = {"version": "1.0.0-rc.1", "profile_ready": ready, "worker_enabled": worker_enabled, "ready": companion.ready(), "buddy_name": settings['buddy_name'], "persona": settings['persona'], "guide": public['guide']}
                    elif path == "/bridge/onboarding-complete":
                        response = companion.onboarding_action({"action": "complete"})
                    elif path == "/bridge/disconnect":
                        response = bridge.disconnect(origin)
                    elif path in ("/bridge/confirm", "/bridge/history", "/bridge/talk", "/bridge/company-save", "/bridge/company-read",'/bridge/cancel','/bridge/retry','/bridge/sync'):
                        response = bridge.companion_action(origin, value, path.rsplit('/', 1)[1])
                    else:
                        raise Problem("扩展接口不存在", 404)
                    return self.send(200, response)
                if path == "/api/extension-code":
                    return self.send(200, bridge.issue_code())
                if path == "/api/extension-revoke":
                    return self.send(200, bridge.revoke_all())
                if path == '/api/companion':
                    companion.save_settings(value)
                    return self.send(200, workbench_settings())
                if path == '/api/privacy-preview':
                    return self.send(200, companion.preview_profile())
                if path == '/api/privacy-approve':
                    companion.approve(value)
                    return self.send(200, workbench_settings())
                if path == '/api/onboarding':
                    companion.onboarding_action(value)
                    return self.send(200, workbench_settings())
                if path == '/api/talk':
                    return self.send(200, companion.send(value))
                if path == '/api/history':
                    return self.send(200, companion.history(value.get('job_id', '')))
                if path=='/api/journey-event':return self.send(200,journey.event(value))
                if path=='/api/quick-event':return self.send(200,activity.record(value))
                if path=='/api/result-viewed':return self.send(200,activity.viewed(value))
                if path=='/api/journey-remove':return self.send(200,journey.remove_event(value))
                if path=='/api/fact':return self.send(200,journey.fact(value))
                if path=='/api/fact-remove':return self.send(200,journey.remove_fact(value))
                if path=='/api/resume-compare':return self.send(200,journey.compare(value))
                if path=='/api/data-delete':
                    result=journey.erase(value);bridge.revoke_all()
                    return self.send(200,result)
                if path == '/api/company':
                    from .company import Company
                    return self.send(200, {'company':Company(store).read(value.get('job_id',''))})
                if path == '/api/resume-accept':
                    return self.send(200, companion.accept_resume(value))
                if path == '/api/resume-versions':
                    with store.connect() as db:
                        rows = [dict(r) for r in db.execute('SELECT * FROM resume_versions WHERE job_id=? ORDER BY created DESC', (value.get('job_id', ''),))]
                    return self.send(200, {'versions': rows})
                if path == '/api/task-preview':
                    from .worker import prompt_for
                    return self.send(200, {'prompt': prompt_for(store.get_task(value.get('task_id', '')), companion.settings())})
                if path == '/api/connection-test':
                    from .providers import test_connection
                    if companion.settings()['provider'] != 'api':
                        from .worker import codex_login_check
                        candidate=shutil.which('codex') or (str(Path('/Applications/ChatGPT.app/Contents/Resources/codex')) if Path('/Applications/ChatGPT.app/Contents/Resources/codex').is_file() else None)
                        ok,message=codex_login_check(candidate)
                        return self.send(200, {'ok': ok, 'message': message, 'provider':'codex', 'cli_available':bool(candidate)})
                    return self.send(200, test_connection(companion.settings()))
                handlers = {"/api/profile": store.save_profile, "/api/jobs": store.save_job,
                            "/api/tasks": store.create_task, "/api/documents": lambda v: import_document(store, v)}
                if path.startswith("/api/tasks/"):
                    parts = path.split("/")
                    if len(parts) == 5 and parts[4] in ("retry", "cancel"):
                        task_id = parts[3]
                        return self.send(200, store.retry(task_id) if parts[4] == "retry" else store.cancel(task_id))
                if path not in handlers:
                    raise Problem("接口不存在", 404)
                self.send(200, handlers[path](value))
            except Problem as e:
                self.send(e.status, {"error": str(e)})
            except Exception:
                self.send(500, {"error": "本地服务错误，请查看工程文档排查"})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    if worker_enabled:
        from .worker import CodexWorker
        stop = threading.Event()
        try:
            count = int(worker_count if worker_count is not None else os.environ.get("JOB_ASSISTANT_WORKERS", "2"))
        except ValueError:
            count = 2
        # Reserve a chat slot: long resume tasks cannot occupy every worker.
        count = max(2, min(count, 4))
        threads = []
        for index in range(count):
            worker = CodexWorker(store, WEB.parent, lane='chat' if index == 0 else 'background')
            thread = threading.Thread(target=worker.run_forever, args=(stop,), daemon=True,
                                      name=f"codex-worker-{index + 1}")
            thread.start()
            threads.append(thread)
        server.worker_stop = stop
        server.worker_thread = threads[0]
        server.worker_threads = threads
        server.worker_count = count
    return server
