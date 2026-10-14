#!/usr/bin/env python3
"""Friendly local launcher: worker + browser, with no hidden installation."""
import argparse
import errno
import json
import hashlib
import sys
import threading
import webbrowser
import importlib.util
import urllib.request
from pathlib import Path

from app.server import make_server
from app.store import Problem

ROOT = Path(__file__).resolve().parent


def local_session(port):
    """Read only local server identity fields; never log or retain its token."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.7) as response:
            details = json.loads(response.read(8192))
        if isinstance(details, dict) and details.get('project_id') and details.get('data_id'):
            return {key: details.get(key) for key in ('version', 'project_id', 'data_id')}
    except (OSError, ValueError, KeyError, AttributeError, TypeError):
        pass
    return None


def same_profile(running, data_dir):
    return running and (running.get('data_id') == hashlib.sha256(str(Path(data_dir).resolve()).encode()).hexdigest()
                        or (running.get('data_dir') and Path(running['data_dir']).resolve() == Path(data_dir).resolve()))


def same_installation(running):
    return (running.get('project_id') == hashlib.sha256(str(ROOT).encode()).hexdigest()
            or (running.get('project_dir') and Path(running['project_dir']).resolve() == ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=str(ROOT / "data"))
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--no-worker", action="store_true")
    parser.add_argument("--workers", type=int, default=None, help="并行 Codex worker 数量，默认 2")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--demo", action="store_true", help="使用独立的虚构演示数据")
    args = parser.parse_args()
    if sys.version_info < (3, 10):
        raise SystemExit("需要 Python 3.10 或更高版本。")
    missing=[package for module,package in (('pypdf','pypdf'),('docx','python-docx'),('reportlab','reportlab'))
             if importlib.util.find_spec(module) is None]
    print(f"当前 Python：{sys.executable}")
    if missing:
        print("文档能力依赖缺失：" + "、".join(missing) + "。服务仍可启动，但相应 PDF 导入 / Word、PDF 导出不可用。")
        print(f'请使用同一解释器安装依赖："{sys.executable}" -m pip install -r requirements.txt')
    data_dir = str(ROOT / "data-demo") if args.demo and args.data_dir == str(ROOT / "data") else args.data_dir
    if args.demo:
        from app.demo import seed_demo
        try:
            seed_demo(data_dir, ROOT)
        except Problem as exc:
            if "非空" not in str(exc):
                raise SystemExit(str(exc))
    expected_version = json.loads((ROOT / "extension/manifest.json").read_text())["version_name"]
    server = None
    ports = (args.port,) if args.port is not None else range(8421, 8431)
    # Inspect all discovery ports before binding: the default port may be free
    # while this profile is already in use by a workbench on another port.
    for port in ports:
        running = local_session(port)
        if same_profile(running, data_dir):
            if running['version'] == expected_version and same_installation(running):
                print(f'这份工作台已在 http://127.0.0.1:{port} 运行；无需再启动。')
                return
            raise SystemExit('数据目录正被另一工作台使用。请先停止旧工作台，再启动新版；不要让两个版本同时写同一份资料。')
    for port in ports:
        try:
            server = make_server(data_dir, port, not args.no_worker, args.workers)
            break
        except OSError as exc:
            if exc.errno == errno.EADDRINUSE:
                running = local_session(port)
                if same_profile(running, data_dir):
                    if running["version"] == expected_version and same_installation(running):
                        print(f"这份工作台已在 http://127.0.0.1:{port} 运行；无需再启动。")
                        return
                    raise SystemExit(f"数据目录正被端口 {port} 上的另一工作台使用。请先停止旧工作台，再启动这份新版；不要让两个版本同时写同一份资料。")
            if args.port is None and exc.errno == errno.EADDRINUSE:
                continue
            raise SystemExit(f"无法启动本地端口 {port}：{exc}")
        except Problem as exc:
            if exc.status == 409:
                raise SystemExit(str(exc))
            raise SystemExit(f"自动分析未启动：{exc}\n如需仅使用手动模式，运行 python3 launch.py --no-worker")
    if server is None:
        raise SystemExit("本地端口 8421—8430 均已占用。请关闭不再使用的工作台，或用 --port 指定空闲端口。")
    if args.port is None and server.server_port != 8421:
        print(f"默认端口 8421 已被占用；本版工作台改用 {server.server_port}，已有服务保持运行。")
    url = f"http://127.0.0.1:{server.server_port}"
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(server.startup_url)).start()
    print(f"求职搭子已启动：{url}")
    if args.demo:
        print("当前为虚构演示数据，不是个人资料。")
    print("自动分析：" + ("关闭" if args.no_worker else "开启（使用工作台配置的 Codex 或兼容 API）"))
    print("按 Ctrl+C 停止。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if getattr(server, "worker_stop", None):
            server.worker_stop.set()
        server.server_close()


if __name__ == "__main__":
    main()
