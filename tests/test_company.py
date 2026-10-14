from app.version import EXTENSION_ID
import json
import tempfile
import unittest
from app.store import Store, Problem
from app.bridge import Bridge
from app.company import Company
from app.companion import Companion
from app.worker import prompt_for


class CompanyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.s=Store(self.tmp.name);self.s.save_profile({'name':'测试姓名','facts':'做过客户沟通和校园活动','preferences':'杭州'})
        self.b=Bridge(self.s);self.client='chrome-extension://'+EXTENSION_ID
        self.ref={'company_key':'companyA~','company_url':'https://www.zhipin.com/gongsi/companyA~.html'}
        capture={**self.ref,'job_key':'job1234','url':'https://www.zhipin.com/job_detail/job1234.html','title':'销售','company':'公司A','jd':'负责商家软件销售、客户需求沟通、签约与回款，要求良好沟通能力。'*3}
        self.job=self.b.capture(self.client,{'scope':'s','seq':1,'capture':capture})['job']
        self.b.companion_action(self.client,{'scope':'s','seq':1},'confirm')
        self.c=Company(self.s)

    def data(self):
        return {**self.ref,'name':'公司A','source_url':self.ref['company_url']+'?ka=secret','sections':[{'kind':'introduction','text':'公司为商家提供软件服务，产品涵盖门店管理和电商经营。','partial':False}],'jobs':[],'categories':[]}

    def test_company_material_enters_all_task_kinds_and_deduplicates(self):
        first=self.c.ingest(self.job['id'],self.data())
        second=self.c.ingest(self.job['id'],self.data())
        self.assertEqual(first['revision'],second['revision'])
        self.assertEqual(len(second['evidence']),1)
        self.assertNotIn('secret',second['evidence'][0]['source_url'])
        for kind in ('analyze_job','tailor_resume','suggest_reply','quick_analysis','companion_chat','interview_prep','interview_review'):
            t=self.s.create_task({'kind':kind,'job_id':self.job['id']},conversation_override='写首次招呼')
            ctx=self.s.get_task(t['id'])['context']
            self.assertEqual(ctx['company_background']['company_key'],'companyA~')
            self.assertIn('门店管理',prompt_for(self.s.get_task(t['id'])))

    def test_other_company_and_wrong_source_rejected(self):
        data=self.data();data.update(company_key='companyB~',company_url='https://www.zhipin.com/gongsi/companyB~.html',source_url='https://www.zhipin.com/gongsi/companyB~.html')
        with self.assertRaises(Problem):self.c.ingest(self.job['id'],data)
        data=self.data();data['source_url']='https://www.zhipin.com/gongsi/companyB~.html'
        with self.assertRaises(Problem):self.c.ingest(self.job['id'],data)
        self.assertEqual(self.c.read(self.job['id'])['evidence'],[])

    def test_peer_is_evidence_not_target_and_company_update_preserves_task_snapshot(self):
        data=self.data();data['source_url']='https://www.zhipin.com/gongsi/job/companyA~.html'
        data['peer']={'company_key':'companyA~','job_key':'peer123','url':'https://www.zhipin.com/job_detail/peer123.html','title':'实施顾问','jd':'负责签约后实施与客户培训，和销售及客户成功团队协作。'}
        self.c.ingest(self.job['id'],data)
        t=self.s.create_task({'kind':'analyze_job','job_id':self.job['id']})
        before=self.s.get_task(t['id'])['context']
        data['sections'][0]['text']='更新后的公司介绍'
        self.c.ingest(self.job['id'],data)
        self.assertEqual(before,self.s.get_task(t['id'])['context'])
        self.assertEqual(len(self.s.state()['jobs']),1)
        self.assertIn('实施顾问',json.dumps(before,ensure_ascii=False))
        self.assertEqual(self.b.scopes[self.b._scope(self.client,{'scope':'s'})]['job_id'],self.job['id'])

    def test_categories_are_reported_counts_not_collected_jobs(self):
        data=self.data();data.update(source_url='https://www.zhipin.com/gongsi/job/160000/companyA~.html',sections=[],categories=['全部(559)','销售(280)'],jobs=[{'job_key':'peer123','url':'https://www.zhipin.com/job_detail/peer123.html','title':'售前顾问','salary':'10-20K'}],filters='工作城市：杭州')
        d=self.c.ingest(self.job['id'],data)
        row=d['evidence'][0]
        self.assertEqual(len(row['jobs']),1);self.assertEqual(row['categories'],['全部(559)','销售(280)'])
        self.assertIn('未读取全部',row['coverage'])

    def test_bridge_requires_pair_scope_confirmation_for_company_save(self):
        with self.assertRaises(Problem):self.b.companion_action(self.client,{'scope':'other','seq':1,'company':self.data()},'company-save')
        result=self.b.companion_action(self.client,{'scope':'s','seq':1,'company':self.data()},'company-save')
        self.assertEqual(result['company']['company_key'],'companyA~')

    def test_versioned_company_evidence_not_clobbered_by_duplicate(self):
        data=self.data();a=self.c.ingest(self.job['id'],data)
        data['sections'][0]['text']='新的产品说明，已补充客户服务范围。'
        b=self.c.ingest(self.job['id'],data)
        self.assertGreater(b['revision'],a['revision'])
        self.assertEqual(len(b['evidence']),1)
        with self.s.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM company_evidence').fetchone()[0],2)

    def test_zhaopin_company_identity_and_evidence_are_site_scoped(self):
        ref={'source_site':'zhaopin','company_key':'zhaopin:CZ123456','company_url':'https://www.zhaopin.com/companydetail/CZ123456.htm'}
        capture={**ref,'job_key':'JOB123456','url':'https://www.zhaopin.com/jobdetail/JOB123456.htm','title':'实施顾问','company':'虚构智联公司','jd':'负责软件实施、客户培训和项目上线，跟进问题并整理验收资料。'*3}
        job=self.b.capture(self.client,{'scope':'zhaopin','seq':1,'capture':capture})['job']
        self.b.companion_action(self.client,{'scope':'zhaopin','seq':1},'confirm')
        data={**ref,'name':'虚构智联公司','source_url':ref['company_url']+'?tracking=discarded','sections':[{'kind':'introduction','text':'虚构企业为客户提供经营管理软件与实施服务。','partial':False}],'jobs':[],'categories':[]}
        result=self.c.ingest(job['id'],data)
        self.assertEqual(result['company_key'],ref['company_key'])
        self.assertEqual(result['evidence'][0]['source_url'],ref['company_url'])
        self.assertIn('经营管理软件',result['evidence'][0]['text'])
        bad={**data,'company_url':'https://www.zhaopin.com/companydetail/CZ654321.htm','source_url':'https://www.zhaopin.com/companydetail/CZ654321.htm'}
        with self.assertRaises(Problem):self.c.ingest(job['id'],bad)
        bad={**data,'company_key':'CZ123456','source_site':'boss'}
        with self.assertRaises(Problem):self.c.ingest(job['id'],bad)

    def test_zhaopin_loaded_company_cards_enter_next_analysis(self):
        ref={'source_site':'zhaopin','company_key':'zhaopin:CZL123456','company_url':'https://www.zhaopin.com/companydetail/CZL123456.htm'}
        capture={**ref,'job_key':'CCL123456J000','url':'https://www.zhaopin.com/jobdetail/CCL123456J000.htm','title':'售前工程师','company':'虚构智联公司','jd':'负责客户需求分析、产品演示及试用支持，协同团队完成方案说明。'*3}
        job=self.b.capture(self.client,{'scope':'zhaopin-cards','seq':1,'capture':capture})['job']
        self.b.companion_action(self.client,{'scope':'zhaopin-cards','seq':1},'confirm')
        data={**ref,'name':'虚构智联公司','source_url':'https://www.zhaopin.com/companydetail/jobs-CZL123456/?p=1','sections':[],'jobs':[{'job_key':'CCL123456J001','url':'https://www.zhaopin.com/jobdetail/CCL123456J001.htm?refcode=discard','title':'客户成功顾问','salary':'9000-13000元','conditions':'杭州 大专'}],'categories':[]}
        first=self.b.companion_action(self.client,{'scope':'zhaopin-cards','seq':1,'company':data},'company-save')['company']
        second=self.b.companion_action(self.client,{'scope':'zhaopin-cards','seq':1,'company':data},'company-save')['company']
        self.assertEqual(first['revision'],second['revision'])
        evidence=second['evidence'][0]
        self.assertEqual(evidence['kind'],'recruitment')
        self.assertEqual(evidence['source_url'],'https://www.zhaopin.com/companydetail/jobs-CZL123456/')
        self.assertEqual(evidence['jobs'][0]['url'],'https://www.zhaopin.com/jobdetail/CCL123456J001.htm')
        peer_url='https://www.zhaopin.com/jobdetail/CCL123456J002.htm'
        peer={**ref,'name':'虚构智联公司','source_url':peer_url,'sections':[],'jobs':[],'categories':[],
              'peer':{'company_key':ref['company_key'],'job_key':'CCL123456J002','url':peer_url,'title':'产品实施顾问','jd':'负责客户上线实施、培训与验收，和售前团队协作。'}}
        with_peer=self.b.companion_action(self.client,{'scope':'zhaopin-cards','seq':1,'company':peer},'company-save')['company']
        self.assertEqual({item['kind'] for item in with_peer['evidence']},{'recruitment','peer_job'})
        task=self.s.create_task({'kind':'analyze_job','job_id':job['id']})
        self.assertIn('客户成功顾问',prompt_for(self.s.get_task(task['id'])))
        self.assertIn('产品实施顾问',prompt_for(self.s.get_task(task['id'])))
        self.assertEqual(self.s.get_task(task['id'])['context']['job']['id'],job['id'])
        wrong={**data,'source_url':'https://www.zhaopin.com/companydetail/jobs-CZL999999/'}
        with self.assertRaises(Problem):self.c.ingest(job['id'],wrong)


if __name__=='__main__':unittest.main()
