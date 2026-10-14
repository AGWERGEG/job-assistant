import json
import threading
import time
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from app.providers import complete
from app.store import Problem


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.started=threading.Event();self.release=threading.Event()
        self.requests=[]
        started,release,requests=self.started,self.release,self.requests
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_POST(self):
                value=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append(value)
                started.set()
                try:
                    if value['model']=='disconnect_headers':
                        self.close_connection=True
                        return
                    if value['model']=='headers': release.wait(5)
                    self.send_response(200)
                    self.send_header('Content-Type','text/event-stream' if value.get('stream') else 'application/json')
                    if value['model']=='incomplete_body': self.send_header('Content-Length','1024')
                    self.end_headers()
                    if value['model']=='body': self.wfile.flush();release.wait(5)
                    if value['model']=='drip':
                        for _ in range(300):
                            self.wfile.write(b' ');self.wfile.flush()
                            if release.wait(.015):break
                    elif value['model']=='incomplete_body':
                        self.wfile.write(b'{"choices":[')
                        self.close_connection=True
                    elif value['model']=='bad_format':
                        self.wfile.write(b'{"choices":[{"message":{}}]}')
                    elif value['model'] in ('structured_reasoning_sse','reasoning_oversize','content_oversize','legacy_sse','multiline_sse','finish_length','finish_content_filter') and value.get('stream'):
                        model=value['model']
                        if model == 'structured_reasoning_sse':
                            for _ in range(45):
                                self.wfile.write(('data: '+json.dumps({'choices':[{'delta':{'reasoning_content':'r'*30000},'finish_reason':None}]})+'\n\n').encode())
                            self.wfile.write(b'data: {"choices":[{"delta":{"content":"{\\"ok\\":true}"},"finish_reason":"stop"}]}\n\n')
                            self.wfile.write(b'data: [DONE]\n\n')
                        elif model == 'reasoning_oversize':
                            for _ in range(430):
                                self.wfile.write(('data: '+json.dumps({'choices':[{'delta':{'reasoning_content':'r'*20000},'finish_reason':None}]})+'\n\n').encode())
                            self.wfile.write(b'data: [DONE]\n\n')
                        elif model == 'content_oversize':
                            for _ in range(220):
                                self.wfile.write(('data: '+json.dumps({'choices':[{'delta':{'content':'x'*20000},'finish_reason':None}]})+'\n\n').encode())
                            self.wfile.write(b'data: [DONE]\n\n')
                        elif model == 'multiline_sse':
                            event=json.dumps({'choices':[{'delta':{'content':'{\"ok\":true}'},'finish_reason':'stop'}]},indent=1)
                            self.wfile.write((''.join('data: '+line+'\n' for line in event.splitlines())+'\n').encode())
                            self.wfile.write(b'data: [DONE]\n\n')
                        elif model == 'legacy_sse':
                            self.wfile.write(b'data: {"choices":[{"delta":{"content":"{\\"ok\\":true}"},"finish_reason":"stop"}]}\n\n')
                            self.wfile.write(b'data: [DONE]\n\n')
                        else:
                            reason='length' if model == 'finish_length' else 'content_filter'
                            self.wfile.write(('data: '+json.dumps({'choices':[{'delta':{'content':'{\"ok\":'},'finish_reason':reason}]})+'\n\n').encode())
                            self.wfile.write(b'data: [DONE]\n\n')
                    elif value['model'] in ('structured_sse','incomplete_sse') and value.get('stream'):
                        self.wfile.write(b'data: {"choices":[{"delta":{"content":"{\\"ok\\":"},"finish_reason":null}]}\n\n')
                        self.wfile.write(b'data: {"choices":[{"delta":{"content":"true}"},"finish_reason":"stop"}]}\n\n')
                        if value['model']=='structured_sse': self.wfile.write(b'data: [DONE]\n\n')
                    elif value.get('stream'):
                        self.wfile.write(b'data: {"choices":[{"delta":{"content":"OK"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
                    else:self.wfile.write(b'{"choices":[{"message":{"content":"OK"},"finish_reason":"stop"}],"usage":{"prompt_tokens":12,"completion_tokens":3,"total_tokens":15}}')
                except OSError: pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.settings={'base_url':f'http://127.0.0.1:{self.server.server_port}/v1','api_model':'ok'}

    def tearDown(self):
        self.release.set();self.server.shutdown();self.server.server_close()

    def test_child_process_environment_forces_utf8(self):
        class FakeProc:
            stdin=None; stdout=None
            def poll(self): return 0
            def terminate(self): pass
            def wait(self,timeout=None): pass
        with patch('app.providers.subprocess.Popen', return_value=FakeProc()) as popen:
            # The fake process cannot complete transport; inspect launch contract only.
            try: complete(self.settings,'synthetic',timeout=.01)
            except Exception: pass
            env=popen.call_args.kwargs['env']
            self.assertEqual(env['PYTHONUTF8'],'1')
            self.assertEqual(env['PYTHONIOENCODING'],'utf-8')

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

    def test_usage_is_returned_to_parent_without_changing_text_contract(self):
        usage={}
        self.assertEqual(complete(self.settings,'synthetic',timeout=2,on_usage=usage.update),'OK')
        self.assertEqual(usage,{'prompt_tokens':12,'completion_tokens':3,'total_tokens':15})

    def test_structured_response_uses_sse_without_delta_callback(self):
        settings={**self.settings,'api_model':'structured_sse','stream':True,'stream_verified':True}
        self.assertEqual(complete(settings,'synthetic',structured=True,timeout=2),'{"ok":true}')
        self.assertTrue(self.requests[-1]['stream'])
        self.assertEqual(self.requests[-1]['response_format'],{'type':'json_object'})

    def test_structured_sse_does_not_publish_json_fragments(self):
        fragments=[]
        settings={**self.settings,'api_model':'structured_sse','stream':True,'stream_verified':True}
        self.assertEqual(complete(settings,'synthetic',structured=True,timeout=2,on_delta=fragments.append),'{"ok":true}')
        self.assertEqual(fragments,[])

    def test_structured_sse_requires_terminal_done_event(self):
        settings={**self.settings,'api_model':'incomplete_sse','stream':True,'stream_verified':True}
        with self.assertRaisesRegex(Problem,'流式.*提前结束|未收到完整回复'):
            complete(settings,'synthetic',structured=True,timeout=2)

    def test_nonstream_body_interruption_has_actionable_error(self):
        settings={**self.settings,'api_model':'incomplete_body','stream':False}
        with self.assertRaisesRegex(Problem,'连接.*中断|响应.*不完整|未收到完整回复'):
            complete(settings,'synthetic',structured=True,timeout=2)

    def test_header_disconnect_has_actionable_error(self):
        settings={**self.settings,'api_model':'disconnect_headers','stream':False}
        with self.assertRaisesRegex(Problem,'连接.*中断|连接失败'):
            complete(settings,'synthetic',structured=True,timeout=2)

    def test_nonstream_bad_format_has_clear_error(self):
        settings={**self.settings,'api_model':'bad_format','stream':False}
        with self.assertRaisesRegex(Problem,'Chat Completions 兼容格式'):
            complete(settings,'synthetic',structured=True,timeout=2)

    def test_structured_sse_reasoning_does_not_consume_visible_output_budget(self):
        settings={**self.settings,'api_model':'structured_reasoning_sse','stream':True,'stream_verified':True}
        self.assertEqual(complete(settings,'synthetic',structured=True,timeout=5),'{"ok":true}')

    def test_structured_sse_reasoning_has_separate_limit(self):
        settings={**self.settings,'api_model':'reasoning_oversize','stream':True,'stream_verified':True}
        with self.assertRaisesRegex(Problem,'推理内容过大'):
            complete(settings,'synthetic',structured=True,timeout=10)

    def test_structured_sse_visible_content_has_separate_limit(self):
        settings={**self.settings,'api_model':'content_oversize','stream':True,'stream_verified':True}
        with self.assertRaisesRegex(Problem,'模型输出过大'):
            complete(settings,'synthetic',structured=True,timeout=10)

    def test_sse_multiline_data_event_is_parsed(self):
        settings={**self.settings,'api_model':'multiline_sse','stream':True,'stream_verified':True}
        self.assertEqual(complete(settings,'synthetic',structured=True,timeout=2),'{"ok":true}')

    def test_structured_sse_without_reasoning_content_remains_compatible(self):
        settings={**self.settings,'api_model':'legacy_sse','stream':True,'stream_verified':True}
        self.assertEqual(complete(settings,'synthetic',structured=True,timeout=2),'{"ok":true}')

    def test_sse_length_and_content_filter_finish_reasons_are_rejected(self):
        for model in ('finish_length','finish_content_filter'):
            with self.subTest(model=model):
                settings={**self.settings,'api_model':model,'stream':True,'stream_verified':True}
                with self.assertRaisesRegex(Problem,'截断或拦截'):
                    complete(settings,'synthetic',structured=True,timeout=2)

    def test_unverified_stream_falls_back_to_nonstream(self):
        for stream,verified in ((False,True),(True,False)):
            with self.subTest(stream=stream,verified=verified):
                settings={**self.settings,'stream':stream,'stream_verified':verified}
                self.assertEqual(complete(settings,'synthetic',structured=True,timeout=2),'OK')
                self.assertFalse(self.requests[-1]['stream'])
