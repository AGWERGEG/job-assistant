"""Fictitious test data. Never overwrites an initialized store."""
import json
from pathlib import Path

from .store import Problem, Store


def seed_demo(directory, root):
    root = Path(root)
    store = Store(directory)
    state = store.state()
    if state["profile"]["revision"] or state["jobs"] or state["documents"] or state["tasks"]:
        raise Problem("演示数据目录非空，不会覆盖现有资料")
    store.save_profile(json.loads((root / "examples/profile.json").read_text(encoding="utf-8")))
    job = store.save_job(json.loads((root / "examples/job.json").read_text(encoding="utf-8")))
    first = store.create_task({"kind": "analyze_job", "job_id": job["id"]})
    claimed = store.claim(first["id"])
    store.finish(first["id"], claimed["claim_token"], json.loads((root / "examples/result.json").read_text(encoding="utf-8")))
    return {"fixture": "虚构演示数据", "job_id": job["id"]}
