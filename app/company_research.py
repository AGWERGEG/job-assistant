"""Explicit, read-only public company research. No browser/session credentials.

Network results are previews; only Company.confirm_research persists reviewed
material. HTML and search excerpts are evidence, never instructions or verified facts.
"""
import hashlib
import http.client
import ipaddress
import json
import queue
import socket
import ssl
import secrets
import threading
import time
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlsplit
from xml.etree import ElementTree

from .store import Problem, require_object, text_field

MAX_BYTES = 512 * 1024
MAX_SOURCES = 5
PREVIEW_TTL = 10 * 60
BLOCKED_DOMAINS = ('zhipin.com', 'zhaopin.com', 'liepin.com', '51job.com', 'linkedin.com')

PUBLIC_TOPICS = (
    ('产品', ('产品', '产品线', '软件', '服务', '解决方案')),
    ('业务', ('业务', '商业模式', '主营', '做什么', '经营')),
    ('客户与行业', ('客户', '服务对象', '行业')),
    ('发展与公开动态', ('发展', '动态', '融资', '新闻', '历史')),
    ('口碑与评价', ('风评', '口碑', '评价', '怎么样', '工作体验')),
)


def public_search_query(company_name, question):
    """Reduce a potentially private question to a bounded public topic query."""
    topics = [label for label, terms in PUBLIC_TOPICS if any(term in question for term in terms)]
    if not topics:
        topics = ['业务', '产品']
    return company_name + ' ' + ' '.join(topics[:3])


def public_url(value):
    value = text_field(value, '公开来源 URL', 2000, True)
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise Problem('公开来源 URL 无效')
    host = (parsed.hostname or '').lower().rstrip('.')
    if (parsed.scheme != 'https' or not host or parsed.username or parsed.password
            or port not in (None, 443) or parsed.fragment
            or any(host == d or host.endswith('.' + d) for d in BLOCKED_DOMAINS)):
        raise Problem('仅支持无登录信息的 HTTPS 公开来源；招聘平台页面请使用已保存材料')
    if host == 'localhost' or host.endswith(('.local', '.localhost', '.internal')):
        raise Problem('禁止访问本机或内部网络')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise Problem('禁止访问本机或内部网络')
    return value


def _resolve(host, deadline):
    # A daemon resolver prevents slow system DNS from defeating the wall clock.
    answer = queue.Queue(maxsize=1)
    def resolve():
        try:
            answer.put(socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM))
        except Exception as exc:
            answer.put(exc)
    threading.Thread(target=resolve, daemon=True).start()
    try:
        rows = answer.get(timeout=max(0.001, deadline - time.monotonic()))
    except queue.Empty:
        raise Problem('公开来源 DNS 查询超时', 504)
    if isinstance(rows, Exception):
        raise Problem('公开来源域名无法解析', 502)
    addresses = list(dict.fromkeys(row[4][0] for row in rows))
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise Problem('公开来源指向本机或内部网络，已拒绝')
    return addresses[0]


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, ip, timeout):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self.public_ip = ip

    def connect(self):
        sock = socket.create_connection((self.public_ip, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


class PublicHTTP:
    """Bounded HTTPS GET, pinned public DNS, TLS validation, no cookies/proxies."""
    def get(self, url, *, deadline):
        for hop in range(4):
            url = public_url(url)
            parsed = urlsplit(url)
            ip = _resolve(parsed.hostname, deadline)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Problem('公开资料获取超时', 504)
            connection = _PinnedHTTPS(parsed.hostname, ip, remaining)
            try:
                connection.request('GET', (parsed.path or '/') + ('?' + parsed.query if parsed.query else ''),
                                   headers={'User-Agent': 'JobAssistant-PublicResearch/1', 'Accept': 'text/html,application/xml,text/xml,text/plain', 'Accept-Encoding': 'identity'})
                response = connection.getresponse()
                if response.status in (301, 302, 303, 307, 308):
                    location = response.getheader('Location')
                    if not location or hop == 3:
                        raise Problem('公开来源重定向过多或无目标', 502)
                    url = urljoin(url, location)
                    continue
                if response.status != 200:
                    raise Problem('公开来源返回 HTTP ' + str(response.status), 502)
                content_type = response.getheader('Content-Type', '').lower()
                if not any(t in content_type for t in ('text/html', 'text/plain', 'text/xml', 'application/xml', 'application/rss+xml')):
                    raise Problem('公开来源不是可读取的文本页面')
                if response.getheader('Content-Encoding', 'identity') not in ('', 'identity'):
                    raise Problem('公开来源压缩格式不受支持')
                data = bytearray()
                while len(data) <= MAX_BYTES:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise Problem('公开资料获取超时', 504)
                    connection.sock.settimeout(remaining) if connection.sock else None
                    part = response.read1(min(16384, MAX_BYTES + 1 - len(data)))
                    if not part:
                        break
                    data.extend(part)
                if len(data) > MAX_BYTES:
                    raise Problem('公开来源超过 512 KiB 限制')
                charset = response.headers.get_content_charset() or 'utf-8'
                try:
                    text = bytes(data).decode(charset, errors='replace')
                except LookupError:
                    raise Problem('公开来源字符编码不受支持')
                return {'url': url, 'text': text, 'content_type': content_type, 'observed_at': time.time()}
            except (OSError, http.client.HTTPException) as exc:
                raise Problem('公开资料连接失败或超时（' + type(exc).__name__ + '）', 502)
            finally:
                connection.close()


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []; self.hidden = 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self.hidden += 1
    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self.hidden = max(0, self.hidden - 1)
    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data.strip())


def _plain(text):
    parser = _Text(); parser.feed(text)
    return '\n'.join(parser.parts)


def _relevant_excerpt(text, company_name, question, limit=20000):
    parser = _Text(); parser.feed(text)
    parts = [part.strip() for part in parser.parts if part.strip()]
    topic_terms={
        '产品':('产品','产品线','软件','服务','解决方案','product','service','solution'),
        '业务':('业务','商业模式','主营','经营','业务模式','business','company','about'),
        '客户与行业':('客户','服务对象','行业','customer','industry'),
        '发展与公开动态':('发展','动态','融资','新闻','history','news','funding'),
        '口碑与评价':('评价','口碑','评测','review','rating'),
    }
    selected=public_search_query(company_name,question).removeprefix(company_name).strip().split()
    terms=tuple(term for topic in selected for term in topic_terms.get(topic,()))
    company_token = company_name.casefold().strip()
    ranked=[]
    for index,part in enumerate(parts):
        lowered=part.casefold(); score=sum(2 for term in terms if term in lowered)
        if company_token and company_token in lowered:score+=4
        if score:ranked.append((index,score,part))
    chosen={};size=0
    for index,score,part in sorted(ranked,key=lambda row:(-row[1],row[0])):
        if size+len(part)>limit-2500:part=part[:max(0,limit-2500-size)]
        if part:chosen[index]=part;size+=len(part)+1
        if size>=limit-2500:break
    # Retain a little opening context after the relevant lines, capped so a
    # long menu cannot crowd the business description out of the excerpt.
    for index,part in enumerate(parts[:3]):
        if index not in chosen and size<limit:
            part=part[:min(1200,limit-size)]
            if part:chosen[index]=part;size+=len(part)+1
    output=[];size=0
    for index,part in sorted(chosen.items()):
        if size+len(part)>limit:part=part[:max(0,limit-size)]
        if part:output.append(part);size+=len(part)+1
        if size>=limit:break
    return '\n'.join(output)


class _SearchResults(HTMLParser):
    def __init__(self):
        super().__init__();self.current=None;self.items=[]
    def handle_starttag(self,tag,attrs):
        if tag=='a':self.current=[dict(attrs).get('href',''),[]]
    def handle_endtag(self,tag):
        if tag=='a' and self.current:
            url,parts=self.current;title=' '.join(part.strip() for part in parts if part.strip())
            if url and title:self.items.append((url,title))
            self.current=None
    def handle_data(self,data):
        if self.current:self.current[1].append(data)


class PublicSearch:
    """Bing public RSS/HTML search. No API key or browser session is used."""
    def __init__(self, http=None):
        self.http = http or PublicHTTP()
    def search(self, company_name, question, *, deadline):
        topics = public_search_query(company_name, question).removeprefix(company_name).strip()
        # RSS occasionally tokenizes Chinese names plus topics into unrelated
        # single-character results. Retry only the company name, using the same
        # deadline and identity checks; never include the private question.
        queries = ['"' + company_name + '" ' + topics, '"' + company_name + '"']
        for query in queries:
            if time.monotonic() >= deadline:
                raise Problem('企业公开搜索超时', 504)
            results = self._search_query(company_name, query, deadline=deadline)
            if results:
                return results
        raise Problem('公开搜索暂未找到能明确关联这家公司的来源；请提供企业官网公开 HTTPS 页面或稍后重试', 502)

    def _search_query(self, company_name, query, *, deadline):
        url = 'https://cn.bing.com/search?format=rss&q=' + quote(query)
        page = self.http.get(url, deadline=deadline)
        if '<!ENTITY' in page['text'].upper():
            raise Problem('公开搜索返回不受支持的实体声明')
        try:
            root = ElementTree.fromstring(page['text'])
        except ElementTree.ParseError:
            parser=_SearchResults();parser.feed(page['text'])
            candidates=[]
            for target,title in parser.items:
                if not target.startswith('https://') or (urlsplit(target).hostname or '').lower() in ('www.bing.com','cn.bing.com'):
                    continue
                candidates.append({'url':target,'text':title,'title':title,'observed_at':page['observed_at'],'search_url':page['url']})
            root=None
        if root is None:
            raw_results=candidates
        else:
            raw_results=[{'url':item.findtext('link',''),'title':item.findtext('title',''),
                          'text':_plain(item.findtext('description','')),
                          'observed_at':page['observed_at'],'search_url':page['url']}
                         for item in root.findall('./channel/item')[:10]]
        results = []
        for item in raw_results[:10]:
            target = item['url']; title = item['title']; excerpt = item['text']
            company_token = company_name.casefold().strip()
            haystack = (title + ' ' + excerpt).casefold()
            if not company_token or company_token not in haystack:
                continue
            try:
                public_url(target)
            except Problem:
                continue
            if len(excerpt.strip()) < 12:
                continue
            results.append(item)
            if len(results) == MAX_SOURCES:
                break
        return results


class CompanyResearch:
    def __init__(self, company=None, *, http=None, search_provider=None):
        self.company = company
        self.http = http or PublicHTTP()
        self.search_provider = search_provider
        self._previews = {}

    def _target(self, job_id):
        if not job_id or not self.company:
            return None
        with self.company.store.connect() as db:
            job = db.execute('SELECT id,company,revision FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not job:
                raise Problem('岗位不存在', 404)
            binding = db.execute('SELECT c.company_key,c.name,c.url FROM job_companies j JOIN companies c ON c.company_key=j.company_key WHERE j.job_id=?', (job_id,)).fetchone()
            return {'job_id':job['id'], 'job_revision':job['revision'],
                    'job_company':job['company'], 'company_key':binding['company_key'] if binding else None,
                    'company_name':binding['name'] if binding else None,
                    'company_url':binding['url'] if binding else None}

    def research(self, company_name, question, *, job_id=None, public_urls=None, allow_network=False, timeout=20):
        company_name = text_field(company_name, '公司名', 300, True)
        question = text_field(question, '企业问题', 2000, True)
        urls = public_urls or []
        if not isinstance(urls, list) or len(urls) > MAX_SOURCES:
            raise Problem('每次最多读取五个公开来源')
        for url in urls:
            public_url(url)
        target = self._target(job_id)
        if target:
            # The saved target name is authoritative; a caller cannot research
            # a different company under this job ID.
            requested_name = target['job_company'] or company_name
            if target['company_key']:
                company_name = target['company_name']
            else:
                company_name = requested_name
            if target['company_key'] and target['job_company'] and target['company_name'] != target['job_company']:
                result_name_warning = '岗位文字与已绑定公司名称不同，请人工核对身份'
            else:
                result_name_warning = ''
        else:
            result_name_warning = ''
        result = {'company_name': company_name, 'question': question, 'sources': [], 'facts': [], 'warnings': []}
        if result_name_warning:
            result['warnings'].append(result_name_warning)
        if job_id and self.company:
            saved = self.company.read(job_id)
            if saved and saved['name'] == company_name:
                for evidence in saved['evidence'][:MAX_SOURCES]:
                    text = evidence.get('text', '')
                    if text:
                        self._append(result, evidence['source_url'], text, evidence['observed'],
                                     evidence.get('source_type', 'saved_company_material'), evidence.get('confidence', 'unverified'),
                                     already_saved=True)
            elif saved:
                result['warnings'].append('公司名与绑定公司不一致，未使用其资料；请人工核对公司身份')
        if not allow_network:
            if urls:
                result['warnings'].append('尚未授权公开联网读取；请明确允许后重试')
            elif not self.search_provider:
                result['warnings'].append('当前没有可用公开搜索；可提供企业官网公开 HTTPS URL，或稍后重试')
        else:
            deadline = time.monotonic() + min(max(float(timeout), 0.1), 30)
            if not urls:
                if not self.search_provider:
                    result['warnings'].append('当前没有可用公开搜索；可提供企业官网公开 HTTPS URL，或稍后重试')
                else:
                    try:
                        for item in self.search_provider.search(company_name, question, deadline=deadline)[:MAX_SOURCES]:
                            self._append(result, public_url(item['url']), item['text'], item['observed_at'], 'public_search_excerpt', 'unverified', title=item.get('title'), search_url=item.get('search_url'), provider=item.get('provider'))
                    except Problem as exc:
                        result['warnings'].append(str(exc))
            for url in urls:
                try:
                    page = self.http.get(url, deadline=deadline)
                    self._append(result, page['url'], _relevant_excerpt(page['text'], company_name, question), page['observed_at'], 'public_web_page', 'unverified')
                except Problem as exc:
                    result['warnings'].append(str(exc))
        result['sources'].sort(key=lambda source:source.get('already_saved') is True)
        source_order={source['id']:index for index,source in enumerate(result['sources'])}
        result['facts'].sort(key=lambda fact:min((source_order.get(sid,99) for sid in fact['source_ids']),default=99))
        result['warnings'].append('公开页面与搜索摘要仅为来源陈述，公司同名和信息时效需人工核对；风评不代表已核实事实')
        if not result['sources']:
            result['warnings'].append('没有取得可用企业资料；本轮未完成公开检索')
        result['preview_id'] = secrets.token_urlsafe(32)
        self._previews[result['preview_id']] = {'result':json.loads(json.dumps(result)), 'target':target, 'job_id':job_id,
                                                'created_at':time.monotonic()}
        while len(self._previews) > 20:
            del self._previews[next(iter(self._previews))]
        return result

    @staticmethod
    def _append(result, url, text, observed, source_type, confidence, **extra):
        if not text.strip():
            return
        extra={key:value for key,value in extra.items() if value is not None}
        sid = hashlib.sha256((url + '|' + text).encode()).hexdigest()
        already_saved = extra.pop('already_saved', False)
        for source in result['sources']:
            if source['id'] == sid:
                source.update(extra)
                return
        result['sources'].append({'id': sid, 'url': url, 'observed_at': observed,
                                  'source_type': source_type, 'confidence': confidence, 'excerpt': text[:20000],
                                  'already_saved':already_saved, **extra})
        result['facts'].append({'text': text[:20000], 'source_ids': [sid], 'confidence': confidence,
                                'status': 'source_claim'})

    def confirm(self, job_id, preview_id, *, confirmed=False):
        if not confirmed or not self.company:
            raise Problem('保存企业研究材料需要用户明确确认')
        preview = self._previews.get(preview_id)
        if not preview:
            raise Problem('企业研究预览不存在或已过期，请重新获取', 409)
        if preview['job_id'] != job_id:
            raise Problem('企业研究预览与岗位不匹配', 409)
        if time.monotonic() - preview['created_at'] > PREVIEW_TTL:
            del self._previews[preview_id]
            raise Problem('企业研究预览已过期，请重新获取', 409)
        target = preview['target']
        if target:
            expected = {'job_revision':target['job_revision'], 'company_key':target['company_key'],
                        'company_name':target['company_name'], 'company_url':target['company_url']}
        else:
            expected = None
        return self.company.confirm_research(job_id, preview['result'], confirmed=True, expected_target=expected)

    def discard(self, job_id, preview_id):
        preview = self._previews.get(preview_id)
        if preview and preview['job_id'] == job_id:
            del self._previews[preview_id]
        return {'discarded':True}
