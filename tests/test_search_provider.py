import io
import json
import time
import urllib.error
import unittest
from unittest.mock import patch

from app.api_transport import _NoRedirect, _search_blocking
from app.company_research import CompanyResearch, PublicSearch
from app.providers import complete
from app.search_provider import TavilySearch, research_search_provider
from app.store import Problem


class SearchProviderTests(unittest.TestCase):
    def test_factory_selects_public_or_tavily(self):
        self.assertIsInstance(research_search_provider({'search_provider':'public'}), PublicSearch)
        provider=research_search_provider({'search_provider':'tavily','search_api_key':'synthetic-key'})
        self.assertIsInstance(provider,TavilySearch)

    def test_tavily_uses_topic_only_query_and_keeps_sources_not_answer(self):
        marker='PRIVATE-PHRASE-13800000000'
        provider=TavilySearch('synthetic-key')
        result=json.dumps([
            {'title':'虚构公司产品与业务','url':'https://example.com/about','content':'虚构公司为门店提供软件服务。'},
            {'title':'另一家公司','url':'https://other.example/about','content':'另一家公司信息。'}],ensure_ascii=False)
        with patch('app.search_provider.complete',return_value=result) as transport:
            rows=provider.search('虚构公司',marker+' 主要做什么？',deadline=time.monotonic()+5)
        settings,query=transport.call_args.args[:2]
        self.assertEqual(settings['_operation'],'tavily_search')
        self.assertEqual(settings['_search_company'],'虚构公司')
        self.assertNotIn(marker,query)
        self.assertIn('虚构公司',query)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['provider'],'tavily')
        self.assertNotIn('answer',rows[0])

    def test_tavily_forwards_cancellation_and_rejects_elapsed_deadline(self):
        cancelled=lambda:False
        provider=TavilySearch('synthetic-key',cancelled=cancelled)
        raw=json.dumps([{'title':'虚构公司介绍','url':'https://example.com/about','content':'虚构公司公开业务来源内容。'}],ensure_ascii=False)
        with patch('app.search_provider.complete',return_value=raw) as transport:
            provider.search('虚构公司','业务背景',deadline=time.monotonic()+4)
        self.assertIs(transport.call_args.kwargs['cancelled'],cancelled)
        with patch('app.search_provider.complete') as transport:
            with self.assertRaises(Problem):
                provider.search('虚构公司','业务背景',deadline=time.monotonic()-1)
        transport.assert_not_called()

    def test_tavily_requires_company_relevant_source(self):
        provider=TavilySearch('synthetic-key')
        with patch('app.search_provider.complete',return_value=json.dumps([{'title':'词典','url':'https://example.com','content':'无关内容'}])):
            with self.assertRaises(Problem):provider.search('虚构公司','产品背景',deadline=time.monotonic()+5)

    def test_company_preview_keeps_tavily_provider_metadata(self):
        class Provider:
            def search(self,company,question,*,deadline):
                return [{'title':'虚构公司介绍','url':'https://example.com/about','text':'虚构公司公开业务资料。','observed_at':1,'provider':'tavily'}]
        preview=CompanyResearch(search_provider=Provider()).research('虚构公司','业务背景',allow_network=True)
        source=preview['sources'][0]
        self.assertEqual(source['source_type'],'public_search_excerpt')
        self.assertEqual(source['provider'],'tavily')
        self.assertEqual(source['title'],'虚构公司介绍')

    def test_transport_posts_bounded_source_only_request_to_fixed_endpoint(self):
        sentinel='TAVILY-SECRET-SENTINEL'
        source={'title':'Acme 产品介绍','url':'https://example.com/about','content':'Acme provides public business software.'}
        body=json.dumps({'answer':sentinel,'results':[source]},ensure_ascii=False).encode()
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,size):return body
        class Opener:
            def open(self,request,timeout):
                self.request=request;self.timeout=timeout
                return Response()
        opener=Opener()
        with patch('urllib.request.build_opener',return_value=opener) as build:
            result=_search_blocking({'search_api_key':sentinel,'_search_company':'Acme'},'Acme public business',3)
        value=json.loads(result)
        payload=json.loads(opener.request.data)
        self.assertEqual(opener.request.full_url,'https://api.tavily.com/search')
        self.assertEqual(opener.request.get_method(),'POST')
        self.assertEqual(opener.request.get_header('Authorization'),'Bearer '+sentinel)
        self.assertEqual(payload,{'query':'Acme public business','search_depth':'basic','max_results':5,
                                  'include_answer':False,'include_raw_content':False,'include_images':False})
        self.assertIs(build.call_args.args[0],_NoRedirect)
        self.assertEqual(len(value),1)
        self.assertNotIn(sentinel,result)

    def test_transport_hides_http_response_and_secret_from_errors(self):
        sentinel='TAVILY-SECRET-SENTINEL'
        def fail(request,timeout):
            raise urllib.error.HTTPError(request.full_url,500,'bad',{},io.BytesIO(sentinel.encode()))
        class Opener:
            open=staticmethod(fail)
        with patch('urllib.request.build_opener',return_value=Opener()):
            with self.assertRaises(Problem) as error:
                _search_blocking({'search_api_key':sentinel,'_search_company':'Acme'},'Acme business',3)
        self.assertNotIn(sentinel,str(error.exception))

    def test_complete_keeps_search_operation_inside_child_stdin_packet(self):
        class FakeProcess:
            def __init__(self,*args,**kwargs):
                class InputPipe(io.StringIO):
                    def close(pipe):pipe.saved=pipe.getvalue();super().close()
                self.stdin=InputPipe();self.stdout=io.StringIO('{"type":"result","text":"[]"}\n')
            def poll(self):return 0
            def terminate(self):pass
            def wait(self,timeout=None):pass
        process=FakeProcess()
        with patch('app.providers.subprocess.Popen',return_value=process):
            result=complete({'_operation':'tavily_search','search_api_key':'stdin-only'},'Acme business',
                            timeout=2,operation='tavily_search')
        request=json.loads(process.stdin.saved)
        self.assertEqual(result,'[]')
        self.assertEqual(request['operation'],'tavily_search')
        self.assertEqual(request['settings']['search_api_key'],'stdin-only')


if __name__=='__main__':unittest.main()
