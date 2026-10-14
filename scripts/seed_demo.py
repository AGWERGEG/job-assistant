#!/usr/bin/env python3
"""Create fictitious fixtures in an empty data directory only."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.demo import seed_demo

parser = argparse.ArgumentParser()
parser.add_argument("--data-dir", default=str(ROOT / "data"))
args = parser.parse_args()
import json
try:
    print(json.dumps(seed_demo(args.data_dir, ROOT), ensure_ascii=False))
except Exception as exc:
    raise SystemExit(str(exc))
