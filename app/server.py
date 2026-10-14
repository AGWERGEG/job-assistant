"""Loopback workspace API with bounded model and public research requests; no platform submissions."""
import json
import os
import secrets
import threading
import time
import hashlib
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .documents import import_document
from .store import Problem, Store, require_object
from .bridge import Bridge
from .version import VERSION, is_extension_origin
from .companion import Companion
from .journey import Journey
from .activity import Activity
from .runtime import find_codex

WEB = Path(__file__).resolve().parent.parent / "web"
LIMIT = 8 * 1024 * 1024


class LocalServer(ThreadingHTTPServer):
    def server_close(self):
        if getattr(self, 'worker_stop', None):
            self.worker_stop.set()
        super().server_close()
        lock = getattr(self, 'data_lock', None)
        if lock is not None:
            self.data_lock = None
            workers = getattr(self, 'worker_threads', [])
            def release():
                for worker in workers:
                    worker.join()
                lock.close()
            if any(worker.is_alive() for worker in workers):
                threading.Thread(target=release, daemon=True, name='workbench-lock-release').start()
            else:
                lock.close()


def make_server(directory, port=8421, worker_enabled=False, worker_count=None):
    from .server_lock import DataDirectoryLock
    lock = DataDirectoryLock(directory)
    try:
        server = _make_server(directory, port, worker_enabled, worker_count)
        server.data_lock = lock
        return server
    except BaseException:
        lock.close()
        raise


def _make_server(directory, port, worker_enabled, worker_count):
    store = Store(directory)
    token = secrets.token_urlsafe(32)
    bootstrap = secrets.token_urlsafe(32)
    bootstrap_until = time.monotonic() + 600
    session_cookie = secrets.token_urlsafe(32)
    bootstrap_lock = threading.Lock()
    version = VERSION
    bridge = Bridge(store)
    companion = Companion(store)
    journey=Journey(store)
    activity=Activity(store)
    from .company import Company
    from .company_research import CompanyResearch
    from .search_provider import research_search_provider
    class ConfiguredSearch:
        def search(self, company_name, question, *, deadline):
            return research_search_provider(companion.settings()).search(company_name, question, deadline=deadline)
    company_research = CompanyResearch(Company(store), search_provider=ConfiguredSearch())

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

        def send(self, status, body, content_type="application/json; charset=utf-8", headers=None):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            origin = self.headers.get("Origin", "")
            if self.path.split('?', 1)[0].startswith("/bridge/") and is_extension_origin(origin):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def check(self, write=False):
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if self.headers.get("Host") not in allowed:
                raise Problem("拒绝未知 Host", 403)
            origin = self.headers.get("Origin")
            try:
                path = urlparse(self.path).path
            except ValueError:
                raise Problem('请求地址无效')
            if path.startswith("/bridge/"):
                if not is_extension_origin(origin):
                    raise Problem("只允许已配对扩展访问", 403)
                if urlparse(self.path).path not in ("/bridge/pair", "/bridge/discover", "/bridge/pair-request", "/bridge/pair-status", "/bridge/challenge"):
                    bridge.authenticate(origin, self.headers.get("X-Bridge-Token"))
                return
            # The public shell can be opened or reloaded from the side panel.
            # This exception never applies to APIs, embedded pages or writes.
            shell_navigation = (
                not write and self.command == "GET" and path == "/"
                and self.headers.get("Sec-Fetch-Mode") == "navigate"
                and self.headers.get("Sec-Fetch-Dest") == "document"
            )
            if not shell_navigation and origin and origin not in {"http://" + h for h in allowed}:
                raise Problem("拒绝跨站请求", 403)
            if not shell_navigation and self.headers.get("Sec-Fetch-Site") == "cross-site":
                raise Problem("拒绝跨站请求", 403)
            offered = self.headers.get('X-Local-Token', '')
            token_ok = bool(offered) and secrets.compare_digest(offered, token)
            if path == '/api/session' and write:
                with bootstrap_lock:
                    bootstrap_ok = bool(offered) and time.monotonic() < bootstrap_until and secrets.compare_digest(offered, self.server.bootstrap_token)
                    if bootstrap_ok:
                        self.server.bootstrap_token = ''
                if not (token_ok or bootstrap_ok):
                    raise Problem('请从启动器打开工作台，再连接侧栏', 403)
                return
            cookie_ok = False
            if not write:
                try:
                    cookies = SimpleCookie(self.headers.get('Cookie', ''))
                    cookie = cookies.get('workbench_session_' + str(self.server.server_port))
                    cookie_ok = bool(cookie) and secrets.compare_digest(cookie.value, session_cookie)
                except Exception:
                    pass
            if path.startswith('/api/') and path != '/api/health' and not (token_ok or (not write and cookie_ok)):
                raise Problem('本机连接未授权，请从启动器打开工作台', 403)
            if write and not token_ok:
                raise Problem("本地会话已失效，请从启动器重新打开工作台", 403)

        def do_OPTIONS(self):
            origin = self.headers.get("Origin", "")
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if self.headers.get("Host") not in allowed or not urlparse(self.path).path.startswith("/bridge/") or not is_extension_origin(origin):
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
                    summary = parse_qs(urlparse(self.path).query).get('summary') == ['1']
                    tag = store.state_tag()[:-1] + ('.summary"' if summary else '.full"')
                    if self.headers.get('If-None-Match') == tag:
                        return self.send(304, b'', headers={'ETag': tag})
                    return self.send(200, store.state(summary=summary), headers={'ETag': tag})
                if path.startswith('/api/task-result/'):
                    task_id = unquote(path.removeprefix('/api/task-result/'))
                    if not task_id or len(task_id) > 128 or '/' in task_id or '\\' in task_id:
                        raise Problem('任务结果标识无效', 400)
                    with store.connect() as db:
                        row = db.execute('SELECT id,status,updated,result_json FROM tasks WHERE id=?', (task_id,)).fetchone()
                    if not row:
                        raise Problem('任务不存在', 404)
                    if row['status'] != 'done' or not row['result_json']:
                        raise Problem('任务结果尚未完成', 409)
                    return self.send(200, {'task_id': row['id'], 'updated': row['updated'],
                                           'result': json.loads(row['result_json'])})
                if path == '/api/job-links':
                    return self.send(200, {'links':store.list_job_links()})
                if path == "/api/companion":
                    return self.send(200, workbench_settings())
                if path == "/api/session":
                    return self.send(200, {"token": token, "version": version, "execution": "codex-worker" if worker_enabled else "manual-agent-bridge", "worker_available": bool(find_codex()), "data_dir": str(store.directory), "project_dir": str(WEB.parent)})
                if path == "/api/health":
                    return self.send(200, {"ok": True, "version": version, "worker_enabled": worker_enabled,
                                          "project_id": hashlib.sha256(str(WEB.parent.resolve()).encode()).hexdigest(),
                                          "data_id": hashlib.sha256(str(store.directory).encode()).hexdigest()})
                if path=='/api/journey':return self.send(200,journey.state())
                if path=='/api/data-export':return self.send(200,journey.export_data(),'application/json; charset=utf-8')
                if path.startswith('/api/resume-export/'):
                    from .resume_export import export_resume
                    name=path.removeprefix('/api/resume-export/')
                    resume_version,sep,kind=name.rpartition('.')
                    if not sep:raise Problem('导出格式缺失')
                    data,mime=export_resume(store,resume_version,kind)
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
                if path == "/reply-format.js":
                    return self.send(200, (WEB.parent / "extension" / "reply-format.js").read_bytes(), "text/javascript; charset=utf-8")
                files = {"/mock-interview.js": ("mock-interview.js", "text/javascript; charset=utf-8"), "/workspace.js": ("workspace.js", "text/javascript; charset=utf-8"), "/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"), "/style.css": ("style.css", "text/css; charset=utf-8"), "/extra.css": ("extra.css", "text/css; charset=utf-8")}
                if path not in files:
                    raise Problem("页面不存在", 404)
                filename, kind = files[path]
                return self.send(200, (WEB / filename).read_bytes(), kind)
            except Problem as e:
                self.send(e.status, {"error": str(e)})
            except ValueError:
                self.send(400, {"error": "请求地址或格式无效"})
            except Exception:
                self.send(500, {"error": "暂时无法读取内容，请稍后重试；本机资料已保留"})

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
                except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
                    raise Problem("JSON 无效")
                for key, item in value.items():
                    if (key in ('id', 'kind', 'scope') or key.endswith('_id')) and not isinstance(item, str):
                        raise Problem('请求中的编号或类型必须是文本')
                pending_values = [(value, 0)]
                while pending_values:
                    item, depth = pending_values.pop()
                    if depth > 32:
                        raise Problem('请求层级过深，请简化输入')
                    if isinstance(item, dict):
                        pending_values.extend((child, depth + 1) for child in item.values())
                    elif isinstance(item, list):
                        pending_values.extend((child, depth + 1) for child in item)
                path = urlparse(self.path).path
                if path == '/api/session':
                    return self.send(200, {"token": token, "version": version, "execution": "codex-worker" if worker_enabled else "manual-agent-bridge"},
                                     headers={'Set-Cookie': 'workbench_session_' + str(self.server.server_port) + '=' + session_cookie + '; HttpOnly; SameSite=Strict; Path=/'})
                if path == '/api/resume-export-preview':
                    from .resume_restore import preview_resume
                    return self.send(200, preview_resume(store, value.get('version_id', '')))
                if path in ('/api/mock-interview/export','/api/mock-interview/preview','/api/mock-interview/import','/api/mock-interview/records'):
                    from .mock_interview import MockInterview
                    interview=MockInterview(store)
                    if path.endswith('/export'): result=interview.create_package(value)
                    elif path.endswith('/preview'): result=interview.preview(value)
                    elif path.endswith('/import'): result=interview.import_result(value)
                    else: result=interview.records(value.get('job_id',''))
                    return self.send(200,result)
                if path == '/api/profile-import-draft':
                    from .profile_import import ProfileImport
                    draft = ProfileImport(store).read(value.get('id', ''))
                    return self.send(200, {**draft, 'editor': ProfileImport.editor_values(draft)})
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
                    elif path == "/bridge/discover":
                        response = bridge.discover(origin)
                    elif path == '/bridge/challenge':
                        response = bridge.server_proof(origin, value.get('nonce'))
                    elif path == "/bridge/pair-request":
                        response = bridge.request_pair(origin)
                    elif path == "/bridge/pair-status":
                        response = bridge.pair_request_status(origin, value.get("request_id", ""))
                    elif path == "/bridge/capture":
                        response = bridge.capture(origin, value)
                    elif path == "/bridge/task":
                        response = bridge.task(origin, value)
                    elif path == "/bridge/result":
                        response = bridge.result(origin, value)
                    elif path == '/bridge/restore':
                        response=bridge.restore(origin,value)
                    elif path == '/bridge/jobs':
                        response=bridge.jobs(origin,value)
                    elif path == '/bridge/select':
                        response=bridge.select(origin,value)
                    elif path == '/bridge/links':
                        response=bridge.links(origin,value)
                    elif path == '/bridge/link-context':
                        response=bridge.link_context(origin,value)
                    elif path == '/bridge/link-save':
                        response=bridge.link_save(origin,value)
                    elif path == '/bridge/link-unbind':
                        response=bridge.link_unbind(origin,value)
                    elif path == "/bridge/status":
                        with store.connect() as db:
                            ready = bool(db.execute("SELECT facts FROM profile WHERE id=1").fetchone()[0].strip())
                        settings = companion.settings()
                        public = companion.settings(public=True)
                        response = {"version": version, "capabilities": ["resume-import", "zhaopin-resume-import", "pair-confirmation", "verified-chat-links"], "profile_ready": ready, "worker_enabled": worker_enabled, "ready": companion.ready(), "readiness": public['readiness'], "buddy_name": settings['buddy_name'], "persona": settings['persona'], "guide": public['guide']}
                    elif path == "/bridge/resume-import":
                        response = bridge.resume_import(origin, value)
                    elif path == "/bridge/onboarding-complete":
                        response = companion.onboarding_action({"action": "complete"})
                    elif path == "/bridge/disconnect":
                        response = bridge.disconnect(origin)
                    elif path in ("/bridge/confirm", "/bridge/history", "/bridge/talk", "/bridge/company-save", "/bridge/company-read", "/bridge/company-bind",'/bridge/cancel','/bridge/retry','/bridge/sync'):
                        response = bridge.companion_action(origin, value, path.rsplit('/', 1)[1])
                    else:
                        raise Problem("扩展接口不存在", 404)
                    return self.send(200, response)
                if path == "/api/extension-code":
                    return self.send(200, bridge.issue_code())
                if path == "/api/pair-request-info":
                    return self.send(200, bridge.pair_request_info(value.get("request_id", "")))
                if path == "/api/pair-request-approve":
                    return self.send(200, bridge.approve_pair_request(value.get("request_id", ""), value.get("confirmed")))
                if path == "/api/extension-revoke":
                    return self.send(200, bridge.revoke_all())
                if path == '/api/companion':
                    companion.save_settings(value)
                    return self.send(200, workbench_settings())
                if path == '/api/models':
                    from .model_connections import list_models
                    connection_id = value.get('connection_id', '')
                    connection = next((c for c in companion.settings().get('connections', [])
                                       if c.get('id') == connection_id), None)
                    if not connection:
                        raise Problem('请先保存该连接，再获取模型列表')
                    return self.send(200, {'models': list_models(connection)})
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
                if path == '/api/search-test':
                    import time
                    try:
                        sources = research_search_provider(companion.settings()).search('OpenAI', '产品与业务', deadline=time.monotonic()+15)
                        ok = bool(sources)
                        return self.send(200, {'ok':ok, 'sources_count':len(sources),
                                              'message':('本次搜索取得 '+str(len(sources))+' 条与固定公司名匹配的来源；不代表每家公司都能检索成功。') if ok else '未取得相关来源；请检查搜索接入或稍后重试。'})
                    except Problem as exc:
                        return self.send(200, {'ok':False, 'sources_count':0, 'message':str(exc)})
                if path == '/api/company-research':
                    job_id = value.get('job_id','')
                    with store.connect() as db:
                        job_row = db.execute('SELECT company FROM jobs WHERE id=?', (job_id,)).fetchone()
                    if not job_row:
                        raise Problem('岗位不存在',404)
                    company_name = job_row['company']
                    return self.send(200, company_research.research(company_name, value.get('question',''), job_id=job_id, public_urls=value.get('public_urls',[]), allow_network=value.get('allow_network') is True))
                if path == '/api/company-research-confirm':
                    return self.send(200, {'company': company_research.confirm(value.get('job_id',''), value.get('preview_id',''), confirmed=value.get('confirmed') is True)})
                if path == '/api/company-research-discard':
                    return self.send(200, company_research.discard(value.get('job_id',''), value.get('preview_id','')))
                if path == '/api/history':
                    return self.send(200, companion.history(value.get('job_id', '')))
                if path=='/api/journey-event':return self.send(200,journey.event(value))
                if path=='/api/quick-event':return self.send(200,activity.record(value))
                if path=='/api/result-viewed':return self.send(200,activity.viewed(value))
                if path=='/api/journey-remove':return self.send(200,journey.remove_event(value))
                if path=='/api/fact':return self.send(200,journey.fact(value))
                if path=='/api/chat-fact-draft':return self.send(200,journey.chat_fact_draft(value))
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
                        candidate=find_codex()
                        ok,message=codex_login_check(candidate)
                        return self.send(200, {'ok': ok, 'message': message, 'provider':'codex', 'cli_available':bool(candidate)})
                    result=test_connection(companion.settings())
                    companion.save_settings({'stream':result.get('stream_supported',False),
                                             'stream_verified':result.get('stream_supported',False)})
                    return self.send(200, result)
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
            except (TypeError, ValueError):
                self.send(400, {"error": "请求格式无效，请核对输入后重试"})
            except Exception:
                self.send(500, {"error": "暂时无法处理，请稍后重试；本机资料已保留"})

    server = LocalServer(("127.0.0.1", port), Handler)
    server.session_token = token
    server.bootstrap_token = bootstrap
    server.startup_url = f'http://127.0.0.1:{server.server_port}/#access={bootstrap}'
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
