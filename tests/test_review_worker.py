import json
import os
import sqlite3
import subprocess
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.companion import Companion
from app import runtime
from app.store import Store
from app.worker import CodexWorker, codex_environment


REPORT = {
    "mode": "agent", "producer": "fake", "summary": "虚构摘要", "decision": "优先了解",
    "strategy": "突出已确认的虚构经历", "primary_output": "可核对的虚构建议",
    "questions": ["虚构问题？"], "markdown": "虚构依据",
}


class ReviewWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ja_review_worker_")
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.companion = Companion(self.store)
        self.store.save_profile({"name": "虚构候选人", "facts": "虚构经历：参与校园活动。"})
        self.companion.approve({"token": self.companion.preview_profile()["token"], "confirmed": True})
        self.job = self.store.save_job({"title": "虚构运营", "company": "虚构公司",
                                        "jd": "负责虚构活动运营与用户反馈。"})

    def add_task(self, instruction, kind="analyze_job"):
        return self.store.create_task({"kind": kind, "job_id": self.job["id"],
                                       "instruction": instruction, "request_id": "req-" + instruction})

    def make_worker(self, lane="background"):
        worker = CodexWorker(self.store, self.temp.name, codex_bin="/bin/true", timeout=3, poll=0.01,
                             lane=lane)
        worker.codex_bin = "/bin/true"
        return worker

    @staticmethod
    def write_report(command, result=REPORT):
        target = command[command.index("--output-last-message") + 1]
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False)
        return SimpleNamespace(returncode=0, stderr="")

    def wait_until(self, predicate, message):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        self.fail(message)

    def run_thread_and_finish_next(self, failure_mode):
        first = self.add_task("first-trigger-" + failure_mode)
        worker = self.make_worker()
        stop = threading.Event()
        first_called = threading.Event()
        calls = []

        def fake_codex(command, prompt, work, timeout, cancelled):
            calls.append(prompt)
            if len(calls) == 1:
                first_called.set()
                if failure_mode == "cancel-timeout":
                    self.store.cancel(first["id"])
                raise subprocess.TimeoutExpired(command, timeout)
            return self.write_report(command)

        original_fail = Store.fail

        def fail_with_busy_db(store, task_id, token, message, worker_id=""):
            if failure_mode == "busy-fail" and task_id == first["id"]:
                raise sqlite3.OperationalError("database is locked")
            return original_fail(store, task_id, token, message, worker_id)

        thread = threading.Thread(target=worker.run_forever, args=(stop,), daemon=True)
        active_key = (str(self.store.db), first["id"])
        with patch("app.worker.run_codex", side_effect=fake_codex), patch.object(Store, "fail", fail_with_busy_db):
            try:
                thread.start()
                self.assertTrue(first_called.wait(2), "first fake Codex invocation did not start")
                self.wait_until(lambda: active_key not in runtime.active,
                                "active lease marker was not cleared after the first failure")
                first_state = self.store.get_task(first["id"])
                if failure_mode == "cancel-timeout":
                    self.assertEqual(first_state["status"], "cancelled")
                else:
                    self.assertEqual(first_state["status"], "running")

                second = self.add_task("second-follow-up-" + failure_mode)
                self.wait_until(lambda: self.store.get_task(second["id"])["status"] == "done",
                                "worker thread did not process the next task")
                self.assertTrue(thread.is_alive(), "worker thread exited after a transient task error")
                self.assertEqual(self.store.get_task(second["id"])["result"]["summary"], "虚构摘要")
                with runtime.lock:
                    self.assertNotIn((str(self.store.db), first["id"]), runtime.active)
                    self.assertNotIn((str(self.store.db), second["id"]), runtime.active)
            finally:
                stop.set()
                thread.join(timeout=2)
        self.assertFalse(thread.is_alive(), "worker did not stop after its stop event")

    def test_cancel_racing_timeout_does_not_kill_worker_or_leak_active_marker(self):
        self.run_thread_and_finish_next("cancel-timeout")

    def test_busy_database_while_recording_failure_does_not_kill_worker(self):
        self.run_thread_and_finish_next("busy-fail")

    def test_transient_queue_exception_recovers_and_processes_task(self):
        task = self.add_task("recover-after-queue-error")
        worker = self.make_worker()
        original_queued = self.store.queued_tasks
        queue_calls = [0]

        def queued_with_one_error(lane=None):
            queue_calls[0] += 1
            if queue_calls[0] == 1:
                raise sqlite3.OperationalError("temporary queue lock")
            return original_queued(lane)

        stop = threading.Event()
        thread = threading.Thread(target=worker.run_forever, args=(stop,), daemon=True)
        with patch.object(self.store, "queued_tasks", side_effect=queued_with_one_error), \
                patch("app.worker.run_codex", side_effect=lambda command, *args: self.write_report(command)):
            try:
                thread.start()
                self.wait_until(lambda: self.store.get_task(task["id"])["status"] == "done",
                                "worker did not recover from one queue exception")
                self.assertGreaterEqual(queue_calls[0], 2)
                self.assertTrue(thread.is_alive())
                with runtime.lock:
                    self.assertNotIn((str(self.store.db), task["id"]), runtime.active)
            finally:
                stop.set()
                thread.join(timeout=2)
        self.assertFalse(thread.is_alive())

    def test_report_normalization_accepts_format_drift_but_rejects_missing_or_wrong_types(self):
        self.companion.save_settings({"provider": "api", "api_model": "fake-model",
                                      "base_url": "http://127.0.0.1:9/v1", "api_key": "fake-key"})
        variants = {
            "three questions and long decision": {
                **REPORT, "questions": ["问题一？", "问题二？", "问题三？"], "decision": "建议" * 260,
            },
            "preface and fenced json": "说明如下：\n```json\n" + json.dumps(REPORT, ensure_ascii=False) + "\n```",
            "missing summary": {key: value for key, value in REPORT.items() if key != "summary"},
            "wrong field type": {**REPORT, "decision": ["不是字符串"]},
        }
        results = {}
        for index, (label, value) in enumerate(variants.items()):
            task = self.add_task("format-" + str(index))
            raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            with patch("app.worker.api_complete", return_value=raw):
                self.assertTrue(self.make_worker().run_one())
            results[label] = self.store.get_task(task["id"])

        normalized = results["three questions and long decision"]
        self.assertEqual(normalized["status"], "done")
        self.assertEqual(len(normalized["result"]["questions"]), 2)
        self.assertEqual(len(normalized["result"]["decision"]), 500)
        prefaced = results["preface and fenced json"]
        self.assertEqual(prefaced["status"], "done")
        self.assertEqual(prefaced["result"]["summary"], REPORT["summary"])
        self.assertEqual(results["missing summary"]["status"], "failed")
        self.assertEqual(results["wrong field type"]["status"], "failed")

    def test_final_output_redacts_configured_keys_token_patterns_and_contacts(self):
        self.companion.save_settings({
            "provider": "api", "api_model": "fake-model", "base_url": "http://127.0.0.1:9/v1",
            "api_key": "configured-openai-secret", "search_api_key": "configured-tavily-secret",
            "connections": [{"id": "synthetic", "name": "虚构连接", "base_url": "https://example.invalid/v1",
                            "api_model": "fake-model", "api_key": "configured-connection-secret"}],
        })
        task = self.add_task("protect-fake-output")
        tokens = ("configured-openai-secret", "configured-tavily-secret", "configured-connection-secret",
                  "sk-review-abcd123456", "tvly-review-efgh123456",
                  "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.synthetic-signature")
        output = {**REPORT, "primary_output": " ".join(tokens) + " 联系电话13812345678 邮箱test@example.com"}
        with patch("app.worker.api_complete", return_value=json.dumps(output, ensure_ascii=False)):
            self.make_worker().run_one()
        result = self.store.get_task(task["id"])
        self.assertEqual(result["status"], "done")
        serialized = json.dumps(result["result"], ensure_ascii=False)
        for secret in (*tokens, "13812345678", "test@example.com"):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, serialized)

    def test_codex_environment_only_contains_allowlisted_values(self):
        environment = {
            "PATH": "/synthetic/bin", "HOME": "/synthetic/home", "LANG": "zh_CN.UTF-8",
            "OPENAI_API_KEY": "fake-openai-env-secret", "TAVILY_API_KEY": "fake-tavily-env-secret",
            "AWS_SECRET_ACCESS_KEY": "fake-cloud-secret", "UNRELATED_SECRET": "fake-other-secret",
        }
        with patch.dict(os.environ, environment, clear=True):
            actual = codex_environment()
        self.assertEqual(actual["PATH"], "/synthetic/bin")
        self.assertEqual(actual["HOME"], "/synthetic/home")
        self.assertEqual(actual["JOB_ASSISTANT_WORKER"], "1")
        for key in ("OPENAI_API_KEY", "TAVILY_API_KEY", "AWS_SECRET_ACCESS_KEY", "UNRELATED_SECRET"):
            self.assertNotIn(key, actual)

    def test_codex_cli_arguments_disable_tools_and_ignore_user_configuration(self):
        task = self.add_task("tool-free-fixture")
        calls = []

        def fake_codex(command, prompt, work, timeout, cancelled):
            calls.append((list(command), prompt))
            return self.write_report(command)

        with patch("app.worker.run_codex", side_effect=fake_codex):
            self.make_worker().run_one()
        command, prompt = calls[0]
        options = {(command[index], command[index + 1]) for index in range(len(command) - 1)}
        self.assertIn(("--disable", "shell_tool"), options)
        for feature in ("view_image", "apps", "multi_agent", "plugins", "browser_use", "browser_use_external", "hooks"):
            self.assertIn(("--disable", feature), options)
        for config in ('web_search="disabled"', "mcp_servers={}"):
            self.assertIn(config, command)
        self.assertIn("--ignore-user-config", command)
        self.assertIn("--sandbox", command)
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
        self.assertIn("tool-free-fixture", prompt)
        self.assertEqual(self.store.get_task(task["id"])["status"], "done")


if __name__ == "__main__":
    unittest.main()
