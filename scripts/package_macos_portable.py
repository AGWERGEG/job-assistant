#!/usr/bin/env python3
"""Build a self-contained macOS Apple Silicon package without user data."""
import argparse
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "JobAssistant_v1.0_RC4.3.40_审阅修复_macOS_Apple芯片便携免安装版"

ALLOWED_FILES = [
    "README.md", "requirements.txt", "job_assistant.py", "launch.py",
    "启动求职搭子.command", "启动虚构演示.command",
    "examples/profile.json", "examples/job.json", "examples/result.json",
]
ALLOWED_DIRS = ["app", "web", "extension"]
USER_DOCS = ['docs/PORTABLE_MACOS.md', 'docs/PRIVACY.md', 'docs/LICENSE_NOTICES.md',
             'docs/KNOWN_LIMITATIONS.md']
RUNTIME_LIBRARY = Path("lib/python3.12")


def check_paths(paths) -> None:
    for path in paths:
        if path.is_symlink():
            raise SystemExit(f"不封装符号链接：{path}")
        if (any(part in ('data', 'data-demo', 'node_modules', 'auth.json') for part in path.parts)
                or path.name.startswith('.env')
                or path.suffix in ('.db', '.sqlite', '.sqlite3')
                or path.name.endswith(('-wal', '-shm'))):
            raise SystemExit(f"不封装资料或认证文件：{path}")


def copy_source(destination: Path) -> None:
    check_paths([ROOT / name for name in ALLOWED_FILES + USER_DOCS])
    for name in ALLOWED_DIRS:
        check_paths((ROOT / name).rglob('*'))
    for name in ALLOWED_FILES:
        (destination / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, destination / name)
    for name in ALLOWED_DIRS:
        shutil.copytree(
            ROOT / name,
            destination / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
        )
    (destination / 'docs').mkdir()
    for name in USER_DOCS:
        shutil.copy2(ROOT / name, destination / name)


def copy_runtime(runtime: Path, destination: Path) -> None:
    python_bin = runtime / "bin/python3.12"
    python_library = runtime / RUNTIME_LIBRARY
    dylib = runtime / "lib/libpython3.12.dylib"
    if not (python_bin.is_file() and python_library.is_dir() and dylib.is_file()):
        raise SystemExit("运行时不完整：需要 Python 3.12 的 bin、libpython 和标准库。")

    (destination / "bin").mkdir(parents=True)
    (destination / "lib").mkdir(parents=True)
    shutil.copy2(python_bin, destination / "bin/python3.12")
    (destination / "bin/python3").symlink_to("python3.12")
    (destination / "bin/python").symlink_to("python3.12")
    shutil.copy2(dylib, destination / "lib/libpython3.12.dylib")
    shutil.copytree(
        python_library,
        destination / RUNTIME_LIBRARY,
        ignore=shutil.ignore_patterns("site-packages", "__pycache__", "*.pyc"),
    )


def install_dependencies(build_python: Path, runtime_destination: Path, wheels: Path) -> None:
    subprocess.run(
        [
            str(build_python), "-m", "pip", "install", "--no-index", f"--find-links={wheels}",
            "--target", str(runtime_destination / RUNTIME_LIBRARY / "site-packages"),
            "-r", str(ROOT / "requirements.txt"),
        ],
        check=True,
    )


def write_zip(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(source.rglob("*")):
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            if path.name == '.DS_Store':
                continue
            if path.is_file() or path.is_symlink():
                archive.write(path, f"{PACKAGE_NAME}/{path.relative_to(source)}")
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise SystemExit("ZIP 校验失败")
        def forbidden(name: str) -> bool:
            parts = Path(name).parts
            return (
                "data" in parts
                or "data-demo" in parts
                or "__pycache__" in parts
                or "node_modules" in parts
                or ".env" in parts
                or "auth.json" in parts
                or Path(name).name.startswith('.env')
                or Path(name).name.endswith(('-wal', '-shm'))
                or Path(name).name == '.DS_Store'
                or Path(name).suffix in (".db", ".sqlite", ".sqlite3", ".pyc")
            )

        if any(forbidden(name) for name in archive.namelist()):
            raise SystemExit("发布包包含不应发布的数据或缓存")


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 macOS Apple 芯片便携免安装包")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--runtime", type=Path, help="显式指定已核对来源/版本/许可的 Python 3.12 运行时")
    parser.add_argument("--wheels", type=Path, help="已下载的 macOS arm64 Python 3.12 依赖 wheels 目录")
    parser.add_argument("--reuse-runtime-tree", type=Path, help="复用已验收便携包的 runtime 目录；提供时不重新安装 wheels")
    args = parser.parse_args()
    if not args.runtime and not args.reuse_runtime_tree:
        raise SystemExit('请显式指定 --runtime 或 --reuse-runtime-tree；不默认使用 Codex 私有缓存')
    runtime = args.runtime.resolve() if args.runtime else None
    build_python = runtime / "bin/python3" if runtime else None
    if runtime and not build_python.is_file():
        raise SystemExit(f"找不到构建 Python：{build_python}")

    with tempfile.TemporaryDirectory(prefix="job-assistant-macos-") as temp:
        stage_root = Path(temp) / PACKAGE_NAME
        stage_root.mkdir()
        copy_source(stage_root)
        for launcher in stage_root.glob('*.command'):
            launcher.chmod(0o755)
        if args.reuse_runtime_tree:
            check_paths([args.reuse_runtime_tree])
            check_paths(args.reuse_runtime_tree.rglob('*'))
            shutil.copytree(args.reuse_runtime_tree.resolve(), stage_root / "runtime",
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
        else:
            if not args.wheels:
                raise SystemExit("未提供 --reuse-runtime-tree 时必须提供 --wheels")
            copy_runtime(runtime, stage_root / "runtime")
            install_dependencies(build_python, stage_root / "runtime", args.wheels.resolve())
        write_zip(stage_root, args.out.resolve())
    print(f"Validated macOS portable package: {args.out.resolve()}")


if __name__ == "__main__":
    main()
