"""A bounded Chat Completions compatible transport. Secrets stay server-side."""
import json
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


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def complete(settings, prompt, structured=False, timeout=180, on_delta=None, cancelled=None):
    """Own the HTTP request process so DNS/header/body waits are all interruptible."""
    began = time.monotonic()
    proc = subprocess.Popen([sys.executable, '-m', 'app.api_transport'],
                            cwd=Path(__file__).resolve().parent.parent,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, encoding='utf-8')
    events = queue.Queue(maxsize=8)
    stop = threading.Event()
    def read_events():
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
    reader = threading.Thread(target=read_events, daemon=True)
    try:
        if cancelled and cancelled(): raise Problem('任务已取消')
        proc.stdin.write(json.dumps({'settings':settings,'prompt':prompt,'structured':structured,
                                    'timeout':timeout,'stream':on_delta is not None}, ensure_ascii=False))
        proc.stdin.close()
        reader.start()
        while True:
            if cancelled and cancelled(): raise Problem('任务已取消')
            remaining = timeout - (time.monotonic() - began)
            if remaining <= 0: raise Problem('模型请求超过总时限，请稍后重试')
            try: event = events.get(timeout=min(.05, remaining))
            except queue.Empty: continue
            if event['type'] == 'delta' and on_delta: on_delta(event['text'])
            elif event['type'] == 'result': return event['text']
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


def _complete_blocking(settings, prompt, structured=False, timeout=180, on_delta=None, cancelled=None):
    base = validate_url(settings.get("base_url", ""))
    if not settings.get("api_model"):
        raise Problem("请在工作台填写 API 模型名称")
    endpoint = base if base.endswith("/chat/completions") else base + "/chat/completions"
    stream=bool(on_delta and not structured and settings.get('stream',True))
    payload = {"model": settings["api_model"], "messages": [{"role": "user", "content": prompt}], "stream": stream}
    if structured and settings.get("json_mode", True):
        payload["response_format"] = {"type": "json_object"}
    headers = {"Content-Type": "application/json"}
    if settings.get("api_key"):
        headers["Authorization"] = "Bearer " + settings["api_key"]
    req = urllib.request.Request(endpoint, data=json.dumps(payload, ensure_ascii=False).encode(), headers=headers, method="POST")
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=timeout) as response:
            if stream and 'text/event-stream' in response.headers.get('Content-Type',''):
                output=[];data=[];size=0;finished=False;started=time.monotonic()
                while True:
                    rawline=response.readline(65537)
                    if not rawline:break
                    if len(rawline)>65536:raise Problem('流式数据行过长')
                    if cancelled and cancelled():raise Problem('任务已取消')
                    if time.monotonic()-started>timeout:raise Problem('流式回复超时')
                    size+=len(rawline)
                    if size>1024*1024:raise Problem('模型返回过大')
                    line=rawline.decode('utf-8').rstrip('\r\n')
                    if line.startswith('data:'):data.append(line[5:].lstrip());continue
                    if line or not data:continue
                    raw_event='\n'.join(data);data=[]
                    if raw_event=='[DONE]':finished=True;break
                    event=json.loads(raw_event)
                    if event.get('error'):raise Problem('模型流式接口报告错误')
                    for choice in event.get('choices',[]):
                        reason=choice.get('finish_reason')
                        if reason in ('length','content_filter'):raise Problem('回复被截断或拦截，请重试')
                        if reason=='stop':finished=True
                        delta=choice.get('delta',{}).get('content')
                        if isinstance(delta,str) and delta:
                            output.append(delta);on_delta(''.join(output))
                if not finished or not output:raise Problem('流式连接提前结束，未收到完整回复')
                return ''.join(output)
            raw = response.read(1024 * 1024 + 1)
            if cancelled and cancelled():raise Problem('任务已取消')
        if len(raw) > 1024 * 1024:
            raise Problem("模型返回过大，请缩短任务后重试")
        result = json.loads(raw)
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
    except (urllib.error.URLError, TimeoutError):
        raise Problem("模型连接失败或超时，请在工作台测试连接") from None
    except (ValueError, KeyError, IndexError, TypeError):
        raise Problem("接口未返回 Chat Completions 兼容格式") from None


def test_connection(settings):
    # Never send a profile, conversations, or files for a connection test.
    if settings.get("provider") == "api" and not settings.get("api_key"):
        raise Problem("尚未保存 API 密钥：输入后先点击“保存接入方式”，再测试连接")
    result = complete(settings, "This is a connection test. Reply only OK.", timeout=20)
    return {"ok": bool(result.strip()), "message": "连接成功（仅发送固定测试文本）"}
