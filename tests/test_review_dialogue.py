"""Regression checks for the RC dialogue review findings (synthetic data only)."""
import json
import tempfile
import unittest
from unittest.mock import patch

from app.artifacts import artifact_snapshot
from app.companion import Companion
from app.dialogue import DialogueSession, run_dialogue
from app.dialogue_intent import validate_decision
from app.store import Problem, Store


class ReviewDialogueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.companion = Companion(self.store)
        self.store.save_profile({'name': '虚构候选人', 'facts': '负责虚构客户沟通和演示。'})
        self.companion.save_settings({'provider': 'codex'})
        self.companion.approve({'token': self.companion.preview_profile()['token'], 'confirmed': True})
        self.job = self.store.save_job({'title': '虚构销售', 'company': '虚构公司',
                                        'jd': '负责企业客户沟通和产品演示。'})

    def send(self, text, request_id, reference_task_id=''):
        value = {'job_id': self.job['id'], 'text': text, 'request_id': request_id}
        if reference_task_id:
            value['reference_task_id'] = reference_task_id
        return self.companion.send(value)['task']

    def finish_artifact(self, kind, body, instruction='虚构成果'):
        task = self.store.create_task({'kind': kind, 'job_id': self.job['id'],
                                       'instruction': instruction})
        claimed = self.store.claim(task['id'])
        self.store.finish(task['id'], claimed['claim_token'], {
            'summary': body[:900], 'primary_output': body, 'markdown': body,
            'producer': 'synthetic-test', 'mode': 'agent',
            'profile_revision': claimed['context']['profile']['revision'],
            'job_revision': claimed['context']['job']['revision'],
        })
        return task['id']

    def complete_chat(self, task_id, claimed=None):
        task = claimed or self.store.claim(task_id)
        self.store.finish(task_id, task['claim_token'], {
            'summary': '合成对话已完成。', 'primary_output': '合成对话已完成。',
            'markdown': '合成对话已完成。', 'producer': 'synthetic-test', 'mode': 'agent',
            'profile_revision': task['context']['profile']['revision'],
            'job_revision': task['context']['job']['revision'],
        })

    def test_codex_routes_only_explicit_task_requests_and_keeps_chat_available(self):
        ordinary = (
            '不用深入分析了，随便聊聊这个岗位就行',
            '上次那份深入分析报告里说的风险具体指什么？',
            'HR说让我详细看看JD再回复她',
            '请改简历的事先放一放，我先问个问题',
            '帮我写招呼的时候要注意什么？',
            '请问深入分析和快速判断有什么区别？',
        )
        for index, text in enumerate(ordinary):
            task = self.send(text, f'ordinary-{index}')
            self.assertEqual(task['kind'], 'companion_chat', text)
            self.complete_chat(task['id'])
        follow = self.send('帮我优化简历', 'after-discussion')
        self.assertEqual(follow['kind'], 'tailor_resume')
        self.store.cancel(follow['id'])
        explicit = self.send('请帮我深入分析这个岗位', 'explicit-analysis')
        self.assertEqual(explicit['kind'], 'analyze_job')
        self.assertEqual(sum(item['kind'] == 'analyze_job' for item in self.store.state()['tasks']), 1)

    def test_accepted_chat_intent_cannot_create_background_task(self):
        self.companion.save_settings({'provider': 'api', 'dialogue_agent': True,
                                      'base_url': 'https://example.test/v1',
                                      'api_model': 'synthetic', 'api_key': 'synthetic'})
        task = self.send('我想问问这个岗位的加班情况', 'model-chat')
        parent = self.store.claim(task['id'])
        chat_vote = validate_decision({'kind': 'chat'}, parent['context']['instruction'])
        result = {'reply': '可以先向 HR 确认团队的加班安排。', 'history': [],
                  'usage': {}, 'tool_calls': [], 'actions': []}
        with patch('app.dialogue.classify_intent', return_value=chat_vote), \
             patch('app.dialogue.run_process', return_value=result):
            run_dialogue(self.companion.settings(), parent, self.store)
        self.assertFalse(any(item['kind'] == 'analyze_job' for item in self.store.state()['tasks']))

    def test_long_artifact_history_does_not_lock_out_chat_or_selected_reference(self):
        long_body = '合成成果内容。' * 2500
        task_ids = [self.finish_artifact('analyze_job' if i == 0 else 'tailor_resume',
                                         long_body, f'合成成果 {i}') for i in range(4)]
        plain = self.send('你好', 'long-history-chat')
        plain_claim = self.store.claim(plain['id'])
        plain_snapshot = DialogueSession(self.store, plain_claim).snapshot(plain_claim)
        plain_json = json.dumps(plain_snapshot, ensure_ascii=False, separators=(',', ':'))
        self.assertLess(len(plain_json), 24000)
        self.assertEqual({item['task_id'] for item in plain_snapshot['task_artifacts']}, set(task_ids))
        self.assertNotIn('result_markdown', plain_snapshot['task_artifacts'][0])
        self.assertNotIn(long_body, plain_json)
        self.complete_chat(plain['id'], plain_claim)

        # Expire the selected report by changing the confirmed target; the
        # request must still bind to that exact task and retain bounded content.
        self.store.save_job({**self.job, 'jd': '更新后的虚构岗位 JD。'})
        latest_id = artifact_snapshot(self.store, self.job['id'], self.companion.settings())[0]['task_id']
        reference_task = self.send('围绕这份结果聊聊', 'long-history-reference', latest_id)
        selected = self.store.claim(reference_task['id'])
        snapshot = DialogueSession(self.store, selected).snapshot(selected)
        selected_json = json.dumps(snapshot, ensure_ascii=False, separators=(',', ':'))
        self.assertEqual(snapshot['selected_reference']['task_id'], latest_id)
        self.assertTrue(snapshot['selected_reference']['stale'])
        self.assertLess(len(selected_json), 24000)
        self.assertLessEqual(sum(len(value) for value in snapshot['selected_reference']['result'].values()), 8000)
        self.assertIn('合成成果内容', snapshot['selected_reference']['result']['primary_output'])
        self.assertEqual(artifact_snapshot(self.store, self.job['id'], self.companion.settings())[0]['task_id'],
                         latest_id)

    def test_chat_message_limit_matches_persisted_snapshot_limit(self):
        with self.assertRaises(Problem):
            self.send('虚构' * 2501, 'too-long-chat')


if __name__ == '__main__':
    unittest.main()
