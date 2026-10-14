#!/usr/bin/env python3
"""Explicit release allowlist excludes user state and test caches."""
import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "JobAssistant_v1.0_RC4.3.40_审阅修复_源码"
parser = argparse.ArgumentParser()
parser.add_argument("--out", required=True)
args = parser.parse_args()
allowed_files = ["README.md", "AGENTS.md", ".gitignore", "requirements.txt", "package.json", "job_assistant.py", "launch.py", "启动求职搭子.command", "启动求职搭子.bat", "启动虚构演示.command", "启动虚构演示.bat"]
allowed_dirs = ["app", "web", "tests", "scripts", "examples", "docs", ".agents", "extension"]
files = [ROOT / name for name in allowed_files]
for name in allowed_dirs:
    for p in (ROOT / name).rglob('*'):
        if p.is_symlink():
            raise SystemExit(f'不封装符号链接：{p}')
        if (any(part in ('data', 'data-demo', 'node_modules', 'auth.json') for part in p.parts)
                or p.name.startswith('.env') or p.suffix in ('.db', '.sqlite', '.sqlite3')
                or p.name.endswith(('-wal', '-shm'))):
            raise SystemExit(f'不封装资料或认证文件：{p}')
        if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc' and p.name != '.DS_Store':
            files.append(p)
if any(file.is_symlink() for file in files):
    raise SystemExit('不封装符号链接')
with zipfile.ZipFile(args.out, "w", zipfile.ZIP_DEFLATED) as archive:
    for file in sorted(files):
        archive.write(file, PACKAGE_NAME + "/" + str(file.relative_to(ROOT)))
with zipfile.ZipFile(args.out) as archive:
    assert archive.testzip() is None
    assert all(not any(part in ('data', 'data-demo', '__pycache__', 'node_modules') for part in Path(n).parts) and not any(s in n for s in ('.sqlite', '.env', 'auth.json')) for n in archive.namelist())
    print(f"Validated archive: {args.out}; files: {len(archive.namelist())}")
