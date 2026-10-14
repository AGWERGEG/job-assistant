#!/usr/bin/env python3
"""Smoke-test an extracted Windows portable archive with isolated data."""
import argparse
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="ja-rc435-smoke-") as temporary:
        temp = Path(temporary)
        with zipfile.ZipFile(args.archive) as archive:
            if archive.testzip() is not None:
                raise SystemExit("ZIP integrity failed")
            archive.extractall(temp)
        roots = list(temp.iterdir())
        if len(roots) != 1 or not roots[0].is_dir():
            raise SystemExit("Unexpected archive layout")
        root = roots[0]
        python = root / "runtime" / "python.exe"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(root / "packages")
        process = subprocess.Popen(
            [str(python), "launch.py", "--data-dir", str(temp / "isolated-data"),
             "--port", "18421", "--no-worker", "--no-browser"],
            cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(50):
                if process.poll() is not None:
                    raise SystemExit(f"Launcher exited: {process.returncode}")
                try:
                    with urllib.request.urlopen("http://127.0.0.1:18421/api/health", timeout=1) as response:
                        result = json.load(response)
                    print(json.dumps(result, ensure_ascii=False))
                    return
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(0.2)
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
