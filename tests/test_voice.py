import base64
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from app.companion import Companion
from app.store import Problem, Store
from app.voice import speech, status, transcribe


class VoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.companion = Companion(self.store)
        self.captured = []
        captured = self.captured

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                captured.append((self.path, self.headers.get("Authorization"), self.headers.get("Content-Type"), body))
                self.send_response(200)
                if self.path.endswith("/audio/transcriptions"):
                    data = json.dumps({"text": "我想练习运营岗位的自我介绍。"}, ensure_ascii=False).encode()
                    self.send_header("Content-Type", "application/json")
                else:
                    data = b"synthetic-mp3"
                    self.send_header("Content-Type", "audio/mpeg")
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.companion.save_settings({
            "voice_base_url": f"http://127.0.0.1:{self.server.server_port}/v1",
            "voice_api_key": "synthetic-voice-secret",
        })

    def test_cloud_transcription_and_speech_keep_key_private_and_audio_ephemeral(self):
        settings = self.companion.settings()
        result = transcribe(settings, {"mime_type": "audio/webm", "audio_base64": base64.b64encode(b"fake-webm").decode()})
        self.assertEqual(result["source"], "cloud")
        self.assertFalse(result["audio_saved"])
        self.assertIn("自我介绍", result["text"])
        audio, mime = speech(settings, {"text": "这是 AI 合成语音。"})
        self.assertEqual(audio, b"synthetic-mp3")
        self.assertEqual(mime, "audio/mpeg")
        self.assertEqual([row[0] for row in self.captured], ["/v1/audio/transcriptions", "/v1/audio/speech"])
        self.assertTrue(all(row[1] == "Bearer synthetic-voice-secret" for row in self.captured))
        self.assertIn(b"fake-webm", self.captured[0][3])
        self.assertNotIn("synthetic-voice-secret", json.dumps(self.companion.settings(public=True)))
        self.assertNotIn("synthetic-voice-secret", json.dumps(self.store.state()))
        self.assertFalse(any(p.name.startswith("job_assistant_voice_") for p in Path(self.temp.name).rglob("*")))

    def test_cloud_failure_uses_local_fallback_without_persisting_audio(self):
        with patch("app.voice._cloud", side_effect=Problem("云端暂时不可用")), patch("app.voice._local_transcribe", return_value="本地识别文字") as local:
            result = transcribe(self.companion.settings(), {"mime_type": "audio/wav", "audio_base64": base64.b64encode(b"wave").decode()})
        self.assertEqual(result["source"], "local")
        self.assertTrue(result["fallback"])
        local.assert_called_once_with(b"wave", "wav")

    def test_missing_cloud_and_local_keeps_text_fallback_available(self):
        self.companion.save_settings({"clear_voice_api_key": True})
        with patch("app.voice._local_transcribe", side_effect=Problem("not configured")):
            with self.assertRaisesRegex(Problem, "文字输入仍可使用"):
                transcribe(self.companion.settings(), {"mime_type": "audio/webm", "audio_base64": base64.b64encode(b"voice").decode()})
        public = self.companion.settings(public=True)
        self.assertFalse(public["has_voice_api_key"])
        self.assertEqual(status(self.companion.settings())["voice_policy"], "cloud_first_local_fallback")

    def test_audio_validation_is_bounded(self):
        with self.assertRaises(Problem):
            transcribe(self.companion.settings(), {"mime_type": "application/octet-stream", "audio_base64": "eA=="})
        with self.assertRaises(Problem):
            speech(self.companion.settings(), {"text": ""})


if __name__ == "__main__":
    unittest.main()
