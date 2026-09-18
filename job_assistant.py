#!/usr/bin/env python3
"""Run from any directory. --data-dir selects the same store as the workbench."""
import argparse
import base64
import json
import shutil
import subprocess
import sys
from pathlib import Path

from app.documents import import_document
from app.store import Problem, Store

ROOT = Path(__file__).resolve().parent


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description="求职搭子本地工具 0.5.0")
    parser.add_argument("--data-dir", default=str(ROOT / "data"))
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--port", type=int, default=8421)
    serve.add_argument("--worker", action="store_true", help="自动使用本机 codex exec 处理待办")
    serve.add_argument("--workers", type=int, default=None, help="并行 Codex worker 数量，默认 2")
    commands.add_parser("state")
    commands.add_parser("tasks")
    for name in ("profile-save", "job-save", "task-create"):
        commands.add_parser(name).add_argument("--file", required=True)
    commands.add_parser("import-resume").add_argument("--file", required=True)
    for name in ("show", "claim", "demo-run"):
        commands.add_parser(name).add_argument("task_id")
    finish = commands.add_parser("complete")
    finish.add_argument("task_id")
    finish.add_argument("--token", required=True)
    finish.add_argument("--file", required=True)
    release = commands.add_parser("release")
    release.add_argument("task_id")
    release.add_argument("--token", required=True)
    commands.add_parser("worker-once")
    commands.add_parser("doctor")
    args = parser.parse_args()
    try:
        if args.command == "serve":
            from app.server import make_server
            server = make_server(args.data_dir, args.port, args.worker, args.workers)
            mode = "Codex worker 已开启，创建任务后将自动处理。" if args.worker else "自动 worker 未开启；请在 Codex 主聊天处理待办。"
            print(f"求职搭子：http://127.0.0.1:{server.server_port}\n数据目录：{Path(args.data_dir).resolve()}\n{mode}", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                if getattr(server, "worker_stop", None):
                    server.worker_stop.set()
                server.server_close()
            return
        store = Store(args.data_dir)
        if args.command == "doctor":
            codex = shutil.which("codex") or ("/Applications/ChatGPT.app/Contents/Resources/codex" if Path("/Applications/ChatGPT.app/Contents/Resources/codex").is_file() else None)
            auth = {"ok": False, "message": "未找到 Codex CLI"}
            if codex:
                try:
                    check = subprocess.run([codex, "login", "status"], text=True, capture_output=True, timeout=15)
                    auth = {"ok": check.returncode == 0, "message": ((check.stdout or check.stderr).strip() or "状态未知")[-1000:]}
                except Exception as exc:
                    auth = {"ok": False, "message": str(exc)}
            result = {"version": "0.4.0", "python": sys.version.split()[0], "python_ok": sys.version_info >= (3, 10), "codex": codex, "codex_auth": auth, "data_dir": str(store.directory)}
        elif args.command == "state":
            result = store.state()
        elif args.command == "tasks":
            result = store.state()["tasks"]
        elif args.command == "profile-save":
            result = store.save_profile(read_json(args.file))
        elif args.command == "job-save":
            result = store.save_job(read_json(args.file))
        elif args.command == "task-create":
            result = store.create_task(read_json(args.file))
        elif args.command == "import-resume":
            path = Path(args.file)
            if path.stat().st_size > 5 * 1024 * 1024:
                raise Problem("文件超过 5 MB")
            result = import_document(store, {"name": path.name, "base64": base64.b64encode(path.read_bytes()).decode()})
        elif args.command == "show":
            result = store.get_task(args.task_id)
            from app.companion import Companion
            from app.privacy import safe_context
            result['context'] = safe_context(result['context'], Companion(store).settings())
        elif args.command == "claim":
            from app.companion import Companion
            from app.privacy import safe_context, fingerprint
            if not Companion(store).ready():
                raise Problem('请先在工作台确认脱敏档案')
            if fingerprint(store.get_task(args.task_id)['context']['profile'], Companion(store).settings()) != Companion(store).settings()['privacy_approved']:
                raise Problem('任务使用旧档案，请按当前已审核档案新建任务')
            result = store.claim(args.task_id)
            result['context'] = safe_context(result['context'], Companion(store).settings())
        elif args.command == "complete":
            result = store.finish(args.task_id, args.token, read_json(args.file))
            result.pop('context', None)
            result.pop('claim_token', None)
        elif args.command == "release":
            result = store.release(args.task_id, args.token)
        elif args.command == "worker-once":
            from app.worker import CodexWorker
            result = {"processed": CodexWorker(store, ROOT).run_one()}
        else:
            task = store.claim(args.task_id)
            # Deliberately not a match score or fabricated model opinion.
            result = store.finish(args.task_id, task["claim_token"], {
                "mode": "demo", "producer": "local-fixture-v1", "summary": "演示任务回写成功，未调用模型",
                "decision": "演示结果", "strategy": "固定占位内容，只验证工程链路。",
                "primary_output": "请创建真实任务，由 Codex worker 生成建议。", "questions": [],
                "markdown": f"这是演示占位结果，不是岗位判断。\n\n任务：{task['kind']}\n岗位：{task['context']['job']['title']}\n\n请创建新任务，由 Codex 领取并分析；本命令只验证队列、保存和工作台展示。"})
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (Problem, OSError, ValueError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
