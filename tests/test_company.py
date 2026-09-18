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
        self.b=Bridge(self.s);self.client='chrome-extension://'+'a'*32
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


if __name__=='__main__':unittest.main()
