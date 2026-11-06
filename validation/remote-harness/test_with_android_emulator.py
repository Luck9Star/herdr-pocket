"""Isolated lifecycle checks; no Android tools, devices, or credentials are used."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('with-android-emulator.sh')


class EmulatorCleanupTest(unittest.TestCase):
    def run_cleanup(self, responses, original=0):
        source = SCRIPT.read_text().split('cleanup() {', 1)[1].split('\ntrap cleanup EXIT', 1)[0]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'responses').write_text('\n'.join(responses) + '\n')
            shell = '''
set -u
ANDROID_SERIAL=emulator-5554
avd_pid=12345
evidence_real="$TEST_DIR"
evidence_event() { printf '%s\\n' "$*" >> "$evidence_real/lifecycle.txt"; }
kill() { return 1; }
wait() { return 0; }
sleep() { :; }
timeout() {
  local n
  n=$(cat "$TEST_DIR/count" 2>/dev/null || printf 0)
  n=$((n+1)); printf '%s' "$n" > "$TEST_DIR/count"
  local result
  result=$(sed -n "${n}p" "$TEST_DIR/responses")
  [[ -n $result ]] || result=present
  [[ $result != error ]] || return 1
  printf 'List of devices attached\\n'
  [[ $result != present ]] || printf 'emulator-5554\\tdevice\\n'
  return 0
}
cleanup() {''' + source + '''
trap cleanup EXIT
exit "$ORIGINAL_STATUS"
'''
            env = dict(os.environ, TEST_DIR=temp, ORIGINAL_STATUS=str(original))
            result = subprocess.run(['bash', '-c', shell], env=env, capture_output=True, text=True)
            return result, (root / 'lifecycle.txt').read_text(), int((root / 'count').read_text())

    def test_delayed_removal(self):
        result, evidence, count = self.run_cleanup(['present', 'present', 'absent'])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(count, 3)
        self.assertIn('owned serial absent on attempt 3', evidence)

    def test_timeout_is_failure(self):
        result, evidence, count = self.run_cleanup(['present'])
        self.assertEqual(result.returncode, 1)
        self.assertEqual(count, 15)
        self.assertIn('remained after bounded wait', evidence)

    def test_adb_failure_preserves_original_failure(self):
        result, evidence, _ = self.run_cleanup(['error'], original=42)
        self.assertEqual(result.returncode, 42)
        self.assertIn('adb devices failed', evidence)
        self.assertIn('Failed to confirm', result.stderr)

    def test_adb_failure_fails_success_and_signal_status_preserved(self):
        self.assertEqual(self.run_cleanup(['error'])[0].returncode, 1)
        self.assertEqual(self.run_cleanup(['absent'], original=130)[0].returncode, 130)
        self.assertEqual(self.run_cleanup(['error'], original=143)[0].returncode, 143)

    def test_foreign_device_refused_before_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tools = root / 'sdk/platform-tools'
            tools.mkdir(parents=True)
            adb = tools / 'adb'
            adb.write_text('#!/bin/sh\nprintf "List of devices attached\\nforeign-device\\tdevice\\n"\n')
            adb.chmod(0o755)
            env = dict(os.environ, GITHUB_ACTIONS='true', GITHUB_REF='refs/heads/codex/test',
                       RUNNER_TEMP=temp, ANDROID_HOME=str(root / 'sdk'))
            result = subprocess.run(['bash', str(SCRIPT), 'false'], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn('Refusing to run with an existing device', result.stderr)
            self.assertIn('existing device detected; refused', (root / 'avd-evidence/lifecycle.txt').read_text())


if __name__ == '__main__':
    unittest.main()
