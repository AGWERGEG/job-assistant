import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from app.server import make_server
from app.store import Store


class ReviewPollingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.save_profile({'name': '虚构用户', 'preferences': '', 'facts': '仅用于轮询测试的虚构经历'})
        self.job = self.store.save_job({
            'title': '虚构岗位', 'company': '虚构公司', 'url': '',
            'jd': '仅用于轮询测试的虚构职位描述', 'conversation': '',
        })

    def tearDown(self):
        self.tmp.cleanup()

    def _insert_report(self, task_id, body):
        with self.store.connect() as db:
            result = {'summary': '有限摘要', 'decision': '可核对',
                      'primary_output': body, 'markdown': '# 完整虚构报告\n' + body}
            db.execute("INSERT INTO tasks(id,kind,job_id,status,context_json,result_json,created,updated,metrics_json) "
                       "VALUES(?,?,?,'done','{}',?,?,123,?)",
                       (task_id, 'analyze_job', self.job['id'], json.dumps(result, ensure_ascii=False),
                        100, json.dumps({'total_seconds': 2})))

    def test_summary_state_excludes_report_bodies_for_hundreds_of_tasks(self):
        marker = 'PRIVATE_FAKE_REPORT_BODY'
        body = ('虚构正文' + marker) * 7000
        with self.store.connect() as db:
            result = json.dumps({'summary': '有限摘要', 'decision': '可核对',
                                 'primary_output': body, 'markdown': '# 完整虚构报告\n' + body},
                                ensure_ascii=False)
            db.executemany("INSERT INTO tasks(id,kind,job_id,status,context_json,result_json,created,updated,metrics_json) "
                           "VALUES(?,?,?,'done','{}',?,?,?,?)",
                           [(f'fake-{i:04d}', 'analyze_job', self.job['id'], result, 1000 - i, 2000 - i,
                             json.dumps({'total_seconds': 2})) for i in range(500)])

        summary = self.store.state(summary=True)
        serialized = json.dumps(summary, ensure_ascii=False)
        self.assertEqual(len(summary['tasks']), 500)
        self.assertLess(len(serialized), 700_000)
        self.assertNotIn(marker, serialized)
        self.assertNotIn('primary_output', serialized)
        self.assertNotIn('markdown', serialized)
        self.assertEqual(summary['tasks'][0]['result'], {'summary': '有限摘要', 'decision': '可核对'})

        # Keep the CLI/local full-state contract unchanged.
        full = self.store.state()
        self.assertIn(marker, full['tasks'][0]['result']['primary_output'])

    def test_authenticated_result_route_returns_only_the_exact_task_result(self):
        marker = 'PRIVATE_FAKE_EXACT_BODY'
        body = '虚构完整成果 ' + marker
        self._insert_report('exact-result', body)
        server = make_server(self.tmp.name, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f'http://127.0.0.1:{server.server_port}/api/task-result/exact-result'

        with self.assertRaises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(url)
        self.assertEqual(denied.exception.code, 403)

        request = urllib.request.Request(url, headers={'X-Local-Token': server.session_token})
        with urllib.request.urlopen(request) as response:
            payload = json.load(response)
        self.assertEqual(payload['task_id'], 'exact-result')
        self.assertEqual(payload['updated'], 123)
        self.assertEqual(payload['result']['primary_output'], body)
        self.assertEqual(set(payload), {'task_id', 'updated', 'result'})

        summary_request = urllib.request.Request(
            f'http://127.0.0.1:{server.server_port}/api/state?summary=1',
            headers={'X-Local-Token': server.session_token})
        with urllib.request.urlopen(summary_request) as response:
            polled = json.load(response)
        task = next(item for item in polled['tasks'] if item['id'] == 'exact-result')
        self.assertEqual(task['result'], {'summary': '有限摘要', 'decision': '可核对'})
        self.assertNotIn(marker, json.dumps(polled, ensure_ascii=False))

        missing = urllib.request.Request(url + '-other', headers={'X-Local-Token': server.session_token})
        with self.assertRaises(urllib.error.HTTPError) as not_found:
            urllib.request.urlopen(missing)
        self.assertEqual(not_found.exception.code, 404)


if __name__ == '__main__':
    unittest.main()
