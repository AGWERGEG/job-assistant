#!/usr/bin/env python3
"""Build the Windows x64 portable package from a previously validated runtime."""
import argparse
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "JobAssistant_v1.0_RC4.3.40_Windows便携免安装版"
ALLOWED_FILES = [
    "README.md", "AGENTS.md", ".gitignore", "requirements.txt", "job_assistant.py", "launch.py",
    "启动求职搭子.bat", "启动虚构演示.bat",
]
ALLOWED_DIRS = ["app", "web", "tests", "scripts", "examples", "docs", ".agents", "extension"]
RUNTIME_PREFIXES = ("runtime/", "packages/")


def copy_source(destination: Path) -> None:
    for name in ALLOWED_FILES:
        shutil.copy2(ROOT / name, destination / name)
    for name in ALLOWED_DIRS:
        shutil.copytree(
            ROOT / name,
            destination / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "data", "data-demo", "node_modules"),
        )


def runtime_member(name: str) -> Optional[str]:
    """Drop the old archive's top directory, regardless of its filename encoding."""
    parts = name.split("/", 1)
    if len(parts) != 2:
        return None
    relative = parts[1]
    if not relative.startswith(RUNTIME_PREFIXES):
        return None
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts:
        raise SystemExit("旧运行环境包含不安全路径")
    return relative


def extract_runtime(archive_path: Path, destination: Path) -> None:
    counts = {"runtime": 0, "packages": 0}
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            relative = runtime_member(info.filename)
            if not relative or info.is_dir():
                continue
            target = destination / Path(*PurePosixPath(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            counts[relative.split("/", 1)[0]] += 1
    required = [destination / "runtime/python.exe", destination / "runtime/python3.dll", destination / "runtime/vcruntime140.dll"]
    if not all(path.is_file() for path in required) or counts["runtime"] < 100 or counts["packages"] < 10:
        raise SystemExit("复用的 Windows 运行环境不完整")


def write_usage(destination: Path) -> None:
    text = """求职搭子 v1.0 RC4.3.40 Windows 便携免安装版

1. 请先完整解压 ZIP，不要直接在压缩包预览窗口中运行。
2. 双击“启动求职搭子.bat”，并保持黑色窗口开启。
3. Edge 会打开本地工作台；加载 extension 文件夹中的浏览器扩展。
4. 在 BOSS 侧栏点击“连接我的工作台”，工作台确认一次后自动连接，不需要复制配对码。

本包内置 64 位 Python 及 Word/PDF 文档依赖，目标电脑无需安装 Python。

注意：
- 仅支持 Windows 10/11 64 位。
- 用户资料保存在解压目录的 data 文件夹；升级时先备份 data，再把新版解压到新的独立目录。
- 发布包不包含制作者的 data、API 密钥、简历、浏览记录或扩展令牌。
- 若端口 8421 被占用，请先关闭旧版求职搭子黑色窗口。
- 此版本是便携包，不会注册系统启动协议；侧栏发现程序未运行时，仍需用户双击启动脚本。
- 如果安全软件提示，请核对 ZIP 的 SHA-256 后再放行；本包不会安装系统组件或写入注册表。
"""
    (destination / "便携版使用说明.txt").write_bytes(text.replace("\n", "\r\n").encode("utf-8"))


def forbidden(name: str) -> bool:
    parts = PurePosixPath(name).parts
    return (
        any(part in ("data", "data-demo", "__pycache__", "node_modules") for part in parts)
        or any(part in (".env", "auth.json") for part in parts)
        or PurePosixPath(name).suffix.lower() in (".sqlite", ".sqlite3", ".pyc")
    )


def write_zip(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, f"{PACKAGE_NAME}/{path.relative_to(source).as_posix()}")
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise SystemExit("ZIP 校验失败")
        if any(forbidden(name) for name in archive.namelist()):
            raise SystemExit("发布包包含不应发布的数据或缓存")
        names = set(archive.namelist())
        required = {
            f"{PACKAGE_NAME}/runtime/python.exe",
            f"{PACKAGE_NAME}/packages/docx/__init__.py",
            f"{PACKAGE_NAME}/packages/pypdf/__init__.py",
            f"{PACKAGE_NAME}/packages/reportlab/__init__.py",
            f"{PACKAGE_NAME}/启动求职搭子.bat",
            f"{PACKAGE_NAME}/extension/manifest.json",
        }
        if not required.issubset(names):
            raise SystemExit("Windows 发布包缺少运行环境、文档依赖或扩展")


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 Windows 10/11 x64 便携免安装包")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--reuse-portable", required=True, type=Path, help="已验收 Windows 便携包，用于复用 runtime 与 packages")
    args = parser.parse_args()
    source_archive = args.reuse_portable.resolve()
    if not source_archive.is_file():
        raise SystemExit(f"找不到旧 Windows 便携包：{source_archive}")
    with tempfile.TemporaryDirectory(prefix="job-assistant-windows-") as temp:
        stage = Path(temp) / PACKAGE_NAME
        stage.mkdir()
        copy_source(stage)
        extract_runtime(source_archive, stage)
        write_usage(stage)
        write_zip(stage, args.out.resolve())
    print(f"Validated Windows portable package: {args.out.resolve()}")


if __name__ == "__main__":
    main()
