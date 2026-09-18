import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from app.providers import complete
from app.store import Problem


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.started=threading.Event();self.release=threading.Event()
        started,release=self.started,self.release
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_POST(self):
                value=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                started.set()
                try:
                    if value['model']=='headers': release.wait(5)
                    self.send_response(200)
                    self.send_header('Content-Type','text/event-stream' if value.get('stream') else 'application/json')
                    self.end_headers()
                    if value['model']=='body': self.wfile.flush();release.wait(5)
                    if value['model']=='drip':
                        for _ in range(300):
                            self.wfile.write(b' ');self.wfile.flush()
                            if release.wait(.015):break
                    elif value.get('stream'):
                        self.wfile.write(b'data: {"choices":[{"delta":{"content":"OK"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
                    else:self.wfile.write(b'{"choices":[{"message":{"content":"OK"},"finish_reason":"stop"}]}')
                except OSError: pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.settings={'base_url':f'http://127.0.0.1:{self.server.server_port}/v1','api_model':'ok'}

    def tearDown(self):
        self.release.set();self.server.shutdown();self.server.server_close()

    def test_cancel_header_body_and_stream_waits_then_next_request_runs(self):
        for model,stream in [('headers',False),('body',False),('body',True)]:
            with self.subTest(model=model,stream=stream):
                self.started.clear()
                start=time.monotonic()
                with self.assertRaisesRegex(Problem,'已取消'):
                    complete({**self.settings,'api_model':model},'synthetic',timeout=4,
                             on_delta=(lambda value:None) if stream else None,
                             cancelled=self.started.is_set)
                self.assertLess(time.monotonic()-start,1.5)
                self.assertEqual(complete(self.settings,'synthetic',timeout=2),'OK')

    def test_total_timeout_cannot_be_extended_by_dripping_bytes(self):
        start=time.monotonic()
        with self.assertRaisesRegex(Problem,'总时限'):
            complete({**self.settings,'api_model':'drip'},'synthetic',timeout=.35)
        self.assertLess(time.monotonic()-start,1.5)
        self.assertEqual(complete(self.settings,'synthetic',timeout=2),'OK')
