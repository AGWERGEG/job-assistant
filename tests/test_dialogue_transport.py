"""Production child transport checks with a local synthetic model endpoint."""

import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.dialogue import DialogueSession, run_process
from app.store import Problem
import tempfile
from app.store import Store
from app.companion import Companion

class Sandbox:
    def __init__(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(self.temp.name)
        self.store.save_profile({'name':'虚构求职者甲','facts':'虚构求职者甲 电话13812345678。负责客户沟通。'})
        self.companion=Companion(self.store)
        self.companion.approve({'token':self.companion.preview_profile()['token'],'confirmed':True})
    def begin(self,text,rid):
        task=self.companion.send({'job_id':'','text':text,'request_id':rid})['task']
        return self.store.claim(task['id'])
    def close(self): self.temp.cleanup()
    def cancel(self,task): return self.store.cancel(task['id'])


class SlowModel(BaseHTTPRequestHandler):
    requests = None

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        type(self).requests.append(body)
        time.sleep(2)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"choices":[{"message":{"content":"late"}}]}')
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *args):
        pass


class DialogueTransportTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = Sandbox()  # Fresh fictional profile and temporary database.
        SlowModel.requests = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), SlowModel)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.settings = {"base_url": f"http://127.0.0.1:{self.server.server_port}/v1",
                         "api_model": "fictional", "api_key": "sk-local-fictional-test"}

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.sandbox.close()

    def test_total_timeout_and_sanitized_outbound(self):
        task = self.sandbox.begin("请聊聊，电话13812345678", "production-timeout")
        session = DialogueSession(self.sandbox.store, task)
        started = time.monotonic()
        with self.assertRaisesRegex(Problem, "总时限"):
            run_process(self.settings, task=task, sandbox=session, timeout=.8)
        self.assertLess(time.monotonic() - started, 1.8)
        self.assertTrue(SlowModel.requests)
        outbound = b"\n".join(SlowModel.requests).decode("utf-8")
        self.assertNotIn("13812345678", outbound)
        self.assertNotIn("虚构求职者甲", outbound)
        self.assertEqual(self.sandbox.store.get_task(task["id"])["status"], "running")

    def test_cancel_prevents_late_result(self):
        task = self.sandbox.begin("先聊聊", "production-cancel")
        session = DialogueSession(self.sandbox.store, task)

        def cancelled():
            if SlowModel.requests and self.sandbox.store.get_task(task["id"])["status"] == "running":
                self.sandbox.cancel(task)
            return self.sandbox.store.get_task(task["id"])["status"] == "cancelled"

        with self.assertRaisesRegex(Problem, "取消"):
            run_process(self.settings, task=task, sandbox=session, timeout=5,
                        cancelled=cancelled)
        time.sleep(.2)
        saved = self.sandbox.store.get_task(task["id"])
        self.assertEqual(saved["status"], "cancelled")
        self.assertFalse(saved.get("result"))


if __name__ == "__main__":
    unittest.main()
