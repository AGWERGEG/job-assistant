import json
import tempfile
import unittest

from app.bridge import Bridge, safe_recruitment_url
from app.chat_links import chat_identity
from app.companion import Companion
from app.journey import Journey
from app.store import Problem, Store


class BlankAndLinksTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.companion = Companion(self.store)
        self.bridge = Bridge(self.store)
        self.client = 'chrome-extension://' + 'a' * 32

    @staticmethod
    def chat(name, company, title):
        return {'url':'https://www.zhipin.com/web/geek/chat',
                'recruiter_name':name,'company':company,'job_title':title}

    def test_blank_profile_only_allows_job_first_chat(self):
        job = self.store.save_job({'title': '测试岗位', 'jd': '负责客户沟通与需求整理。'})
        with self.assertRaises(Problem):
            self.store.create_task({'kind': 'quick_analysis', 'job_id': job['id']})
        self.companion.onboarding_action({'action': 'blank-profile'})
        self.assertEqual(self.companion.readiness_state()['state'], 'privacy_required')
        preview = self.companion.preview_profile()
        self.companion.approve({'token': preview['token'], 'confirmed': True})
        self.assertEqual(self.companion.readiness_state()['state'], 'profile_optional')
        task = self.store.create_task({'kind': 'quick_analysis', 'job_id': job['id']})
        self.assertEqual(task['kind'], 'quick_analysis')
        with self.assertRaises(Problem):
            self.store.create_task({'kind': 'tailor_resume', 'job_id': job['id']})

    def test_link_record_and_manual_switch(self):
        first = self.store.save_job({'title':'甲岗位','company':'甲公司','url':'https://www.zhipin.com/job_detail/abcd1234.html','jd':'JD A'})
        second = self.store.save_job({'title':'乙岗位','company':'乙公司','url':'https://www.zhipin.com/job_detail/efgh5678.html','jd':'JD B'})
        jobs = self.bridge.jobs(self.client, {'scope':'tab'})['jobs']
        self.assertEqual({j['id'] for j in jobs}, {first['id'], second['id']})
        selected = self.bridge.select(self.client, {'scope':'tab','seq':1,'job_id':first['id']})
        self.assertEqual(selected['job']['id'], first['id'])
        chat = self.chat('甲先生','甲公司','甲岗位')
        link = self.bridge.link_save(self.client, {'scope':'tab','seq':1,'job_id':first['id'],'chat':chat})['link']
        self.assertEqual(self.bridge.link_context(self.client, {'scope':'tab','chat':chat})['link']['job_id'], first['id'])
        self.bridge.select(self.client, {'scope':'tab','seq':2,'job_id':second['id']})
        with self.assertRaises(Problem):
            self.bridge.link_save(self.client, {'scope':'tab','seq':2,'job_id':second['id'],'chat':chat})
        self.assertEqual(len(self.store.list_job_links(first['id'])), 2)

    def test_same_boss_chat_url_identifies_each_contact_and_allows_rebind(self):
        first=self.store.save_job({'title':'技术支持','company':'甲公司','url':'https://www.zhipin.com/job_detail/abcd1234.html','jd':'JD A'})
        second=self.store.save_job({'title':'产品经理','company':'乙公司','url':'https://www.zhipin.com/job_detail/efgh5678.html','jd':'JD B'})
        a=self.chat('张先生','甲公司','技术支持')
        b=self.chat('李女士','乙公司','产品经理')
        self.assertNotEqual(chat_identity(a)['key'],chat_identity(b)['key'])
        self.bridge.select(self.client,{'scope':'tab','seq':1,'job_id':first['id']})
        self.bridge.link_save(self.client,{'scope':'tab','seq':1,'job_id':first['id'],'chat':a})
        self.assertIsNone(self.bridge.link_context(self.client,{'scope':'tab','chat':b})['link'])
        self.assertEqual(self.bridge.link_context(self.client,{'scope':'tab','chat':b})['matches'][0]['id'],second['id'])
        self.bridge.select(self.client,{'scope':'tab','seq':2,'job_id':second['id']})
        self.bridge.link_save(self.client,{'scope':'tab','seq':2,'job_id':second['id'],'chat':b})
        self.assertEqual(self.bridge.link_context(self.client,{'scope':'tab','chat':b})['link']['job_id'],second['id'])
        self.bridge.link_unbind(self.client,{'scope':'tab','job_id':second['id'],'chat':b})
        self.assertIsNone(self.bridge.link_context(self.client,{'scope':'tab','chat':b})['link'])
        self.bridge.link_save(self.client,{'scope':'tab','seq':2,'job_id':second['id'],'chat':b})
        self.assertEqual(self.bridge.link_context(self.client,{'scope':'tab','chat':b})['link']['job_id'],second['id'])

    def test_company_title_and_recruiter_evidence_block_false_binding(self):
        job=self.store.save_job({'title':'技术支持','company':'甲公司','url':'https://www.zhipin.com/job_detail/abcd1234.html','jd':'JD A'})
        self.store.save_job_recruiter(job['id'],'张先生',job['url'])
        self.bridge.select(self.client,{'scope':'tab','seq':1,'job_id':job['id']})
        for wrong in (self.chat('李先生','甲公司','技术支持'),
                      self.chat('张先生','乙公司','技术支持'),
                      self.chat('张先生','甲公司','产品经理')):
            self.assertEqual(self.bridge.link_context(self.client,{'scope':'tab','chat':wrong})['matches'],[])
            with self.assertRaisesRegex(Problem,'关联核验失败'):
                self.bridge.link_save(self.client,{'scope':'tab','seq':1,'job_id':job['id'],'chat':wrong})
        self.assertEqual(self.store.list_job_links(job['id'])[0]['kind'],'job_detail')

    def test_old_jd_online_badge_does_not_block_verified_chat_binding(self):
        job=self.store.save_job({'title':'销售经理（全国分配） (MJ009897)','company':'示例科技',
                                 'url':'https://www.zhipin.com/job_detail/abcd1234.html','jd':'JD'})
        self.store.save_job_recruiter(job['id'],'陈先生\n在线',job['url'])
        chat={**self.chat('陈先生','示例科技','销售经理（全国分配）（MJ009897）'),
              'job_url':job['url']}
        self.assertEqual([row['id'] for row in self.bridge.link_context(self.client,{'scope':'tab','chat':chat})['matches']],[job['id']])
        self.bridge.select(self.client,{'scope':'tab','seq':1,'job_id':job['id']})
        self.bridge.link_save(self.client,{'scope':'tab','seq':1,'job_id':job['id'],'chat':chat})
        self.assertEqual(self.bridge.link_context(self.client,{'scope':'tab','chat':chat})['link']['job_id'],job['id'])
        self.assertEqual(self.bridge.link_context(self.client,{'scope':'tab','chat':self.chat('李先生','示例科技','销售经理（全国分配）（MJ009897）')})['matches'],[])

    def test_link_domain_is_checked(self):
        for url in ('https://zhipin.com.evil.test/web/geek/chat', 'http://www.zhipin.com/web/geek/chat', 'https://www.zhipin.com:invalid/web/geek/chat'):
            with self.assertRaises(Problem):
                safe_recruitment_url(url, 'hr_chat')

    def test_chat_job_url_disambiguates_identical_company_and_title(self):
        first=self.store.save_job({'title':'技术支持','company':'甲公司','url':'https://www.zhipin.com/job_detail/abcd1234.html','jd':'JD A'})
        second=self.store.save_job({'title':'技术支持','company':'甲公司','url':'https://www.zhipin.com/job_detail/efgh5678.html','jd':'JD B'})
        chat={**self.chat('张先生','甲公司','技术支持'),'job_url':second['url']}
        self.assertNotEqual(chat_identity(chat)['key'],chat_identity({**chat,'job_url':first['url']})['key'])
        matches=self.bridge.link_context(self.client,{'scope':'tab','chat':chat})['matches']
        self.assertEqual([row['id'] for row in matches],[second['id']])
        self.bridge.select(self.client,{'scope':'tab','seq':1,'job_id':first['id']})
        with self.assertRaisesRegex(Problem,'岗位链接'):
            self.bridge.link_save(self.client,{'scope':'tab','seq':1,'job_id':first['id'],'chat':chat})

    def test_binding_must_be_removed_before_switching_to_another_matching_record(self):
        first=self.store.save_job({'title':'技术支持','company':'甲公司','url':'https://www.zhipin.com/job_detail/abcd1234.html','jd':'JD A'})
        second=self.store.save_job({'title':'技术支持','company':'甲公司','url':'https://www.zhipin.com/job_detail/efgh5678.html','jd':'JD B'})
        chat=chat_identity(self.chat('张先生','甲公司','技术支持'))
        self.store.bind_chat(chat,first['id'])
        with self.assertRaisesRegex(Problem,'先解绑'):
            self.store.bind_chat(chat,second['id'])
        self.store.unbind_chat(chat['key'],first['id'])
        self.store.bind_chat(chat,second['id'])
        self.assertEqual(self.store.chat_binding(chat['key'])['job_id'],second['id'])

    def test_link_records_are_exported_and_erased(self):
        job = self.store.save_job({'title': '测试岗位', 'company': '虚构公司',
                                   'url': 'https://www.zhipin.com/job_detail/abcd1234.html', 'jd': '测试 JD'})
        self.store.bind_chat(chat_identity(self.chat('张先生','虚构公司','测试岗位')),job['id'])
        journey = Journey(self.store)
        exported = json.loads(journey.export_data())
        self.assertEqual({link['kind'] for link in exported['job_links']}, {'job_detail'})
        self.assertEqual(len(exported['hr_chat_bindings']),1)
        journey.erase({'confirmation': '删除本机全部求职资料'})
        self.assertEqual(self.store.list_job_links(), [])
        self.assertEqual(self.store.chat_binding(chat_identity(self.chat('张先生','虚构公司','测试岗位'))['key']),None)

    def test_old_generic_url_record_is_kept_but_never_auto_matched(self):
        job=self.store.save_job({'title':'技术支持','company':'甲公司','url':'https://www.zhipin.com/job_detail/abcd1234.html','jd':'JD A'})
        with self.store.connect() as db:
            db.execute('INSERT INTO job_links VALUES(?,?,?,?,?,?,?,?,?)',
                       ('old-link',job['id'],'hr_chat','https://www.zhipin.com/web/geek/chat',
                        job['title'],job['company'],'boss',1,1))
        other=self.chat('李女士','乙公司','产品经理')
        result=self.bridge.link_context(self.client,{'scope':'tab','chat':other})
        self.assertIsNone(result['link'])
        self.assertTrue(result['legacy'])
        self.assertIn('hr_chat_legacy', {link['kind'] for link in self.store.list_job_links(job['id'])})


if __name__ == '__main__':
    unittest.main()
