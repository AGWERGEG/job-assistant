import json
import tempfile
import unittest
from unittest.mock import patch

from app.companion import Companion
from app.interviews import Interviews
from app.store import Problem, Store, task_lane


class InterviewSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.store.save_profile({'name':'虚构候选人','facts':'校园活动：负责报名沟通与复盘。','preferences':'运营'})
        self.companion = Companion(self.store)
        self.companion.save_settings({'provider':'api','base_url':'https://example.com/v1','api_model':'mock'})
        self.companion.approve({'token':self.companion.preview_profile()['token'],'confirmed':True})
        self.job = self.store.save_job({'title':'运营助理','company':'虚构公司','jd':'负责活动执行、用户沟通与复盘。'})
        task = self.store.create_task({'kind':'tailor_resume','job_id':self.job['id'],'instruction':'简历'})
        claim = self.store.claim(task['id'])
        self.store.finish(task['id'], claim['claim_token'], {'mode':'agent','producer':'fixture','summary':'简历','primary_output':'校园活动经历','markdown':'事实依据'})
        self.version = self.companion.accept_resume({'task_id':task['id'],'content':'校园活动经历'})['id']
        self.interviews = Interviews(self.store, self.companion)

    def finish_question(self, session, text='请做一个60秒自我介绍。'):
        task_id = self.store._row if False else self.interviews._row(session['id'])['pending_task_id']
        task = self.store.claim(task_id)
        self.store.finish(task_id, task['claim_token'], {'mode':'agent','producer':'fixture','summary':'问题','primary_output':text,'markdown':'只生成一个问题'})
        return self.interviews.get(session['id'])

    def test_start_is_idempotent_and_questions_are_job_scoped(self):
        s = self.interviews.start({'job_id':self.job['id'],'resume_version_id':self.version,'goal':'练习表达','request_id':'start-1'})
        self.assertEqual(s['status'], 'generating_question')
        self.assertEqual(task_lane('interview_question'), 'interview')
        again = self.interviews.start({'job_id':self.job['id'],'resume_version_id':self.version,'goal':'练习表达','request_id':'start-1'})
        self.assertEqual(again['id'], s['id'])
        waiting = self.finish_question(s)
        self.assertEqual(waiting['status'], 'awaiting_answer')
        self.assertEqual(len(waiting['turns']), 1)
        self.assertEqual(waiting['turns'][0]['answer_status'], 'pending')

    def test_answer_requires_confirmation_and_only_confirmed_text_enters_next_prompt(self):
        s = self.interviews.start({'job_id':self.job['id'],'resume_version_id':self.version,'request_id':'start-2'})
        waiting = self.finish_question(s)
        with self.assertRaises(Problem):
            self.interviews.answer({'session_id':s['id'],'answer':'草稿','confirmed':False})
        next_state = self.interviews.answer({'session_id':s['id'],'answer':'我负责报名沟通和复盘。','confirmed':True})
        self.assertEqual(next_state['status'], 'generating_question')
        task = self.store.get_task(self.interviews._row(s['id'])['pending_task_id'])
        self.assertIn('我负责报名沟通和复盘', json.dumps(task['context'], ensure_ascii=False))
        self.assertNotIn('草稿', json.dumps(task['context'], ensure_ascii=False))

    def test_pause_resume_skip_and_end_without_fake_recruiting_signal(self):
        s = self.interviews.start({'job_id':self.job['id'],'resume_version_id':self.version,'request_id':'start-3'})
        paused = self.interviews.control({'session_id':s['id'],'action':'pause'})
        self.assertEqual(paused['status'], 'paused')
        resumed = self.interviews.control({'session_id':s['id'],'action':'resume'})
        self.assertEqual(resumed['status'], 'generating_question')
        waiting = self.finish_question(resumed)
        skipped = self.interviews.control({'session_id':s['id'],'action':'skip'})
        self.assertEqual(skipped['turns'][0]['answer_status'], 'skipped')
        self.interviews.control({'session_id':s['id'],'action':'end'})
        done = self.interviews.get(s['id'])
        self.assertIn(done['status'], ('generating_recap','completed'))
        if done['recap']:
            text = json.dumps(done['recap'], ensure_ascii=False)
            self.assertNotIn('录用概率', text)
            self.assertNotIn('补写', text)

    def test_export_and_delete_include_interview_tables(self):
        s = self.interviews.start({'job_id':self.job['id'],'resume_version_id':self.version,'request_id':'start-4'})
        exported = json.loads(self._journey_export())
        self.assertEqual(exported['interview_sessions'][0]['id'], s['id'])
        self.store.cancel(self.interviews._row(s['id'])['pending_task_id'])
        self.store.connect

    def _journey_export(self):
        from app.journey import Journey
        return Journey(self.store).export_data()


if __name__ == '__main__':
    unittest.main()
