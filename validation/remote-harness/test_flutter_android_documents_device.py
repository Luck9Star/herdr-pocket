import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

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


if __name__ == '__main__':
    unittest.main()
