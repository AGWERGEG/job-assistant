"""Isolated checks for the reviewed loopback authorization and error boundaries."""
import http.client
import json
import tempfile
import threading
import socket
import unittest
from unittest.mock import patch

from app.server import make_server
from app.store import Store, Problem


class ReviewedHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.store.save_profile({'name': '虚构测试者', 'facts': '虚构校园经历'})
        self.server = make_server(self.temp.name, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, method, path, data=None, headers=None, authorized=False):
        fields = dict(headers or {})
        if authorized:
            fields['X-Local-Token'] = self.server.session_token
        if data is not None and not isinstance(data, bytes):
            data = json.dumps(data).encode()
        if data is not None:
            fields['Content-Type'] = 'application/json'
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        conn.request(method, path, body=data, headers=fields)
        response = conn.getresponse()
        raw = response.read()
        result = response.status, dict(response.getheaders()), json.loads(raw) if raw and raw.startswith(b'{') else raw
        conn.close()
        return result

    def test_untrusted_local_client_cannot_obtain_token_or_data(self):
        for headers in ({}, {'Origin': f'http://127.0.0.1:{self.server.server_port}',
                             'Sec-Fetch-Site': 'same-origin'}):
            for path in ('/api/session', '/api/data-export', '/api/state', '/api/companion'):
                status, _, body = self.request('GET', path, headers=headers)
                self.assertEqual(status, 403)
                self.assertNotIn(self.server.session_token, str(body))
                self.assertNotIn('虚构校园经历', str(body))
        status, _, health = self.request('GET', '/api/health')
        self.assertEqual(status, 200)
        self.assertNotIn('data_dir', health)
        self.assertNotIn('token', health)
        self.assertEqual(self.request('GET', '/')[0], 200)

    def test_bootstrap_is_one_time_and_cookie_only_authorizes_reads(self):
        bootstrap = self.server.bootstrap_token
        status, headers, session = self.request('POST', '/api/session', {}, {'X-Local-Token': bootstrap})
        self.assertEqual(status, 200)
        self.assertEqual(session['token'], self.server.session_token)
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        cookie = headers['Set-Cookie'].split(';')[0]
        self.assertEqual(self.request('GET', '/api/state', headers={'Cookie': cookie})[0], 200)
        self.assertEqual(self.request('GET', '/api/session', headers={'Cookie': cookie})[0], 200)
        self.assertEqual(self.request('POST', '/api/profile', {'facts': 'changed'}, {'Cookie': cookie})[0], 403)
        self.assertEqual(self.request('POST', '/api/session', {}, {'X-Local-Token': bootstrap})[0], 403)
        self.assertEqual(self.request('GET', '/api/state', headers={'Cookie': cookie, 'Sec-Fetch-Site': 'cross-site'})[0], 403)

    def test_state_poll_does_not_reload_unchanged_reports(self):
        status, headers, _ = self.request('GET', '/api/state', authorized=True)
        self.assertEqual(status, 200)
        with patch.object(Store, 'state', side_effect=AssertionError('should not reload reports')):
            self.assertEqual(self.request('GET', '/api/state', headers={'If-None-Match': headers['ETag']}, authorized=True)[0], 304)
        self.store.save_profile({'facts': '新虚构经历'})
        status, revised, body = self.request('GET', '/api/state', headers={'If-None-Match': headers['ETag']}, authorized=True)
        self.assertEqual(status, 200)
        self.assertNotEqual(revised['ETag'], headers['ETag'])
        self.assertEqual(body['profile']['facts'], '新虚构经历')

    def test_bad_inputs_return_json_errors_without_disconnect(self):
        for path, payload in (('/api/jobs', {'id': []}), ('/api/tasks', {'kind': {}}),
                              ('/api/company-research', {'job_id': []}),
                              ('/api/profile', b'{"a":' + b'[' * 1200 + b'0' + b']' * 1200 + b'}')):
            status, _, body = self.request('POST', path, payload, authorized=True)
            self.assertEqual(status, 400)
            self.assertIn('error', body)
        with socket.create_connection(('127.0.0.1', self.server.server_port), timeout=3) as conn:
            conn.sendall(('GET http://[ HTTP/1.1\r\nHost: 127.0.0.1:' + str(self.server.server_port)
                          + '\r\nX-Local-Token: ' + self.server.session_token + '\r\nConnection: close\r\n\r\n').encode())
            self.assertIn(b'400', conn.recv(4096).split(b'\r\n', 1)[0])
        with patch.object(Store, 'state', side_effect=RuntimeError('synthetic diagnostic must not leak')):
            status, _, body = self.request('GET', '/api/state', authorized=True)
            self.assertEqual(status, 500)
            self.assertNotIn('synthetic diagnostic', body['error'])

    def test_retry_of_stale_snapshot_directs_new_task(self):
        job = self.store.save_job({'title': '虚构岗位', 'company': '虚构公司', 'jd': '虚构职责'})
        task = self.store.create_task({'kind': 'analyze_job', 'job_id': job['id']})
        claimed = self.store.claim(task['id'])
        self.store.fail(task['id'], claimed['claim_token'], '虚构错误')
        self.store.save_profile({'facts': '新虚构经历'})
        with self.assertRaisesRegex(Problem, '创建新任务'):
            self.store.retry(task['id'])
        self.assertEqual(self.store.get_task(task['id'])['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
