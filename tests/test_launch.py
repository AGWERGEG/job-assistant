import contextlib
import errno
import io
import tempfile
import unittest
from unittest.mock import Mock, patch

import launch


class LauncherTests(unittest.TestCase):
    def test_default_port_conflict_uses_next_port_without_stopping_existing_server(self):
        with tempfile.TemporaryDirectory() as data_dir:
            server = Mock(server_port=8422, worker_stop=None)
            busy = OSError(errno.EADDRINUSE, 'Address already in use')
            output = io.StringIO()
            with patch('sys.argv', ['launch.py', '--data-dir', data_dir, '--no-worker', '--no-browser']), \
                 patch.object(launch, 'make_server', side_effect=[busy, server]) as make, \
                 patch.object(launch, 'local_session', return_value=None), \
                 contextlib.redirect_stdout(output):
                launch.main()
            self.assertEqual([call.args[1] for call in make.call_args_list], [8421, 8422])
            self.assertIn('改用 8422', output.getvalue())
            server.serve_forever.assert_called_once()
            server.server_close.assert_called_once()

    def test_explicit_port_never_silently_moves_to_another_port(self):
        with tempfile.TemporaryDirectory() as data_dir:
            busy = OSError(errno.EADDRINUSE, 'Address already in use')
            with patch('sys.argv', ['launch.py', '--data-dir', data_dir, '--port', '8421', '--no-worker', '--no-browser']), \
                 patch.object(launch, 'make_server', side_effect=busy) as make, \
                 patch.object(launch, 'local_session', return_value=None), \
                 contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(SystemExit, '无法启动本地端口 8421'):
                    launch.main()
            make.assert_called_once()

    def test_repeat_launch_of_same_installation_keeps_one_instance(self):
        with tempfile.TemporaryDirectory() as data_dir:
            busy = OSError(errno.EADDRINUSE, 'Address already in use')
            output = io.StringIO()
            with patch('sys.argv', ['launch.py', '--data-dir', data_dir, '--no-worker', '--no-browser']), \
                 patch.object(launch, 'make_server', side_effect=busy) as make, \
                 patch.object(launch, 'local_session', return_value={
                     'version':'1.0.0-rc.4.3.40','project_dir':str(launch.ROOT),'data_dir':data_dir}), \
                 contextlib.redirect_stdout(output):
                launch.main()
            make.assert_not_called()
            self.assertIn('已在 http://127.0.0.1:8421 运行', output.getvalue())

    def test_other_version_cannot_share_the_same_data_directory(self):
        with tempfile.TemporaryDirectory() as data_dir:
            busy = OSError(errno.EADDRINUSE, 'Address already in use')
            with patch('sys.argv', ['launch.py', '--data-dir', data_dir, '--no-worker', '--no-browser']), \
                 patch.object(launch, 'make_server', side_effect=busy) as make, \
                 patch.object(launch, 'local_session', return_value={
                     'version':'1.0.0-rc.4.3.5','project_dir':'/different-installation','data_dir':data_dir}), \
                 contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(SystemExit, '不要让两个版本同时写同一份资料'):
                    launch.main()
            make.assert_not_called()

    def test_profile_on_another_port_is_detected_before_binding_free_default(self):
        with tempfile.TemporaryDirectory() as data_dir:
            def session(port):
                return {'version':'old-version','project_dir':'/old','data_dir':data_dir} if port==8424 else None
            with patch('sys.argv',['launch.py','--data-dir',data_dir,'--no-worker','--no-browser']), \
                 patch.object(launch,'local_session',side_effect=session), \
                 patch.object(launch,'make_server') as make, \
                 contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(SystemExit,'数据目录正被另一工作台使用'):
                    launch.main()
            make.assert_not_called()


if __name__ == '__main__':
    unittest.main()
