"""Isolated lifecycle checks; no Android tools, devices, or credentials are used."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('with-android-emulator.sh')


class EmulatorLauncherTest(unittest.TestCase):
    def select(self, temp, launcher=None):
        source = SCRIPT.read_text().split('select_emulator_launcher() {', 1)[1].split('\nemulator_launcher=$(select_emulator_launcher)', 1)[0]
        env = dict(os.environ, RUNNER_TEMP=temp, ANDROID_HOME='/sdk')
        env.pop('AVD_EMULATOR_LAUNCHER', None)
        if launcher is not None:
            env['AVD_EMULATOR_LAUNCHER'] = str(launcher)
        return subprocess.run(['bash', '-c', 'select_emulator_launcher() {' + source + '\nselect_emulator_launcher'],
                              env=env, text=True, capture_output=True)

    def test_default_launcher_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self.select(temp)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), '/sdk/emulator/emulator')

    def test_image_and_actual_version_fail_closed(self):
        source = SCRIPT.read_text()
        image = source.split('if [[ -n ${AVD_EXPECTED_IMAGE_REVISION:-} ]]; then', 1)[1].split('\nfi', 1)[0]
        version = source.split('if [[ -n ${AVD_EXPECTED_EMULATOR_VERSION:-} ]]; then', 1)[1].split('\nfi', 1)[0]
        with tempfile.TemporaryDirectory() as temp:
            evidence = Path(temp)
            fields = 'Pkg.Revision=9\nAndroidVersion.ApiLevel=35\nSystemImage.Abi=x86_64\nSystemImage.TagId=google_apis\n'
            (evidence / 'image.properties').write_text(fields)
            (evidence / 'emulator-version.txt').write_text('Android emulator version 37.2.13.0 (build_id 16740729) (CL:N/A)\n')
            env = dict(os.environ, evidence_real=temp, AVD_EXPECTED_IMAGE_REVISION='9',
                       AVD_EXPECTED_EMULATOR_VERSION='Android emulator version 37.2.13.0 (build_id 16740729) (CL:N/A)')
            shell = ('set -e\nif [[ -n ${AVD_EXPECTED_IMAGE_REVISION:-} ]]; then' + image + '\nfi\n'
                     'if [[ -n ${AVD_EXPECTED_EMULATOR_VERSION:-} ]]; then' + version + '\nfi\n')
            run = lambda: subprocess.run(['bash', '-c', shell], env=env, capture_output=True)
            self.assertEqual(run().returncode, 0)
            (evidence / 'image.properties').write_text(fields + 'Pkg.Revision=8\n')
            self.assertNotEqual(run().returncode, 0)
            (evidence / 'image.properties').write_text(fields.replace('Pkg.Revision=9', 'Pkg.Revision=8'))
            self.assertNotEqual(run().returncode, 0)
            (evidence / 'image.properties').write_text(fields)
            (evidence / 'emulator-version.txt').write_text('Android emulator version 37.3.10.0 (build_id 16970787) (CL:N/A)\n')
            self.assertNotEqual(run().returncode, 0)

    def test_only_private_absolute_regular_executable_launcher_is_allowed(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as other:
            root = Path(temp)
            valid = root / 'emulator'
            valid.write_text('#!/bin/sh\nexit 0\n')
            valid.chmod(0o755)
            result = self.select(temp, valid)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), str(valid.resolve()))
            outside = Path(other) / 'emulator'
            outside.write_text('#!/bin/sh\nexit 0\n')
            outside.chmod(0o755)
            link = root / 'linked' / 'emulator'
            link.parent.mkdir()
            link.symlink_to(outside)
            for candidate in (outside, link, root / 'missing' / 'emulator', 'emulator'):
                with self.subTest(candidate=candidate):
                    self.assertNotEqual(self.select(temp, candidate).returncode, 0)
            valid.chmod(0o644)
            self.assertNotEqual(self.select(temp, valid).returncode, 0)


class EmulatorCleanupTest(unittest.TestCase):
    def run_cleanup(self, responses, original=0, process_exit=0):
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
resource_snapshot() { :; }
kill() { return 1; }
wait() { return "$PROCESS_EXIT"; }
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
            env = dict(os.environ, TEST_DIR=temp, ORIGINAL_STATUS=str(original), PROCESS_EXIT=str(process_exit))
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

    def test_dead_emulator_exit_status_is_recorded_without_masking_failure(self):
        result, evidence, _ = self.run_cleanup(['absent'], original=42, process_exit=137)
        self.assertEqual(result.returncode, 42)
        self.assertIn('alive_on_entry=false exit_status=137', evidence)

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
