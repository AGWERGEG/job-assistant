import json
import tempfile
import unittest
from app.store import Store, Problem
from app.companion import Companion
from app.mock_interview import MockInterview, SCHEMA
from app.journey import Journey


class MockInterviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.s=Store(self.temp.name);self.c=Companion(self.s);self.m=MockInterview(self.s)
        self.s.save_profile({'name':'虚构小林','facts':'姓名：虚构小林\n手机：13800000000\n邮箱：mock@example.com\n组织校园活动。'})
        self.c.save_settings({'api_key':'synthetic-secret','private_terms':'秘密学校'})
        self.c.approve({'token':self.c.preview_profile()['token'],'confirmed':True})
        self.job=self.s.save_job({'title':'运营','company':'虚构公司','jd':'负责活动执行与数据整理。'*5,'conversation':'不应该导出的HR消息'})

    def payload(self,pid):
        return {'schema':SCHEMA,'package_id':pid,'summary':'练习已结束','strengths':['表达清晰'],
                'improvements':['补充实际行动'],'next_steps':['练习自我介绍'],
                'turns':[{'question':'介绍一次活动','answer':'我的手机13800000000，曾组织校园活动','feedback':'需要补充细节'}]}

    def test_redacted_prompt_and_roundtrip_without_model_or_career_event(self):
        pkg=self.m.create_package({'job_id':self.job['id']})
        for sensitive in ('虚构小林','13800000000','mock@example.com','synthetic-secret','不应该导出的HR消息'):
            self.assertNotIn(sensitive,pkg['prompt'])
        self.assertIn('每轮只问一个问题',pkg['prompt']);self.assertIn(SCHEMA,pkg['prompt'])
        raw=json.dumps(self.payload(pkg['package_id']),ensure_ascii=False)
        preview=self.m.preview({'job_id':self.job['id'],'content':raw})
        self.assertNotIn('13800000000',json.dumps(preview))
        args={'job_id':self.job['id'],'content':raw,'preview_token':preview['preview_token'],'confirmed':True}
        imported=self.m.import_result(args);self.assertFalse(imported['duplicate'])
        self.assertTrue(self.m.import_result(args)['duplicate'])
        self.assertEqual(len(MockInterview(Store(self.temp.name)).records(self.job['id'])['records']),1)
        self.assertEqual(len(self.s.state()['tasks']),0)
        self.assertEqual(Journey(self.s).state()['events'],[])
        self.assertEqual(Journey(self.s).state()['facts'],[])

    def test_invalid_wrong_job_and_changed_preview_are_rejected(self):
        pkg=self.m.create_package({'job_id':self.job['id']})
        raw=json.dumps(self.payload(pkg['package_id']),ensure_ascii=False)
        with self.assertRaises(Problem):self.m.preview({'job_id':'wrong','content':raw})
        with self.assertRaises(Problem):self.m.preview({'job_id':self.job['id'],'content':'not json'})
        with self.assertRaises(Problem):self.m.import_result({'job_id':self.job['id'],'content':raw})
        p=self.m.preview({'job_id':self.job['id'],'content':raw})
        modified=self.payload(pkg['package_id']);modified['summary']='修改后的内容'
        with self.assertRaises(Problem):self.m.import_result({'job_id':self.job['id'],'content':json.dumps(modified),'preview_token':p['preview_token'],'confirmed':True})
        extra=self.payload(pkg['package_id']);extra['execute']='不要执行'
        with self.assertRaises(Problem):self.m.preview({'job_id':self.job['id'],'content':json.dumps(extra)})

    def test_fenced_json_stale_and_data_erasure(self):
        pkg=self.m.create_package({'job_id':self.job['id']})
        raw=chr(96)*3+'json\n'+json.dumps(self.payload(pkg['package_id']))+'\n'+chr(96)*3
        self.s.save_profile({'name':'虚构小林','facts':'更新后的校园经历。'})
        with self.assertRaises(Problem):self.m.create_package({'job_id':self.job['id']})
        p=self.m.preview({'job_id':self.job['id'],'content':raw});self.assertTrue(p['stale'])
        self.m.import_result({'job_id':self.job['id'],'content':raw,'preview_token':p['preview_token'],'confirmed':True})
        self.assertTrue(self.m.records(self.job['id'])['records'][0]['stale'])
        exported=json.loads(Journey(self.s).export_data())
        self.assertEqual(len(exported['mock_interview_results']),1)
        Journey(self.s).erase({'confirmation':'删除本机全部求职资料'})
        with self.s.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM mock_interview_packages').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM mock_interview_results').fetchone()[0],0)
