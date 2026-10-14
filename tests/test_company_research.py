import tempfile
import unittest
import json
import threading
import time
import urllib.request
import urllib.error
from app.store import Store, Problem
from app.bridge import Bridge
from app.company import Company
from app.company_research import CompanyResearch, PublicSearch, public_search_query, public_url
from app.server import make_server
from app.journey import Journey


class FakeHTTP:
    def __init__(self): self.calls = []
    def get(self, url, *, deadline):
        self.calls.append(url)
        return {'url': url, 'text': '<html><title>公司官网</title><p>提供门店管理软件和支付服务。</p></html>',
                'content_type': 'text/html', 'observed_at': 1700000000.0}


class CompanyResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.store.save_profile({'name': '测试', 'facts': '', 'preferences': ''})
        bridge = Bridge(self.store); client = 'chrome-extension://' + 'b' * 32
        ref = {'company_key': 'companyA~', 'company_url': 'https://www.zhipin.com/gongsi/companyA~.html'}
        job = bridge.capture(client, {'scope': 'r', 'seq': 1, 'capture': {**ref, 'job_key': 'job1234', 'url': 'https://www.zhipin.com/job_detail/job1234.html', 'title': '销售', 'company': '公司A', 'jd': '负责销售。' * 20}})['job']
        bridge.companion_action(client, {'scope': 'r', 'seq': 1}, 'confirm')
        self.job_id = job['id']; self.company = Company(self.store); self.http = FakeHTTP()
        self.research = CompanyResearch(self.company, http=self.http)

    def test_preview_requires_network_opt_in_and_reports_missing_provider(self):
        result = self.research.research('公司A', '产品和业务是什么？')
        self.assertFalse(result['sources'])
        self.assertTrue(any('当前没有可用公开搜索' in w for w in result['warnings']))
        result = self.research.research('公司A', '产品是什么？', public_urls=['https://example.com/about'])
        self.assertEqual(self.http.calls, [])
        self.assertTrue(any('尚未授权公开联网' in w for w in result['warnings']))

    def test_public_page_preview_and_explicit_confirmation_persist_provenance(self):
        result = self.research.research('公司A', '产品是什么？', job_id=self.job_id, public_urls=['https://example.com/about'], allow_network=True)
        self.assertEqual(len(result['sources']), 1)
        source = result['sources'][0]
        self.assertEqual(source['source_type'], 'public_web_page')
        self.assertEqual(source['confidence'], 'unverified')
        with self.assertRaises(Problem):
            self.research.confirm(self.job_id, result['preview_id'])
        dossier = self.research.confirm(self.job_id, result['preview_id'], confirmed=True)
        evidence = [e for e in dossier['evidence'] if e['kind'] == 'research'][0]
        self.assertEqual(evidence['source_type'], 'public_web_page')
        self.assertEqual(evidence['observed_at'], 1700000000.0)
        self.assertEqual(evidence['confidence'], 'unverified')

    def test_public_url_rejects_private_and_recruiting_sites(self):
        for value in ('http://example.com', 'https://127.0.0.1/x', 'https://localhost/x', 'https://www.zhipin.com/gongsi/a.html'):
            with self.assertRaises(Problem): public_url(value)

    def test_saved_and_new_search_sources_can_be_confirmed_without_duplicates(self):
        class Search:
            offset = 0
            def search(self, name, question, *, deadline):
                return [{'url':f'https://example.com/source{i}', 'text':f'公司A产品来源{i}',
                         'title':f'公司A产品{i}', 'observed_at':1700000000.0}
                        for i in range(self.offset,self.offset+5)]
        provider=Search();service=CompanyResearch(self.company,search_provider=provider)
        first=service.research('公司A','产品？',job_id=self.job_id,allow_network=True)
        service.confirm(self.job_id,first['preview_id'],confirmed=True)
        provider.offset=5
        second=service.research('公司A','产品？',job_id=self.job_id,allow_network=True)
        self.assertEqual(len(second['sources']),10)
        self.assertTrue(all(not source['already_saved'] for source in second['sources'][:5]))
        saved=service.confirm(self.job_id,second['preview_id'],confirmed=True)
        self.assertEqual(len(saved['evidence']),10)
        third=service.research('公司A','产品？',job_id=self.job_id,allow_network=True)
        self.assertEqual(len(third['sources']),5)
        self.assertTrue(all(source['already_saved'] for source in third['sources']))
        self.assertEqual(service.confirm(self.job_id,third['preview_id'],confirmed=True)['revision'],saved['revision'])

    def test_confirm_requires_bound_job_and_source_url(self):
        with self.assertRaises(Problem):
            self.company.confirm_research('missing', {'sources': []}, confirmed=True)

    def test_first_confirmation_without_manual_company_material_is_job_scoped(self):
        target = self.store.save_job({'title':'虚构岗位','company':'独立虚构公司','url':'','jd':'虚构岗位职责描述足够长。'*10})
        service = CompanyResearch(self.company, http=self.http)
        preview = service.research('独立虚构公司','主要业务？',job_id=target['id'],public_urls=['https://example.com/about'],allow_network=True)
        saved = service.confirm(target['id'],preview['preview_id'],confirmed=True)
        self.assertEqual(saved['name'],'独立虚构公司')
        self.assertEqual(saved['evidence'][0]['kind'],'research')
        other = self.store.save_job({'title':'另一虚构岗位','company':'独立虚构公司','url':'','jd':'另一虚构岗位职责描述足够长。'*10})
        self.assertIsNone(self.company.read(other['id']))
        self.store.save_job({**target,'company':'另一家公司'})
        self.assertIsNone(self.company.read(target['id']))
        self.store.save_job(target)
        self.assertEqual(self.company.read(target['id'])['name'],'独立虚构公司')
        self.store.save_job({**target,'url':'https://example.com/new-job'})
        self.assertIsNone(self.company.read(target['id']))

    def test_stale_job_preview_is_rejected(self):
        preview = self.research.research('公司A','产品是什么？',job_id=self.job_id,public_urls=['https://example.com/about'],allow_network=True)
        job = next(item for item in self.store.state()['jobs'] if item['id']==self.job_id)
        self.store.save_job({**job,'title':'修改后的虚构岗位'})
        with self.assertRaises(Problem) as error:
            self.research.confirm(self.job_id,preview['preview_id'],confirmed=True)
        self.assertEqual(error.exception.status,409)

    def test_changed_company_identity_invalidates_preview(self):
        preview=self.research.research('公司A','产品是什么？',job_id=self.job_id,public_urls=['https://example.com/about'],allow_network=True)
        with self.store.connect() as db:
            db.execute("UPDATE companies SET name='另一虚构公司' WHERE company_key='companyA~'")
        with self.assertRaises(Problem) as error:
            self.research.confirm(self.job_id,preview['preview_id'],confirmed=True)
        self.assertEqual(error.exception.status,409)

    def test_public_page_excerpt_keeps_business_lines_after_navigation(self):
        from app.company_research import _relevant_excerpt
        nav=' '.join(['导航链接']*15000)
        page='<html><body><nav>'+nav+'</nav><main><p>公司A的产品为商户提供门店管理软件和订单服务。</p><p>公司A主要业务是为客户提供经营管理解决方案。</p></main></body></html>'
        excerpt=_relevant_excerpt(page,'公司A','产品与业务')
        self.assertLess(len(excerpt),20000)
        self.assertIn('门店管理软件',excerpt)
        self.assertIn('经营管理解决方案',excerpt)

    def test_expired_preview_is_rejected(self):
        preview=self.research.research('公司A','产品是什么？',job_id=self.job_id,public_urls=['https://example.com/about'],allow_network=True)
        self.research._previews[preview['preview_id']]['created_at']-=601
        with self.assertRaises(Problem) as error:
            self.research.confirm(self.job_id,preview['preview_id'],confirmed=True)
        self.assertEqual(error.exception.status,409)

    def test_saved_boss_evidence_is_preserved_when_confirming_new_source(self):
        self.company.ingest(self.job_id,{'company_key':'companyA~','company_url':'https://www.zhipin.com/gongsi/companyA~.html','name':'公司A','source_url':'https://www.zhipin.com/gongsi/companyA~.html','sections':[{'kind':'introduction','text':'既有 BOSS 公司介绍','partial':False}]})
        preview = self.research.research('公司A','产品是什么？',job_id=self.job_id,public_urls=['https://example.com/about'],allow_network=True)
        saved = self.research.confirm(self.job_id,preview['preview_id'],confirmed=True)
        self.assertTrue(any(e.get('text')=='既有 BOSS 公司介绍' for e in saved['evidence']))
        self.assertTrue(any(e.get('source_type')=='public_web_page' for e in saved['evidence']))

    def test_public_search_never_sends_private_question_text(self):
        marker='私密短语-用户电话13800000000'
        query=public_search_query('虚构公司',f'{marker} 主要做什么？')
        self.assertIn('虚构公司',query)
        self.assertNotIn(marker,query)
        self.assertEqual(query,'虚构公司 业务')
        class SearchHTTP:
            def __init__(self):self.url=''
            def get(self,url,*,deadline):
                self.url=url
                return {'url':url,'text':'<rss><channel><item><title>无关资讯</title><link>https://example.com/news</link><description>完全无关的网页内容</description></item></channel></rss>','observed_at':1}
        http=SearchHTTP()
        with self.assertRaises(Problem):
            PublicSearch(http).search('虚构公司',marker+' 主要做什么？',deadline=999999999)
        self.assertNotIn(marker,http.url)

    def test_public_search_retries_company_only_when_topics_lose_identity(self):
        from urllib.parse import parse_qs, urlsplit
        class SearchHTTP:
            def __init__(self): self.calls=[]
            def get(self,url,*,deadline):
                self.calls.append((parse_qs(urlsplit(url).query)['q'][0],deadline))
                title='有的意思' if len(self.calls)==1 else '有赞产品与业务'
                return {'url':url,'text':f'<rss><channel><item><title>{title}</title><link>https://example.com/about</link><description>公开的产品业务介绍及客户服务说明</description></item></channel></rss>','observed_at':1}
        http=SearchHTTP();deadline=time.monotonic()+20
        result=PublicSearch(http).search('有赞','私密经历-电话13800000000 产品与业务',deadline=deadline)
        self.assertEqual([call[0] for call in http.calls],['"有赞" 产品 业务','"有赞"'])
        self.assertEqual([call[1] for call in http.calls],[deadline,deadline])
        self.assertEqual(result[0]['title'],'有赞产品与业务')

    def test_public_search_does_not_retry_success_or_extend_expired_deadline(self):
        class SearchHTTP:
            def __init__(self): self.calls=0
            def get(self,url,*,deadline):
                self.calls+=1
                return {'url':url,'text':'<rss><channel><item><title>公司A产品</title><link>https://example.com/about</link><description>公司A公开产品介绍与客户服务说明</description></item></channel></rss>','observed_at':1}
        http=SearchHTTP()
        self.assertEqual(len(PublicSearch(http).search('公司A','产品',deadline=time.monotonic()+20)),1)
        self.assertEqual(http.calls,1)
        with self.assertRaisesRegex(Problem,'超时'):
            PublicSearch(http).search('公司A','产品',deadline=time.monotonic()-1)
        self.assertEqual(http.calls,1)

    def test_http_confirmation_uses_server_preview_token_and_cancel_expires_it(self):
        server=make_server(self.tmp.name,0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(lambda:(server.shutdown(),server.server_close(),thread.join(timeout=2)))
        base=f'http://127.0.0.1:{server.server_port}'
        def post(path,value,token):
            req=urllib.request.Request(base+path,data=json.dumps(value).encode(),headers={'Content-Type':'application/json','X-Local-Token':token})
            with urllib.request.urlopen(req) as response:return json.loads(response.read())
        token=server.session_token
        response=post('/api/company-research',{'job_id':self.job_id,'company_name':'伪造公司名','question':'产品是什么？','public_urls':['https://example.com/about'],'allow_network':True},token)
        self.assertEqual(response['company_name'],'公司A')
        fake={'preview_id':response['preview_id'],'question':'伪造客户端正文','sources':[{'url':'https://attacker.example','excerpt':'伪造事实','observed_at':1,'source_type':'public_web_page','confidence':'verified'}]}
        saved=post('/api/company-research-confirm',{'job_id':self.job_id,'preview_id':response['preview_id'],'research':fake,'confirmed':True},token)['company']
        self.assertNotIn('伪造事实',json.dumps(saved,ensure_ascii=False))
        again=post('/api/company-research-confirm',{'job_id':self.job_id,'preview_id':response['preview_id'],'confirmed':True},token)['company']
        self.assertEqual(again['revision'],saved['revision'])
        second=post('/api/company-research',{'job_id':self.job_id,'question':'产品是什么？','public_urls':['https://example.com/about'],'allow_network':True},token)
        post('/api/company-research-discard',{'job_id':self.job_id,'preview_id':second['preview_id']},token)
        request=urllib.request.Request(base+'/api/company-research-confirm',data=json.dumps({'job_id':self.job_id,'preview_id':second['preview_id'],'confirmed':True}).encode(),headers={'Content-Type':'application/json','X-Local-Token':token})
        with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request)
        self.assertEqual(error.exception.code,409)

    def test_http_preview_cannot_be_confirmed_for_another_job(self):
        server=make_server(self.tmp.name,0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(lambda:(server.shutdown(),server.server_close(),thread.join(timeout=2)))
        base=f'http://127.0.0.1:{server.server_port}'
        token=server.session_token
        other=self.store.save_job({'title':'另一虚构岗位','company':'公司A','url':'','jd':'另一岗位职责描述足够长。'*10})
        def post(path,value):
            request=urllib.request.Request(base+path,data=json.dumps(value).encode(),headers={'Content-Type':'application/json','X-Local-Token':token})
            return urllib.request.urlopen(request)
        preview=json.loads(post('/api/company-research',{'job_id':self.job_id,'question':'产品是什么？','public_urls':['https://example.com/about'],'allow_network':True}).read())
        request=urllib.request.Request(base+'/api/company-research-confirm',data=json.dumps({'job_id':other['id'],'preview_id':preview['preview_id'],'confirmed':True}).encode(),headers={'Content-Type':'application/json','X-Local-Token':token})
        with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request)
        self.assertEqual(error.exception.code,409)

    def test_job_scoped_research_is_exported_and_deleted(self):
        target=self.store.save_job({'title':'虚构岗位','company':'独立虚构公司','url':'','jd':'虚构岗位职责描述足够长。'*10})
        service=CompanyResearch(self.company,http=self.http)
        preview=service.research('独立虚构公司','业务是什么？',job_id=target['id'],public_urls=['https://example.com/about'],allow_network=True)
        service.confirm(target['id'],preview['preview_id'],confirmed=True)
        exported=json.loads(Journey(self.store).export_data())
        self.assertEqual(exported['job_company_research'][0]['job_id'],target['id'])
        Journey(self.store).erase({'confirmation':'删除本机全部求职资料'})
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM job_company_research').fetchone()[0],0)


if __name__ == '__main__': unittest.main()


class SearchSettingsTests(unittest.TestCase):
    def test_search_credential_is_local_write_only_and_not_in_export(self):
        from app.companion import Companion
        from app.journey import Journey
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);c=Companion(store)
            c.save_settings({'search_provider':'tavily','search_api_key':'search-secret-sentinel'})
            self.assertEqual(c.settings()['search_api_key'],'search-secret-sentinel')
            public=c.settings(public=True)
            self.assertTrue(public['has_search_api_key'])
            self.assertNotIn('search_api_key',public)
            self.assertNotIn('search-secret-sentinel',json.dumps(public))
            self.assertNotIn(b'search-secret-sentinel',Journey(store).export_data())
            c.save_settings({'search_api_key':''});self.assertTrue(c.settings(public=True)['has_search_api_key'])
            c.save_settings({'clear_search_api_key':True});self.assertFalse(c.settings(public=True)['has_search_api_key'])
            with self.assertRaises(Problem):c.save_settings({'search_provider':'unknown'})
