import base64
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from app.documents import import_document
from app.server import make_server
from app.store import Problem, Store


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.store.save_profile({"name": "test", "facts": "真实经历", "preferences": "杭州"})
        from app.companion import Companion
        companion = Companion(self.store)
        companion.approve({'token': companion.preview_profile()['token'], 'confirmed': True})
        self.job = self.store.save_job({"title": "运营", "jd": "本科", "conversation": "请介绍经历"})

    def task(self):
        return self.store.create_task({"job_id": self.job["id"], "kind": "analyze_job"})

    def result(self):
        return {"summary": "判断", "decision": "优先尝试", "strategy": "主打真实经历", "primary_output": "直接结果", "questions": [], "markdown": "证据", "mode": "agent", "producer": "test"}

    def test_snapshot_dedup_and_stale(self):
        first = self.task()
        self.assertEqual(first["id"], self.task()["id"])
        claimed = self.store.claim(first["id"])
        self.store.save_profile({"facts": "新事实"})
        self.assertEqual(claimed["context"]["profile"]["facts"], "真实经历")
        done = self.store.finish(first["id"], claimed["claim_token"], self.result())
        self.assertTrue(done["result"]["stale_at_completion"])
        self.assertNotEqual(self.task()["id"], first["id"])

    def test_only_one_worker_can_claim(self):
        task_id = self.task()["id"]
        def claim(_):
            try:
                return self.store.claim(task_id)["status"]
            except Problem:
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(claim, [1, 2])), ["running", "conflict"])

    def test_lease_recovery_and_wrong_token(self):
        task_id = self.task()["id"]
        old = self.store.claim(task_id)
        with self.assertRaises(Problem):
            self.store.finish(task_id, "bad", self.result())
        with self.store.connect() as db:
            db.execute("UPDATE tasks SET lease_until=0 WHERE id=?", (task_id,))
        new = self.store.claim(task_id)
        with self.assertRaises(Problem):
            self.store.finish(task_id, old["claim_token"], self.result())
        self.assertEqual(self.store.finish(task_id, new["claim_token"], self.result())["status"], "done")

    def test_result_contract_and_release(self):
        task = self.store.claim(self.task()["id"])
        with self.assertRaises(Problem):
            self.store.finish(task["id"], task["claim_token"], {"summary": "缺少正文"})
        self.store.release(task["id"], task["claim_token"])
        self.assertEqual(self.store.get_task(task["id"])["status"], "queued")

    def test_fail_retry_and_cancel(self):
        task = self.store.claim(self.task()["id"])
        failed = self.store.fail(task["id"], task["claim_token"], "模型不可用", "test-worker")
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["error_text"], "模型不可用")
        retried = self.store.retry(task["id"])
        self.assertEqual(retried["status"], "queued")
        cancelled = self.store.cancel(task["id"])
        self.assertEqual(cancelled["status"], "cancelled")
        with self.assertRaises(Problem):
            self.store.retry(task["id"])

    @unittest.skipIf(os.name == "nt", "fake executable is POSIX-only")
    def test_worker_success_and_failure(self):
        from app.worker import CodexWorker
        task = self.task()
        fake = Path(self.tmp.name) / "fake-codex"
        fake.write_text('''#!/bin/sh\nout=""\nprev=""\nfor arg in "$@"; do\n  if [ "$prev" = "--output-last-message" ]; then out="$arg"; fi\n  prev="$arg"\ndone\ncat >/dev/null\nprintf '%s' '{"mode":"agent","producer":"fake","summary":"完成","decision":"尝试","strategy":"主打经历","primary_output":"结果","questions":[],"markdown":"## 依据\\n真实经历\\n## 待确认\\n无"}' > "$out"\n''')
        fake.chmod(0o755)
        worker = CodexWorker(self.store, self.tmp.name, codex_bin=str(fake), timeout=5, poll=.01)
        self.assertTrue(worker.run_one())
        self.assertEqual(self.store.get_task(task["id"])["status"], "done")
        failed_task = self.store.create_task({"job_id": self.job["id"], "kind": "tailor_resume"})
        fake.write_text("#!/bin/sh\ncat >/dev/null\necho unavailable >&2\nexit 7\n")
        fake.chmod(0o755)
        self.assertTrue(worker.run_one())
        self.assertEqual(self.store.get_task(failed_task["id"])["status"], "failed")

    @unittest.skipIf(os.name == "nt", "fake executable is POSIX-only")
    def test_worker_uses_fast_model_and_low_reasoning_by_default(self):
        from app.worker import CodexWorker
        self.task()
        fake = Path(self.tmp.name) / "fake-codex-args"
        args_file = Path(self.tmp.name) / "args.txt"
        fake.write_text(f'''#!/bin/sh
printf '%s\n' "$@" > "{args_file}"
out=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "--output-last-message" ]; then out="$arg"; fi
  prev="$arg"
done
cat >/dev/null
printf '%s' '{{"mode":"agent","producer":"fake","summary":"完成","decision":"尝试","strategy":"主打经历","primary_output":"结果","questions":[],"markdown":"依据"}}' > "$out"
''')
        fake.chmod(0o755)
        self.assertTrue(CodexWorker(self.store, self.tmp.name, codex_bin=str(fake)).run_one())
        args = args_file.read_text()
        self.assertIn("gpt-5.6-luna", args)
        self.assertIn('model_reasoning_effort="low"', args)

    def test_import_does_not_overwrite_profile_and_blocks_path(self):
        result = import_document(self.store, {"name": "../../简历.txt", "base64": base64.b64encode("导入草稿".encode()).decode()})
        self.assertEqual(result["name"], "简历.txt")
        self.assertEqual(result["extracted"], "导入草稿")
        self.assertEqual(self.store.state()["profile"]["facts"], "真实经历")
        self.assertEqual(len(list((self.store.directory / "uploads").glob("*.txt"))), 1)

    def test_docx_and_invalid_documents(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as z:
            z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>中文经历</w:t></w:r></w:p></w:body></w:document>')
        result = import_document(self.store, {"name": "resume.docx", "base64": base64.b64encode(stream.getvalue()).decode()})
        self.assertIn("中文经历", result["extracted"])
        text_result = import_document(self.store, {"name": "resume.txt", "base64": base64.b64encode('邮箱 HYPERLINK "mailto:a@b.com" a@b.com'.encode()).decode()})
        self.assertEqual(text_result["extracted"], "邮箱 a@b.com")
        with self.assertRaises(Problem):
            import_document(self.store, {"name": "bad.pdf", "base64": base64.b64encode(b"not pdf").decode()})

    def test_demo_seed_is_isolated_and_non_overwriting(self):
        from app.demo import seed_demo
        root = Path(__file__).resolve().parents[1]
        demo = Path(self.tmp.name) / "demo"
        result = seed_demo(demo, root)
        self.assertEqual(result["fixture"], "虚构演示数据")
        state = Store(demo).state()
        self.assertIn("虚构", state["profile"]["name"])
        with self.assertRaises(Problem):
            seed_demo(demo, root)

    def test_reply_needs_conversation_and_profile(self):
        job = self.store.save_job({"title": "x", "jd": "y"})
        with self.assertRaises(Problem):
            self.store.create_task({"job_id": job["id"], "kind": "suggest_reply"})
        self.store.save_profile({"facts": ""})
        with self.assertRaises(Problem):
            self.task()

    def test_later_task_inherits_current_agent_strategy(self):
        first = self.store.claim(self.task()["id"])
        self.store.finish(first["id"], first["claim_token"], self.result())
        second = self.store.create_task({"job_id": self.job["id"], "kind": "tailor_resume", "instruction": "更自然"})
        context = self.store.get_task(second["id"])["context"]
        self.assertEqual(context["prior_results"][0]["kind"], "analyze_job")
        self.assertEqual(context["prior_results"][0]["strategy"], "主打真实经历")

    def test_legacy_agent_result_does_not_pollute_strategy(self):
        first = self.store.claim(self.task()["id"])
        legacy = {"summary": "旧结果", "markdown": "旧报告", "mode": "agent", "producer": "legacy"}
        self.store.finish(first["id"], first["claim_token"], legacy)
        second = self.store.create_task({"job_id": self.job["id"], "kind": "tailor_resume"})
        self.assertEqual(self.store.get_task(second["id"])["context"]["prior_results"], [])

    def test_http_boundaries_and_export(self):
        server = make_server(self.tmp.name, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        def request(path, value=None, **headers):
            if value is not None:
                headers["Content-Type"] = "application/json"
            req = urllib.request.Request(base + path, data=json.dumps(value).encode() if value is not None else None, headers=headers)
            return urllib.request.urlopen(req)
        token = json.load(request("/api/session"))["token"]
        for headers in ({}, {"X-Local-Token": token, "Origin": "https://evil.example"}, {"X-Local-Token": token, "Host": "evil.example"}):
            with self.assertRaises(urllib.error.HTTPError) as cm:
                request("/api/profile", {"facts": "x"}, **headers)
            self.assertEqual(cm.exception.code, 403)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            request("/api/profile", [], **{"X-Local-Token": token})
        self.assertEqual(cm.exception.code, 400)
        task = self.store.claim(self.task()["id"])
        self.store.finish(task["id"], task["claim_token"], self.result())
        self.assertIn("证据", request("/api/export/"+task["id"]).read().decode())
        with self.assertRaises(urllib.error.HTTPError):
            request("/../data/assistant.sqlite3")
        self.assertIn("求职搭子", request("/").read().decode())


if __name__ == "__main__":
    unittest.main()
