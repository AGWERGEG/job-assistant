import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from app.store import Store,Problem
from app.companion import Companion
from app.activity import Activity
from app.journey import Journey


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.s=Store(self.tmp.name);self.c=Companion(self.s);self.a=Activity(self.s)
        self.s.save_profile({'name':'虚构','facts':'真实活动协调经历','preferences':''})
        self.c.approve({'token':self.c.preview_profile()['token'],'confirmed':True})
        self.job=self.s.save_job({'title':'岗位A','jd':'协调活动','conversation':'首次招呼'})
        self.other=self.s.save_job({'title':'岗位B','jd':'整理信息'})

    def done(self,kind='tailor_resume'):
        t=self.s.create_task({'job_id':self.job['id'],'kind':kind});claim=self.s.claim(t['id'])
        self.s.finish(t['id'],claim['claim_token'],{'mode':'agent','producer':'test','summary':'完成','primary_output':'真实活动协调','markdown':'依据'})
        return self.s.get_task(t['id'])

    def test_viewed_is_persistent_reversible_and_version_checked(self):
        t=self.done();v={'task_id':t['id'],'result_updated':t['updated'],'viewed':True}
        self.a.viewed(v);self.a.viewed(v)
        self.assertTrue(Store(self.tmp.name).state()['tasks'][0]['viewed'])
        with self.assertRaises(Problem):self.a.viewed({**v,'result_updated':t['updated']-1})
        self.a.viewed({**v,'viewed':False});self.assertFalse(self.s.state()['tasks'][0]['viewed'])
        self.assertEqual(Journey(self.s).state()['events'],[])

    def test_running_and_short_chat_not_acknowledged(self):
        t=self.s.create_task({'job_id':self.job['id'],'kind':'analyze_job'})
        with self.assertRaises(Problem):self.a.viewed({'task_id':t['id'],'viewed':True,'result_updated':t['updated']})
        short=self.done('suggest_reply')
        with self.assertRaises(Problem):self.a.viewed({'task_id':short['id'],'viewed':True,'result_updated':short['updated']})

    def test_source_validation_confirmation_and_idempotency(self):
        t=self.done('suggest_reply');v={'source_type':'task','source_id':t['id'],'job_id':self.job['id'],'kind':'greeting_sent','confirmed':True}
        with self.assertRaises(Problem):self.a.record({**v,'confirmed':False})
        with self.assertRaises(Problem):self.a.record({**v,'job_id':self.other['id']})
        with self.assertRaises(Problem):self.a.record({**v,'kind':'joined'})
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:self.a.record(v),range(2)))
        self.assertEqual(len(Journey(self.s).state()['events']),1)
        self.assertCountEqual([r['already_recorded'] for r in results],[False,True])
        Journey(self.s).remove_event({'id':results[0]['event_id']})
        self.assertFalse(self.a.record(v)['already_recorded'])

    def test_only_accepted_version_can_record_application(self):
        t=self.done();v={'source_type':'version','source_id':t['id'],'job_id':self.job['id'],'kind':'applied','confirmed':True}
        with self.assertRaises(Problem):self.a.record(v)
        version=self.c.accept_resume({'task_id':t['id'],'content':'真实活动协调'})['id']
        self.assertEqual(Journey(self.s).state()['summary']['applications'],0)
        self.a.record({**v,'source_id':version})
        self.assertEqual(Journey(self.s).state()['summary']['applications'],1)

    def test_invitation_record_no_model_task_or_closing(self):
        v={'source_type':'job','source_id':self.job['id'],'job_id':self.job['id'],'kind':'interview','confirmed':True}
        self.a.record(v);self.assertEqual(self.s.state()['tasks'],[])
        with self.assertRaises(Problem):self.a.record({**v,'source_id':self.other['id']})

    def test_existing_store_migration_and_erasure(self):
        t=self.done();self.a.viewed({'task_id':t['id'],'result_updated':t['updated'],'viewed':True})
        Store(self.tmp.name)
        self.assertEqual(len(self.s.state()['tasks']),1)
        Journey(self.s).erase({'confirmation':'删除本机全部求职资料'})
        with self.s.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM result_views').fetchone()[0],0)


if __name__=='__main__':unittest.main()
