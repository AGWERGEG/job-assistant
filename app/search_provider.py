"""Bounded public company-search providers."""
import json
import time

from .providers import complete
from .store import Problem


class TavilySearch:
    """Tavily source search using the isolated API transport child."""
    def __init__(self, api_key, *, cancelled=None):
        self._api_key = api_key or ''
        self.cancelled = cancelled

    def search(self, company_name, question, *, deadline):
        from .company_research import public_search_query, public_url
        if not self._api_key:
            raise Problem('请先在工作台保存 Tavily 搜索密钥，或切回免密公开搜索')
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise Problem('企业公开搜索超时', 504)
        query = public_search_query(company_name, question)
        settings = {'_operation':'tavily_search', '_search_company':company_name,
                    'search_api_key':self._api_key, 'stream':False}
        raw = complete(settings, query, timeout=min(30, remaining),
                       cancelled=self.cancelled, operation='tavily_search')
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            raise Problem('公开搜索服务返回格式无效；未保存原始响应') from None
        if not isinstance(payload, list):
            raise Problem('公开搜索服务未返回可用来源；未保存服务回答')
        matches = []
        company_token = company_name.casefold().strip()
        for item in payload[:5]:
            if not isinstance(item, dict):
                continue
            title = item.get('title')
            content = item.get('content')
            target = item.get('url')
            if not all(isinstance(part, str) and part.strip() for part in (title, content, target)):
                continue
            title = title.strip()[:500]
            content = content.strip()[:12000]
            if not company_token or company_token not in (title + ' ' + content).casefold():
                continue
            try:
                target = public_url(target)
            except Problem:
                continue
            matches.append({'url':target, 'title':title, 'text':content,
                            'observed_at':time.time(), 'provider':'tavily'})
        if not matches:
            raise Problem('公开搜索暂未找到能明确关联这家公司的来源；请核对公司名称或提供官网公开页面', 502)
        return matches


def research_search_provider(settings, cancelled=None):
    """Create the selected public search provider from local companion settings."""
    from .company_research import PublicSearch
    settings = settings if isinstance(settings, dict) else {}
    if settings.get('search_provider') == 'tavily':
        return TavilySearch(settings.get('search_api_key', ''), cancelled=cancelled)
    return PublicSearch()
