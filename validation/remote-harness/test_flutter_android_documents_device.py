import json
import os
from pathlib import Path
import tempfile
from contextlib import contextmanager
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import flutter_android_documents_device as driver
from paired_gui import GuiFailure


class ExchangeTest(unittest.TestCase):
    def test_fixed_order_has_one_apply_and_all_picker_actions(self):
        self.assertEqual(driver.STAGES.count('apply_dispatch'), 1)
        self.assertEqual([s for s in driver.STAGES if s.endswith('_picker')],
                         ['cancel_picker', 'save_picker', 'wrong_picker', 'tampered_picker', 'correct_picker'])
        self.assertLess(driver.STAGES.index('app_ready'), driver.STAGES.index('initial19'))
        self.assertLess(driver.STAGES.index('preview'), driver.STAGES.index('apply_dispatch'))

    def test_exchange_does_not_treat_device_failure_as_missing_file(self):
        reply = subprocess.CompletedProcess([], 1, b'', b'error: device offline')
        with patch.object(driver.subprocess, 'run', return_value=reply):
            with self.assertRaisesRegex(GuiFailure, 'exchange_read_failed'):
                driver.exchange_read('cache/herdr-documents-1/checkpoint.json')

    def test_exchange_rejects_extra_fields_and_unknown_stages(self):
        for value in ({'stage': 'unknown'}, {'stage': 'app_ready', 'extra': 'secret'}):
            reply = subprocess.CompletedProcess([], 0, json.dumps(value).encode(), b'')
            with patch.object(driver.subprocess, 'run', return_value=reply):
                with self.assertRaisesRegex(GuiFailure, 'exchange_invalid'):
                    driver.exchange_read('cache/herdr-documents-1/checkpoint.json')

    def test_ack_write_is_one_attempt_and_stops_before_rename_when_unknown(self):
        failure = subprocess.CompletedProcess([], 1, b'', b'sensitive diagnostic')
        with patch.object(driver.subprocess, 'run', return_value=failure) as call, patch.object(driver, 'adb') as adb:
            with self.assertRaisesRegex(GuiFailure, 'ack_write_unconfirmed'):
                driver.acknowledge('cache/herdr-documents-1', 'apply_dispatch')
            self.assertEqual(call.call_count, 1)
            adb.assert_not_called()

    def test_exchange_timeout_has_fixed_label_and_no_replay(self):
        with patch.object(driver.subprocess, 'run', side_effect=subprocess.TimeoutExpired('secret', 10)) as call:
            with self.assertRaisesRegex(GuiFailure, 'exchange_read_timeout') as caught:
                driver.exchange_read('cache/herdr-documents-1/checkpoint.json')
            self.assertEqual(call.call_count, 1)
            self.assertNotIn('secret', str(caught.exception))

    def test_adb_error_uses_only_fixed_diagnostic_vocabulary(self):
        error = driver.AdbFailure('secret', operation='window', outcome='timeout')
        self.assertEqual(driver.adb_failure_report(error), {'error': 'adb_operation_failed',
            'commandDiagnostic': {'operation': 'window', 'outcome': 'timeout'}})
        error = driver.AdbFailure('secret', operation='private-value', outcome='private-value')
        self.assertEqual(driver.adb_failure_report(error), {'error': 'adb_operation_failed'})

    def test_stopped_flutter_process_reports_only_bounded_numeric_exit(self):
        report = {}
        with self.assertRaisesRegex(GuiFailure, 'flutter_process_exited'):
            driver.ensure_running(SimpleNamespace(poll=lambda: -4), report)
        self.assertEqual(report, {'flutterExitCode': -4})
        report = {}
        with self.assertRaises(GuiFailure):
            driver.ensure_running(SimpleNamespace(poll=lambda: 'sensitive'), report)
        self.assertEqual(report, {})

    def test_ack_contains_only_public_stage(self):
        data = b'{"stage":"apply_dispatch"}'
        reply = subprocess.CompletedProcess([], 0, data, b'')
        with patch.object(driver.subprocess, 'run', return_value=reply) as call, patch.object(driver, 'adb') as adb:
            driver.acknowledge('cache/herdr-documents-1', 'apply_dispatch')
            self.assertEqual(call.call_args.kwargs['input'], data)
            adb.assert_called_once_with('shell', 'run-as', driver.PACKAGE, 'mv',
                'cache/herdr-documents-1/ack.new', 'cache/herdr-documents-1/ack.json')


class InstalledDigestTest(unittest.TestCase):
    PATH = '/data/app/~~fixture/base.apk'
    DIGEST = 'a' * 64
    SIZE = 12345

    @staticmethod
    def reply(stdout=b'', stderr=b'', code=0):
        return subprocess.CompletedProcess([], code, stdout, stderr)

    def verify(self, replies):
        report = {}
        with patch.object(driver, 'adb', return_value=('package:' + self.PATH + '\n').encode()), \
             patch.object(driver.subprocess, 'run', side_effect=replies) as call:
            driver.installed_digest(self.DIGEST, self.SIZE, report)
        return report, call

    def test_shell_v2_size_and_digest_match(self):
        report, call = self.verify([self.reply(b'12345\n'),
            self.reply((self.DIGEST + '  ' + self.PATH + '\n').encode())])
        self.assertTrue(report['apkVerification']['matched'])
        self.assertEqual(call.call_count, 2)
        self.assertEqual(report['apkVerification']['attempts'][0]['reader'], 'shell')
        self.assertNotIn(self.PATH, json.dumps(report))

    def test_shell_denied_then_owned_run_as(self):
        report, call = self.verify([self.reply(stderr=b'permission denied', code=1), self.reply(b'12345\n'),
            self.reply((self.DIGEST + '  ' + self.PATH + '\n').encode())])
        self.assertTrue(report['apkVerification']['matched'])
        self.assertEqual(report['apkVerification']['attempts'][0]['size'], 'nonzero')
        self.assertIn('run-as', call.call_args.args[0])

    def test_exec_out_style_pseudo_success_is_not_a_digest(self):
        report = {}
        replies = [self.reply(b'12345\n'), self.reply(b'permission denied\n'),
                   self.reply(stderr=b'permission denied', code=1)]
        with patch.object(driver, 'adb', return_value=('package:' + self.PATH).encode()), \
             patch.object(driver.subprocess, 'run', side_effect=replies):
            with self.assertRaisesRegex(GuiFailure, 'installed_hash_unavailable'):
                driver.installed_digest(self.DIGEST, self.SIZE, report)
        self.assertNotIn('permission denied', json.dumps(report))
        self.assertNotIn('matched', report['apkVerification'])

    def test_valid_mismatch_stops_without_alternate_reader(self):
        report = {}
        replies = [self.reply(b'12345\n'), self.reply(('b' * 64 + '  ' + self.PATH).encode())]
        with patch.object(driver, 'adb', return_value=('package:' + self.PATH).encode()), \
             patch.object(driver.subprocess, 'run', side_effect=replies) as call:
            with self.assertRaisesRegex(GuiFailure, 'installed_hash_mismatch'):
                driver.installed_digest(self.DIGEST, self.SIZE, report)
            self.assertEqual(call.call_count, 2)
        self.assertEqual(report['apkVerification']['attempts'][0]['digest'], 'b' * 64)

    def test_wrong_size_stops_without_alternate_reader(self):
        with self.assertRaisesRegex(GuiFailure, 'installed_hash_mismatch'):
            self.verify([self.reply(b'12344\n'),
                self.reply((self.DIGEST + '  ' + self.PATH).encode())])


class DocumentImeTest(unittest.TestCase):
    LAUNCHER = driver.PACKAGE + '/.MainActivity'

    @staticmethod
    def sample(visibility):
        return {'visible': visibility == 'visible', 'hidden': visibility == 'hidden',
                'diagnostic': {'visibility': visibility, 'focusOwner': 'owned', 'raw': 'private diagnostic'}}

    def test_import_accepts_already_hidden_without_pressing_back(self):
        with patch.object(driver, 'foreground', return_value=self.LAUNCHER), \
             patch.object(driver, 'wait_import_ime', return_value=self.sample('hidden')), \
             patch.object(driver, 'adb') as adb, patch.object(driver, 'wait_system_ime') as strict:
            expected = {'outcome': 'already_hidden', 'before': {'visibility': 'hidden', 'focusOwner': 'owned'}}
            self.assertEqual(driver.dismiss_document_ime('hide_wrong', self.LAUNCHER), expected)
            adb.assert_not_called()
            strict.assert_not_called()

    def test_visible_import_sends_one_back_and_verifies_hidden(self):
        with patch.object(driver, 'foreground', return_value=self.LAUNCHER), \
             patch.object(driver, 'wait_import_ime', return_value=self.sample('visible')), \
             patch.object(driver, 'adb') as adb, \
             patch.object(driver, 'wait_system_ime', return_value=self.sample('hidden')) as strict:
            result = driver.dismiss_document_ime('hide_tampered', self.LAUNCHER)
            self.assertEqual(result['outcome'], 'system_back')
            self.assertEqual((result['before']['visibility'], result['after']['visibility']), ('visible', 'hidden'))
            self.assertIs(strict.call_args.args[2], False)
            adb.assert_called_once_with('shell', 'input', 'keyevent', 'KEYCODE_BACK')

    def test_export_requires_native_show_before_back(self):
        hidden = driver.SystemImeFailure('android_system_ime_show_unconfirmed', {'reason': 'owned_hidden'})
        with patch.object(driver, 'foreground', return_value=self.LAUNCHER), \
             patch.object(driver, 'wait_import_ime') as optional, patch.object(driver, 'adb') as adb, \
             patch.object(driver, 'wait_system_ime', side_effect=hidden) as strict:
            with self.assertRaisesRegex(driver.SystemImeFailure, 'show_unconfirmed'):
                driver.dismiss_document_ime('hide_export', self.LAUNCHER)
            self.assertIs(strict.call_args.args[2], True)
            optional.assert_not_called()
            adb.assert_not_called()

        with patch.object(driver, 'foreground', return_value=self.LAUNCHER), \
             patch.object(driver, 'wait_system_ime', side_effect=[self.sample('visible'), self.sample('hidden')]) as strict, \
             patch.object(driver, 'adb') as adb:
            result = driver.dismiss_document_ime('hide_export', self.LAUNCHER)
            self.assertEqual([call.args[2] for call in strict.call_args_list], [True, False])
            self.assertEqual(result['outcome'], 'system_back')
            adb.assert_called_once_with('shell', 'input', 'keyevent', 'KEYCODE_BACK')

    def test_foreground_change_and_unconfirmed_back_block_progress(self):
        for owners in ([None], [self.LAUNCHER, 'foreign/.Picker']):
            with self.subTest(owners=owners), patch.object(driver, 'foreground', side_effect=owners), \
                 patch.object(driver, 'wait_import_ime', return_value=self.sample('visible')), patch.object(driver, 'adb') as adb:
                with self.assertRaisesRegex(GuiFailure, 'ime_foreground_unconfirmed'):
                    driver.dismiss_document_ime('hide_correct', self.LAUNCHER)
                adb.assert_not_called()
        failure = driver.SystemImeFailure('android_system_ime_hide_unconfirmed', {'reason': 'owned_visible'})
        with patch.object(driver, 'foreground', return_value=self.LAUNCHER), \
             patch.object(driver, 'wait_import_ime', return_value=self.sample('visible')), patch.object(driver, 'adb') as adb, \
             patch.object(driver, 'wait_system_ime', side_effect=failure):
            with self.assertRaisesRegex(driver.SystemImeFailure, 'hide_unconfirmed'):
                driver.dismiss_document_ime('hide_correct', self.LAUNCHER)
            adb.assert_called_once()

        with patch.object(driver, 'foreground', side_effect=[self.LAUNCHER, self.LAUNCHER, None]), \
             patch.object(driver, 'wait_import_ime', return_value=self.sample('visible')), patch.object(driver, 'adb') as adb, \
             patch.object(driver, 'wait_system_ime', return_value=self.sample('hidden')):
            with self.assertRaisesRegex(GuiFailure, 'ime_foreground_unconfirmed'):
                driver.dismiss_document_ime('hide_correct', self.LAUNCHER)
            adb.assert_called_once()

    def test_import_requires_consecutive_owned_samples(self):
        hidden = self.sample('hidden')
        retry = driver.SystemImeFailure('android_system_ime_target_mismatch', {'reason': 'focus_null'}, retryable=True)
        samples = [hidden, retry, hidden, self.sample('transition'), hidden, hidden]
        with patch.object(driver, 'parse_system_ime', side_effect=samples) as parse, patch.object(driver.time, 'sleep'):
            result = driver.wait_import_ime(Mock(return_value=('service dump', 'display dump')))
        self.assertTrue(result['hidden'])
        self.assertEqual(result['diagnostic']['attempts'], 6)
        self.assertEqual(parse.call_count, 6)
        foreign = driver.SystemImeFailure('android_system_ime_target_mismatch', {'reason': 'focus_foreign'})
        with patch.object(driver, 'parse_system_ime', side_effect=[hidden, foreign, hidden]) as parse, \
             patch.object(driver.time, 'sleep'):
            with self.assertRaisesRegex(driver.SystemImeFailure, 'target_mismatch'):
                driver.wait_import_ime(Mock(return_value=('service dump', 'display dump')))
        self.assertEqual(parse.call_count, 2)


class CleanupTest(unittest.TestCase):
    def test_hash_failure_still_reports_independently_verified_cleanup(self):
        @contextmanager
        def owned(*args, **kwargs):
            yield SimpleNamespace(pid=123, poll=lambda: None)

        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            app = base / 'app'
            apk = app / 'build/app/outputs/flutter-apk/app-debug.apk'
            apk.parent.mkdir(parents=True)
            apk.write_bytes(b'fixture-apk')
            output = base / 'result'
            picker = SimpleNamespace(scratch='/fixed-fixture', scratch_cleanup_failed=False)
            def adb(*args, **kwargs):
                if args[:3] == ('shell', 'settings', 'get'):
                    return b'1'
                return b''
            with patch.dict(os.environ, {'GITHUB_RUN_ID': '1', 'GITHUB_SHA': 'a' * 40}), \
                 patch.object(driver, 'check_environment', return_value=base), \
                 patch.object(driver, 'Picker', return_value=picker), \
                 patch.object(driver, 'wait_download_storage'), patch.object(driver, 'adb', side_effect=adb), \
                 patch.object(driver, 'owned_process', owned), patch.object(driver, 'exchange_read', return_value='app_ready'), \
                 patch.object(driver, 'installed_digest', side_effect=GuiFailure('installed_hash_mismatch')), \
                 patch.object(driver, 'verify_tool_stopped'):
                with self.assertRaisesRegex(GuiFailure, 'roundtrip_failed'):
                    driver.drive(app, output)
            report = json.loads((output / 'flutter-documents-roundtrip.json').read_text())
            self.assertEqual(report['error'], 'installed_hash_mismatch')
            self.assertEqual(report['status'], 'failed')
            self.assertTrue(all(report['cleanup'].values()))
            self.assertTrue(all(facts['outcome'] == 'confirmed' for facts in report['cleanupDiagnostics'].values()))

    def test_tool_requires_exit_and_absent_process_group(self):
        process = SimpleNamespace(pid=123, poll=lambda: 1)
        with patch.object(driver.os, 'killpg', side_effect=ProcessLookupError):
            driver.verify_tool_stopped(process)
        with patch.object(driver.os, 'killpg', return_value=None):
            with self.assertRaisesRegex(GuiFailure, 'flutter_tool_unconfirmed'):
                driver.verify_tool_stopped(process)
        with self.assertRaises(GuiFailure):
            driver.verify_tool_stopped(SimpleNamespace(pid=123, poll=lambda: None))

    def test_cleanup_records_only_actual_outcome_and_safe_error(self):
        report = {'cleanup': {'package': False, 'folder': False}, 'cleanupDiagnostics': {}}
        driver.checked_cleanup(report, 'package', lambda: None)
        self.assertTrue(report['cleanup']['package'])
        self.assertEqual(report['cleanupDiagnostics']['package'], {'outcome': 'confirmed'})
        def failed():
            raise driver.AdbFailure('private', operation='package_list', outcome='timeout')
        driver.checked_cleanup(report, 'folder', failed)
        self.assertFalse(report['cleanup']['folder'])
        self.assertEqual(report['cleanupDiagnostics']['folder'], {'outcome': 'adb_failed',
            'commandDiagnostic': {'operation': 'package_list', 'outcome': 'timeout'}})
        self.assertNotIn('private', json.dumps(report))


if __name__ == '__main__':
    unittest.main()
