"""A bounded Chat Completions compatible transport. Secrets stay server-side."""
import json
import http.client
import os
import time
import queue
import subprocess
import sys
import threading
from pathlib import Path
import urllib.error
import urllib.request

from .companion import validate_url
from .store import Problem


# SSE limits are independent: reasoning traces can be large without consuming
# the visible structured response budget. Raw traffic still has a finite safety cap.
STREAM_TOTAL_BYTES = 16 * 1024 * 1024
STREAM_REASONING_BYTES = 8 * 1024 * 1024
STREAM_CONTENT_BYTES = 4 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def complete(settings, prompt, structured=False, timeout=180, on_delta=None, cancelled=None, on_usage=None, operation='model'):
    """Own the HTTP request process so DNS/header/body waits are all interruptible."""
    if operation not in ('model','tavily_search'):
        raise Problem('不支持的 API transport 操作')
    began = time.monotonic()
    proc = subprocess.Popen([sys.executable, '-m', 'app.api_transport'],
                            cwd=Path(__file__).resolve().parent.parent,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, encoding='utf-8',
                            env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'})
    events = queue.Queue(maxsize=8)
    stop = threading.Event()
    def read_events():
        try:
            while not stop.is_set():
                line = proc.stdout.readline(8 * 1024 * 1024 + 1)
                if not line:
                    event = {'type':'error','text':'模型连接进程提前结束，请重试'}
                elif len(line) > 8 * 1024 * 1024:
                    event = {'type':'error','text':'模型返回过大'}
                else:
                    try: event = json.loads(line)
                    except ValueError: event = {'type':'error','text':'模型连接进程返回无效数据'}
                while not stop.is_set():
                    try: events.put(event, timeout=.05); break
                    except queue.Full: continue
                if not line or event.get('type') in ('result','error'): return
        except (OSError, UnicodeError):
            event = {'type':'error','text':'模型连接进程返回了无法解码的数据，请重试'}
            while not stop.is_set():
                try: events.put(event, timeout=.05); return
                except queue.Full: continue
    reader = threading.Thread(target=read_events, daemon=True)
    try:
        if cancelled and cancelled(): raise Problem('任务已取消')
        want_stream = bool(settings.get('stream', True) and (
            settings.get('stream_verified', False) if structured else on_delta is not None))
        proc.stdin.write(json.dumps({'operation':operation,'settings':settings,'prompt':prompt,'structured':structured,
                                    'timeout':timeout,'stream':want_stream}, ensure_ascii=False))
        proc.stdin.close()
        reader.start()
        while True:
            if cancelled and cancelled(): raise Problem('任务已取消')
            remaining = timeout - (time.monotonic() - began)
            if remaining <= 0: raise Problem('模型请求超过总时限，请稍后重试')
            try: event = events.get(timeout=min(.05, remaining))
            except queue.Empty: continue
            if event['type'] == 'delta' and on_delta: on_delta(event['text'])
            elif event['type'] == 'result':
                if on_usage and isinstance(event.get('usage'), dict): on_usage(event['usage'])
                return event['text']
            elif event['type'] == 'error': raise Problem(event['text'])
    except (OSError, ValueError):
        raise Problem('模型连接进程无法启动或已中断，请重试') from None
    finally:
        stop.set()
        if proc.poll() is None:
            proc.terminate()
            try: proc.wait(timeout=.5)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait()
        if reader.ident is not None: reader.join(timeout=.5)
        if proc.stdin and not proc.stdin.closed: proc.stdin.close()
        proc.stdout.close()


def _complete_blocking(settings, prompt, structured=False, timeout=180, on_delta=None, cancelled=None, usage_out=None):
    base = validate_url(settings.get("base_url", ""))
    if not settings.get("api_model"):
        raise Problem("请在工作台填写 API 模型名称")
    endpoint = base if base.endswith("/chat/completions") else base + "/chat/completions"
    stream=bool(settings.get('stream', True) and (
        settings.get('stream_verified', False) if structured else on_delta is not None))
    payload = {"model": settings["api_model"], "messages": [{"role": "user", "content": prompt}], "stream": stream}
    max_tokens = settings.get("max_tokens")
    if isinstance(max_tokens, int) and max_tokens > 0:
        payload["max_tokens"] = min(max_tokens, 131072)
    if settings.get("thinking") == "disabled":
        payload["thinking"] = {"type": "disabled"}
    if structured and settings.get("json_mode", True):
        payload["response_format"] = {"type": "json_object"}
    headers = {"Content-Type": "application/json"}
    if settings.get("api_key"):
        headers["Authorization"] = "Bearer " + settings["api_key"]
    req = urllib.request.Request(endpoint, data=json.dumps(payload, ensure_ascii=False).encode(), headers=headers, method="POST")
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=timeout) as response:
            if stream and 'text/event-stream' in response.headers.get('Content-Type',''):
                output=[];data=[];total_size=0;reasoning_size=0;content_size=0;finished=False;done=False;started=time.monotonic();stream_usage={}
                while True:
                    rawline=response.readline(65537)
                    if not rawline:
                        if data: raise Problem('流式连接提前结束，未收到完整回复')
                        break
                    if len(rawline)>65536:raise Problem('流式数据行过长')
                    if cancelled and cancelled():raise Problem('任务已取消')
                    if time.monotonic()-started>timeout:raise Problem('流式回复超时')
                    total_size+=len(rawline)
                    if total_size>STREAM_TOTAL_BYTES:raise Problem('模型流式响应总量过大，请缩短任务或降低推理长度')
                    line=rawline.decode('utf-8').rstrip('\r\n')
                    if line.startswith('data:'):data.append(line[5:].lstrip());continue
                    if line or not data:continue
                    raw_event='\n'.join(data);data=[]
                    if raw_event.strip()=='[DONE]':finished=True;done=True;break
                    try:event=json.loads(raw_event)
                    except (ValueError,TypeError):raise Problem('模型流式事件格式无效，请检查接口兼容性') from None
                    if event.get('error'):raise Problem('模型流式接口报告错误')
                    if isinstance(event.get('usage'), dict):stream_usage.update(event['usage'])
                    for choice in event.get('choices',[]):
                        reason=choice.get('finish_reason')
                        if reason in ('length','content_filter'):raise Problem('回复被截断或拦截，请重试')
                        if reason=='stop':finished=True
                        delta=choice.get('delta') or {}
                        reasoning=delta.get('reasoning_content')
                        if reasoning is None: reasoning=delta.get('reasoning')
                        if isinstance(reasoning,str):
                            reasoning_size += len(reasoning.encode('utf-8'))
                            if reasoning_size>STREAM_REASONING_BYTES:raise Problem('模型推理内容过大，请降低推理长度后重试')
                        text=delta.get('content')
                        if isinstance(text,str) and text:
                            content_size += len(text.encode('utf-8'))
                            if content_size>STREAM_CONTENT_BYTES:raise Problem('模型输出过大，请缩短任务或降低输出长度')
                            output.append(text)
                            if on_delta and not structured: on_delta(''.join(output))
                if not finished or (structured and not done) or not ''.join(output).strip():
                    raise Problem('流式连接提前结束，未收到完整回复')
                if usage_out is not None: usage_out.update(stream_usage)
                return ''.join(output)
            raw = response.read(1024 * 1024 + 1)
            if cancelled and cancelled():raise Problem('任务已取消')
            declared = response.headers.get('Content-Length')
            if declared is not None:
                try:
                    expected = int(declared)
                except ValueError:
                    raise Problem('模型响应长度字段无效，请检查接口或网络后重试') from None
                if expected >= 0 and len(raw) < expected:
                    raise Problem(f'模型响应传输不完整（收到 {len(raw)} / 期望 {expected} 字节），请检查网络后重试')
        if len(raw) > STREAM_CONTENT_BYTES:
            raise Problem("模型输出过大，请缩短任务或降低输出长度")
        result = json.loads(raw)
        if usage_out is not None and isinstance(result.get('usage'), dict): usage_out.update(result['usage'])
        choice = result["choices"][0]
        if choice.get("finish_reason") in ("length", "content_filter"):
            raise Problem("模型输出被截断或拦截，请调整模型配置后重试")
        content = choice["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise Problem("模型未返回可用文本")
        return content
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise Problem("模型接口返回 HTTP 401：鉴权未通过。先确认页面显示“已保存密钥”；若已保存，请在服务商控制台检查该密钥是否有效且可用。服务端错误正文不会保存") from None
        raise Problem(f"模型接口返回 HTTP {exc.code}，请检查地址、密钥、模型与 JSON 模式；服务端错误正文不会保存") from None
    except http.client.IncompleteRead:
        raise Problem("模型响应传输不完整，请检查网络后重试") from None
    except (http.client.RemoteDisconnected, ConnectionError) as exc:
        raise Problem(f"模型连接在回复完成前中断（{type(exc).__name__}），请稍后重试") from None
    except http.client.HTTPException as exc:
        raise Problem(f"模型响应协议异常（{type(exc).__name__}），请检查接口或网络后重试") from None
    except (urllib.error.URLError, TimeoutError):
        raise Problem("模型连接失败或超时，请在工作台测试连接") from None
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise Problem("接口未返回 Chat Completions 兼容格式") from None


def test_connection(settings):
    # Never send a profile, conversations, or files for a connection test.
    if settings.get("provider") == "api" and not settings.get("api_key"):
        raise Problem("尚未保存 API 密钥：输入后先点击“保存接入方式”，再测试连接")
    prompt = "This is a connection test. Reply only OK."
    if settings.get('stream', True):
        try:
            parts=[]
            result=complete(settings,prompt,timeout=30,on_delta=parts.append)
            structured_ok=_test_structured(settings)
            return {"ok":bool(result.strip()),"stream_supported":True,"structured_supported":structured_ok,
                    "message":"连接成功：短对话逐段显示可用；"+("专业任务 JSON 可用。" if structured_ok else "专业任务 JSON 测试未通过，建议关闭 JSON 模式后再测试。")}
        except Problem as stream_error:
            # Some compatible services accept ordinary Chat Completions but
            # never finish their SSE stream. Verify the usable fallback.
            result=complete({**settings,'stream':False},prompt,timeout=20)
            structured_ok=_test_structured(settings)
            return {"ok":bool(result.strip()),"stream_supported":False,"structured_supported":structured_ok,
                    "message":"连接成功，但逐段显示不兼容，已自动改用完整回复模式；"+("专业任务 JSON 可用。" if structured_ok else "专业任务 JSON 测试未通过，建议关闭 JSON 模式后再测试。")+"原流式错误："+str(stream_error)}
    result = complete({**settings,'stream':False},prompt,timeout=20)
    structured_ok=_test_structured(settings)
    return {"ok":bool(result.strip()),"stream_supported":False,"structured_supported":structured_ok,
            "message":"连接成功，使用完整回复模式；"+("专业任务 JSON 可用。" if structured_ok else "专业任务 JSON 测试未通过，建议关闭 JSON 模式后再测试。")}


def _test_structured(settings):
    """Use a tiny synthetic object: no profile, conversation or document."""
    prompt='Return only this JSON object: {"ok":true}'
    try:
        result=complete({**settings,'stream':False},prompt,structured=True,timeout=20)
        value=json.loads(result)
        return value.get('ok') is True
    except (Problem, ValueError, TypeError):
        return False
