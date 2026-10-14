"""Short-lived API transport child. Secrets arrive on stdin, never command arguments."""
import json
import http.client
import sys
import urllib.error
import urllib.request
from .providers import _complete_blocking
from .store import Problem


def emit(kind, text, usage=None):
    value={'type':kind,'text':text}
    if usage:value['usage']=usage
    payload=(json.dumps(value, ensure_ascii=False)+'\n').encode('utf-8')
    stream=getattr(sys.stdout, 'buffer', None)
    if stream is not None:
        stream.write(payload);stream.flush()
    else:
        sys.stdout.write(payload.decode('utf-8'));sys.stdout.flush()


def read_request():
    stream=getattr(sys.stdin, 'buffer', None)
    if stream is not None:
        return json.loads(stream.read().decode('utf-8'))
    return json.load(sys.stdin)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _search_blocking(settings, query, timeout):
    """Tavily source-only POST. No answer text, redirects, raw errors or logs."""
    api_key = settings.get('search_api_key')
    if not isinstance(api_key, str) or not api_key or len(api_key) > 4096:
        raise Problem('请先保存有效的 Tavily 搜索密钥')
    if not isinstance(query, str) or not query.strip() or len(query) > 1000:
        raise Problem('公开搜索关键词无效')
    timeout = min(max(float(timeout), 0.1), 30)
    body = {'query':query, 'search_depth':'basic', 'max_results':5,
            'include_answer':False, 'include_raw_content':False, 'include_images':False}
    request = urllib.request.Request(
        'https://api.tavily.com/search',
        data=json.dumps(body,ensure_ascii=False).encode('utf-8'),
        headers={'Authorization':'Bearer '+api_key,'Content-Type':'application/json','Accept':'application/json'},
        method='POST')
    try:
        opener=urllib.request.build_opener(_NoRedirect)
        with opener.open(request,timeout=timeout) as response:
            raw=response.read(512*1024+1)
            if len(raw)>512*1024:
                raise Problem('公开搜索响应超过 512 KiB 限制')
            result=json.loads(raw.decode('utf-8'))
    except urllib.error.HTTPError as exc:
        raise Problem(f'公开搜索服务返回 HTTP {exc.code}；密钥或服务响应未保存', 502) from None
    except (urllib.error.URLError, TimeoutError, http.client.HTTPException, OSError):
        raise Problem('公开搜索连接失败或超时；服务响应未保存', 502) from None
    except (UnicodeError, ValueError, TypeError):
        raise Problem('公开搜索服务响应格式无效；服务响应未保存', 502) from None
    company_token = ''
    # The query contains the company and public topics. Extracting a separate
    # identity from the caller avoids trusting any model-generated answer.
    company_token=str(settings.get('_search_company','')).casefold().strip()
    results=result.get('results') if isinstance(result,dict) else None
    safe=[]
    if isinstance(results,list):
        from .company_research import public_url
        for item in results[:5]:
            if not isinstance(item,dict):continue
            title=item.get('title');content=item.get('content');url=item.get('url')
            if not all(isinstance(v,str) and v.strip() for v in (title,content,url)):continue
            title=title.strip()[:500];content=content.strip()[:12000]
            if not company_token or company_token not in (title+' '+content).casefold():continue
            if api_key in title or api_key in content or api_key in url:
                raise Problem('公开搜索服务响应包含敏感内容，已拒绝')
            try:url=public_url(url)
            except Problem:continue
            safe.append({'title':title,'content':content,'url':url})
    return json.dumps(safe,ensure_ascii=False)


def main():
    # Windows may inherit a GBK console encoding. The parent transport
    # protocol is UTF-8 on every platform.
    if hasattr(sys.stdin, 'reconfigure'):
        sys.stdin.reconfigure(encoding='utf-8', errors='strict')
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='strict')
    try:
        value = read_request()
        operation=value.get('operation','model')
        if operation not in ('model','tavily_search'):
            raise Problem('不支持的 API transport 操作')
        if operation=='tavily_search':
            if value.get('settings',{}).get('_operation')!='tavily_search':
                raise Problem('搜索 transport 操作标记无效')
            emit('result',_search_blocking(value['settings'],value['prompt'],value['timeout']))
            return
        usage={}
        result = _complete_blocking(value['settings'], value['prompt'],
                                    structured=value['structured'], timeout=value['timeout'],
                                    on_delta=(lambda text: emit('delta',text)) if value['stream'] else None,
                                    usage_out=usage)
        emit('result',result,usage)
    except Problem as exc:
        emit('error',str(exc))
    except Exception as exc:
        # Exception messages can contain response bodies or credentials. Keep only the type.
        emit('error',f'模型接口处理异常（{type(exc).__name__}），请重试；原始响应未保存')


if __name__ == '__main__':
    main()
