import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import android_dual_overlay_session as session


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.subject = session.AndroidDualOverlaySession(self.root, self.root,
            host_source='a' * 40, source_checkout=self.root)

    def test_private_json_control_does_not_log_requests_and_stops(self):
        code = '''import sys,json
print(json.dumps({'event':'ready'}),flush=True)
for line in sys.stdin:
 r=json.loads(line)
 if r['op']=='stop':
  print(json.dumps({'event':'cleanup','stopReason':'explicit-stop'}),flush=True);break
 print(json.dumps({'event':'ts_authorized','ok':True}),flush=True)
'''
        child = subprocess.Popen([sys.executable, '-c', code], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            control = session.PrivateHostControl(child)
            self.assertEqual(control.ready(timeout=3), {'event': 'ready'})
            capture = io.StringIO()
            with contextlib.redirect_stdout(capture):
                result = control.call({'op': 'complete_ts_auth', 'authorize': True,
                                       'url': 'one-time-synthetic-value'}, timeout=3)
            self.assertEqual(result, {'event': 'ts_authorized', 'ok': True})
            self.assertEqual(capture.getvalue(), '')
            self.assertEqual(control.call({'op': 'stop'}, timeout=3)['stopReason'], 'explicit-stop')
            self.assertEqual(child.wait(timeout=3), 0)
            control.reader.join(timeout=2)
            self.assertFalse(control.reader.is_alive())
        finally:
            if child.poll() is None: child.kill(); child.wait()
            child.stdin.close(); child.stdout.close()

    def test_namespace_collision_is_never_deleted(self):
        env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REF': 'refs/heads/codex/test',
               'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '2', 'RUNNER_TEMP': str(self.root)}
        calls = []
        with mock.patch.dict(os.environ, env), mock.patch.object(session.sys, 'platform', 'linux'), \
             mock.patch.object(session.os, 'geteuid', return_value=1001), \
             mock.patch.object(session, 'assert_owned_avd'), \
             mock.patch.object(session, 'command', side_effect=lambda args, *a: calls.append(args) or b''), \
             mock.patch.object(self.subject, '_namespace_exists', return_value=True):
            with self.assertRaisesRegex(session.SessionError, 'namespace_collision'):
                self.subject.__enter__()
        self.assertFalse(any('delete' in args or 'add' in args for args in calls))
        self.assertFalse(self.subject.report['cleanup']['namespaceRemoved'])
        self.assertTrue(self.subject.report['cleanup']['privateFilesRemoved'])

    def test_replaced_namespace_is_never_signalled_or_removed(self):
        self.subject.namespace = 'hp-dual-123-2'
        self.subject.namespace_owned = True
        self.subject.namespace_inode = 42
        path = mock.Mock()
        path.exists.return_value = True
        path.stat.return_value = SimpleNamespace(st_ino=43)
        self.subject.namespace_path = path
        with mock.patch.object(session, 'command') as command:
            with self.assertRaisesRegex(session.SessionError, 'namespace_changed'):
                self.subject._remove_namespace()
        command.assert_not_called()

    def test_namespace_inode_is_rechecked_immediately_before_delete(self):
        self.subject.namespace = 'hp-dual-123-2'
        self.subject.namespace_owned = True
        with mock.patch.object(self.subject, '_same_namespace', side_effect=[True, False]), \
             mock.patch.object(self.subject, '_residents', return_value=[]), \
             mock.patch.object(session, 'command') as command:
            with self.assertRaisesRegex(session.SessionError, 'namespace_changed'):
                self.subject._remove_namespace()
        command.assert_not_called()

    def test_teardown_order_and_private_files_are_confirmed(self):
        order = []
        self.subject.private = self.root / 'private'; self.subject.private.mkdir(mode=0o700)
        (self.subject.private / 'materials.json').write_text('synthetic')
        self.subject.reverse = mock.Mock(cleanup_confirmed=True)
        self.subject.reverse.close.side_effect = lambda: order.append('reverse')
        self.subject.relay = mock.Mock()
        self.subject.relay.close.side_effect = lambda: order.append('relay')
        self.subject.process = mock.Mock()
        self.subject.process.wait.return_value = self.subject.process.poll.return_value = 0
        self.subject.control = mock.Mock()
        self.subject.control.reader.is_alive.return_value = False
        def stop(*args, **kwargs):
            order.append('host')
            return dict(event='cleanup', stopReason='explicit-stop',
                        **dict.fromkeys(session.CONTROLLER_CLEANUP, True))
        self.subject.control.call.side_effect = stop
        self.subject._remove_namespace = lambda: order.append('namespace') or True
        self.subject._remove_host_private_directory = lambda: order.append('host-files') or True
        self.subject.close()
        self.assertEqual(order, ['reverse', 'relay', 'host', 'namespace', 'host-files'])
        self.assertTrue(all(self.subject.report['cleanup'].values()))
        self.subject.close()
        self.assertEqual(len(order), 5)

    def test_private_materials_reject_escape_symlink_and_hardlink(self):
        self.subject.private = self.root / 'private'; self.subject.private.mkdir(mode=0o700)
        outside = self.root / 'outside'; outside.write_text('synthetic')
        with self.assertRaises(session.SessionError): self.subject._private_file(outside, 100)
        alias = self.subject.private / 'alias'; alias.symlink_to(outside)
        with self.assertRaises(session.SessionError): self.subject._private_file(alias, 100)
        alias.unlink(); os.link(outside, alias)
        with self.assertRaises(session.SessionError): self.subject._private_file(alias, 100)

    def test_pidfd_cleanup_validates_namespace_before_signalling(self):
        def verify(matched):
            def stat(path, *args, **kwargs):
                inode = 42 if str(path).startswith('/run/netns/') or matched else 99
                return SimpleNamespace(st_ino=inode)
            with mock.patch.object(session.sys, 'platform', 'linux'), \
                 mock.patch.object(session.os, 'geteuid', return_value=0), \
                 mock.patch.object(session.Path, 'stat', stat), \
                 mock.patch.object(session.Path, 'read_text', return_value='Uid:\t501\t501\t501\t501\n'), \
                 mock.patch.object(session.os, 'pidfd_open', create=True, return_value=123) as opened, \
                 mock.patch.object(session.os, 'close') as closed, \
                 mock.patch.object(session.signal, 'pidfd_send_signal', create=True) as sent:
                if matched:
                    session.signal_owned_residents('/run/netns/hp-dual-123-2', 42, 501, signal.SIGTERM, [456])
                    sent.assert_called_once_with(123, signal.SIGTERM)
                else:
                    with self.assertRaisesRegex(session.SessionError, 'resident_changed'):
                        session.signal_owned_residents('/run/netns/hp-dual-123-2', 42, 501, signal.SIGTERM, [456])
                    sent.assert_not_called()
                opened.assert_called_once_with(456); closed.assert_called_once_with(123)
        verify(True); verify(False)


if __name__ == '__main__':
    unittest.main()
