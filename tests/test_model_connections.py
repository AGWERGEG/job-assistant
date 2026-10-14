import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.companion import Companion
from app.model_connections import list_models, resolve_task_model
from app.server import make_server
from app.store import Problem, Store


class ModelConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.companion = Companion(self.store)

    def test_secret_redaction_assignment_resolution_and_endpoint_key_binding(self):
        self.companion.save_settings({"connections": [{"id": "work", "name": "虚构服务", "base_url": "https://example.invalid/v1", "api_model": "manual-model", "api_key": "synthetic-secret"}]})
        public = self.companion.settings(public=True)
        encoded = json.dumps(public)
        self.assertNotIn("synthetic-secret", encoded)
        self.assertTrue(public["connections"][0]["has_api_key"])
        current = {**self.companion.settings(), "provider": "codex", "api_model": "legacy"}
        self.assertEqual(resolve_task_model(current, "resume")["api_model"], "legacy")
        with self.assertRaises(Problem):
            self.companion.save_settings({"task_models": {"resume": {"connection_id": "work", "model": "manual-model"}}})
        self.companion.save_settings({"task_models": {"resume": {"connection_id": "work", "model": "manual-model"}}, "task_models_confirmed": True})
        resolved = resolve_task_model(self.companion.settings(), "resume")
        self.assertEqual((resolved["provider"], resolved["api_model"], resolved["api_key"]), ("api", "manual-model", "synthetic-secret"))
        self.assertEqual(resolve_task_model(current, "daily_chat")["provider"], "codex")
        broken = self.companion.settings()
        broken["connections"] = []
        with self.assertRaises(Problem):
            resolve_task_model(broken, "resume")
        broken = self.companion.settings()
        broken["connections"][0]["api_key"] = ""
        with self.assertRaises(Problem):
            resolve_task_model(broken, "resume")
        self.companion.save_settings({"connections": [{"id": "work", "name": "虚构服务", "base_url": "https://new.example.invalid/v1", "api_model": "manual-model", "api_key": ""}]})
        self.assertFalse(self.companion.settings()["connections"][0]["api_key"])
        with self.assertRaises(Problem):
            self.companion.save_settings({"task_models": {"resume": {"connection_id": "work", "model": "manual-model"}}, "task_models_confirmed": True})

    def test_public_settings_hide_a_key_even_in_another_connections_fields(self):
        self.companion.save_settings({"connections": [
            {"id": "a", "name": "服务 A", "base_url": "https://a.example.invalid/v1", "api_model": "model-a", "api_key": "fixture-key-a"},
            {"id": "b", "name": "服务 B", "base_url": "https://b.example.invalid/v1", "api_model": "model-b", "api_key": "fixture-key-b"},
        ]})
        self.companion.save_settings({"api_model": "fixture-key-b",
                                      "task_models": {"resume": {"connection_id": "a", "model": "fixture-key-b"}},
                                      "task_models_confirmed": True})
        public = self.companion.settings(public=True)
        self.assertNotIn("fixture-key-a", json.dumps(public))
        self.assertNotIn("fixture-key-b", json.dumps(public))

    def test_model_fetch_is_bounded_and_uses_saved_connection_http_route(self):
        seen = []
        class Fake(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                seen.append((self.path, self.headers.get("Authorization")))
                body = json.dumps({"data": [{"id": "fixture-a"}, {"id": "fixture-b"}, {"id": "synthetic-secret"}]}).encode()
                self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        remote = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=remote.serve_forever, daemon=True).start()
        self.addCleanup(remote.server_close); self.addCleanup(remote.shutdown)
        self.companion.save_settings({"connections": [{"id": "local", "name": "本机假服务", "base_url": f"http://127.0.0.1:{remote.server_port}/v1", "api_model": "manual", "api_key": "synthetic-secret"}]})
        self.assertEqual(list_models(self.companion.settings()["connections"][0]), ["fixture-a", "fixture-b"])
        server = make_server(self.temp.name, 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        session = {'token':server.session_token}
        req = urllib.request.Request(base + "/api/models", data=json.dumps({"connection_id": "local"}).encode(), headers={"Content-Type": "application/json", "X-Local-Token": session["token"]})
        body = urllib.request.urlopen(req).read().decode()
        self.assertIn("fixture-a", body)
        self.assertNotIn("synthetic-secret", body)
        self.assertEqual(seen[-1], ("/v1/models", "Bearer synthetic-secret"))
        unknown = urllib.request.Request(base + "/api/models", data=b'{"connection_id":"missing"}', headers={"Content-Type": "application/json", "X-Local-Token": session["token"]})
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(unknown)
        self.assertEqual(error.exception.code, 400)

    def test_reject_redirect_for_model_list(self):
        class Redirect(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                self.send_response(302); self.send_header("Location", "https://example.invalid/steal/synthetic-secret"); self.end_headers()
        remote = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
        threading.Thread(target=remote.serve_forever, daemon=True).start()
        self.addCleanup(remote.server_close); self.addCleanup(remote.shutdown)
        with self.assertRaises(Problem) as error:
            list_models({"base_url": f"http://127.0.0.1:{remote.server_port}/v1", "api_key": "synthetic-secret"})
        self.assertNotIn("synthetic-secret", str(error.exception))

    def test_parent_wall_clock_timeout_kills_slow_catalog_request(self):
        class Slow(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                time.sleep(3)
                try:
                    self.send_response(200); self.end_headers(); self.wfile.write(b'{"data":[]}')
                except OSError:
                    pass
        remote = ThreadingHTTPServer(("127.0.0.1", 0), Slow)
        threading.Thread(target=remote.serve_forever, daemon=True).start()
        self.addCleanup(remote.server_close); self.addCleanup(remote.shutdown)
        began = time.monotonic()
        with self.assertRaises(Problem) as error:
            list_models({"base_url": f"http://127.0.0.1:{remote.server_port}/v1", "api_key": "synthetic-secret"}, timeout=.2)
        self.assertLess(time.monotonic() - began, 2.5)
        self.assertNotIn("synthetic-secret", str(error.exception))


if __name__ == "__main__":
    unittest.main()
