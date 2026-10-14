#!/usr/bin/env python3
"""Smoke-test a macOS portable ZIP with an isolated temporary profile."""
import argparse
import hashlib
import json
import os
import platform
import shlex
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import urllib.parse
import zipfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="ja-rc4340-mac-smoke-") as temporary:
        temp = Path(temporary)
        with zipfile.ZipFile(args.archive) as archive:
            if archive.testzip() is not None:
                raise SystemExit("ZIP integrity failed")
            for info in archive.infolist():
                parts = Path(info.filename).parts
                if not parts or '..' in parts or Path(info.filename).is_absolute():
                    raise SystemExit("Unsafe ZIP path")
                if any(part in {"data", "data-demo", "node_modules", "__pycache__"} for part in parts):
                    raise SystemExit("User data or cache in ZIP")
                if info.is_dir():
                    continue
                target = temp.joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("wb") as output:
                    import shutil
                    shutil.copyfileobj(source, output)
                target.chmod((info.external_attr >> 16) & 0o777 or 0o644)
        roots = list(temp.iterdir())
        if len(roots) != 1 or not roots[0].is_dir():
            raise SystemExit("Unexpected archive layout")
        root = roots[0]
        python = root / "runtime/bin/python3"
        launcher = root / "启动求职搭子.command"
        if not (python.is_file() and os.access(python, os.X_OK) and launcher.is_file()
                and os.access(launcher, os.X_OK)):
            raise SystemExit("Missing macOS launcher or runtime")
        if platform.machine() != "arm64":
            raise SystemExit("Smoke test requires an Apple Silicon Mac")
        test_home = temp / 'home'
        test_home.mkdir()
        startup_capture = temp / 'startup-url'
        browser_sink = temp / 'capture-browser'
        browser_sink.write_text('#!/bin/sh\numask 077\nprintf \'%s\' "$1" > ' + shlex.quote(str(startup_capture)) + '\n')
        browser_sink.chmod(0o700)
        environment = {
            'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'HOME': str(test_home),
            'BROWSER': str(browser_sink), 'PYTHONDONTWRITEBYTECODE': '1',
            'PYTHONUNBUFFERED': '1', 'LANG': 'en_US.UTF-8',
        }
        subprocess.run([str(python), "-c", "import docx,pypdf,reportlab,pydantic_ai; import app.dialogue_child"],
                       cwd=root, env=environment, check=True)
        demo_check = """from pathlib import Path
import tempfile
from app.demo import seed_demo
with tempfile.TemporaryDirectory() as directory:
    result = seed_demo(directory, Path.cwd())
    assert result['fixture'] == '虚构演示数据'
print('Fictional demo fixtures: OK')
"""
        subprocess.run([str(python), '-c', demo_check], cwd=root, env=environment, check=True)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        process = subprocess.Popen(
            [str(launcher), "--data-dir", str(temp / "isolated-data"),
             "--port", str(port), "--no-worker"],
            cwd=root, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise SystemExit(f"Launcher exited: {process.returncode}: {process.stdout.read()[-1000:]}")
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
                        health = json.load(response)
                    if any(health.get(key) != value for key, value in
                           {"ok": True, "version": "1.0.0-rc.4.3.40", "worker_enabled": False}.items()):
                        raise SystemExit(f"Unexpected health: {health}")
                    expected_data = temp / 'isolated-data'
                    if health.get('data_id') != hashlib.sha256(str(expected_data.resolve()).encode()).hexdigest():
                        raise SystemExit('Health data identity is not isolated')
                    if health.get('project_id') != hashlib.sha256(str(root.resolve()).encode()).hexdigest():
                        raise SystemExit('Health project identity does not match extracted package')
                    for path in ('/api/session', '/api/state', '/api/data-export'):
                        try:
                            urllib.request.urlopen(f'http://127.0.0.1:{port}' + path, timeout=1)
                            raise SystemExit('Private API allowed anonymous reads')
                        except urllib.error.HTTPError as exc:
                            if exc.code != 403:
                                raise
                    if not startup_capture.is_file():
                        time.sleep(0.1)
                        continue
                    startup = urllib.parse.urlsplit(startup_capture.read_text())
                    if startup.scheme != 'http' or startup.netloc != f'127.0.0.1:{port}' or startup.path != '/':
                        raise SystemExit('Startup browser URL is not the isolated server')
                    bootstrap = urllib.parse.parse_qs(startup.fragment).get('access', [''])[0]
                    if not bootstrap:
                        raise SystemExit('Startup URL is missing one-time authorization')
                    request = urllib.request.Request(f'http://127.0.0.1:{port}/api/session', data=b'{}',
                        headers={'Content-Type': 'application/json', 'X-Local-Token': bootstrap})
                    with urllib.request.urlopen(request, timeout=2) as response:
                        session = json.load(response)
                        cookie = response.headers.get('Set-Cookie', '')
                    if not session.get('token') or 'HttpOnly' not in cookie:
                        raise SystemExit('Missing private session authorization')
                    headers = {'X-Local-Token': session['token']}
                    with urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{port}/api/companion',
                                                headers=headers), timeout=2) as response:
                        companion = json.load(response)
                    if companion.get("ready"):
                        raise SystemExit("Fresh profile must not be ready")
                    try:
                        urllib.request.urlopen(request, timeout=1)
                        raise SystemExit('Bootstrap authorization was reusable')
                    except urllib.error.HTTPError as exc:
                        if exc.code != 403:
                            raise
                    cookie_request = urllib.request.Request(f'http://127.0.0.1:{port}/api/state?summary=1',
                                                            headers={'Cookie': cookie.split(';')[0]})
                    with urllib.request.urlopen(cookie_request, timeout=2) as response:
                        state = json.load(response)
                        etag = response.headers.get('ETag')
                    if state.get('tasks') or state.get('jobs') or not etag:
                        raise SystemExit('Fresh state is not empty or has no ETag')
                    print(json.dumps({"health": health, "python": str(python),
                        "profile_ready": companion.get("ready"), 'anonymous_private_reads': 403,
                        'bootstrap_one_time': True, 'cookie_reads': True, 'fresh_state_empty': True}, ensure_ascii=False))
                    return
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(0.1)
            raise SystemExit("Health endpoint timed out")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
