"""Resource evidence remains numeric and never exports host log contents."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('android_emulator_resources', Path(__file__).with_name('android_emulator_resources.py'))
resources = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(resources)


class ResourceEvidenceTest(unittest.TestCase):
    def test_oom_log_is_counted_without_raw_lines(self):
        result = subprocess.CompletedProcess([], 0, b'Out of memory: PRIVATE\nKilled process 12345 (PRIVATE)\n', b'')
        with patch.object(resources.subprocess, 'run', return_value=result):
            value = resources.oom_diagnostic(12345)
        self.assertEqual(value, {'available': True, 'oomLineCount': 2, 'ownedPidMentionCount': 1})
        self.assertNotIn('PRIVATE', json.dumps(value))

    def test_missing_or_forbidden_resources_are_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertIsNone(resources.read_number(Path(temp) / 'missing'))
            self.assertIsNone(resources.memory_events(Path(temp) / 'missing'))
        with patch.object(resources.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, b'', b'PRIVATE')):
            self.assertEqual(resources.oom_diagnostic(12345), {'available': False})


if __name__ == '__main__':
    unittest.main()
