#!/usr/bin/env python3
"""Friendly local launcher: worker + browser, with no hidden installation."""
import argparse
import sys
import threading
import webbrowser
import importlib.util
from pathlib import Path

from app.server import make_server
from app.store import Problem

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=str(ROOT / "data"))
    parser.add_argument("--port", type=int, default=8421)
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
    try:
        server = make_server(data_dir, args.port, not args.no_worker, args.workers)
    except OSError as exc:
        raise SystemExit(f"无法启动本地端口 {args.port}：{exc}")
    except Problem as exc:
        raise SystemExit(f"自动分析未启动：{exc}\n如需仅使用手动模式，运行 python3 launch.py --no-worker")
    url = f"http://127.0.0.1:{server.server_port}"
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
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
