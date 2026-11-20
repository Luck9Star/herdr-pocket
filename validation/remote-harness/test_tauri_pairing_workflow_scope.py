"""Offline workflow routing checks; these do not prove a GTK GUI run."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/paired-gui-validation.yml'


def step_script(name):
    text = WORKFLOW.read_text(encoding='utf-8')
    block = text.split(f'      - name: {name}', 1)[1].split('\n      - ', 1)[0]
    return textwrap.dedent(block.split('        run: |\n', 1)[1])


class PairingWorkflowRouting(unittest.TestCase):
    def validate(self, **overrides):
        env = dict(os.environ, LINUX_KEYRING='true', LINUX_KEYRING_DENIAL='off',
                   LINUX_DIRECT_SSH='off', FLUTTER_STOCK='false', FLUTTER_ONLY_RESTART='false',
                   INPUT_FIXTURE='false', S06_SPLIT='true', S06_GUARDED='true', S06_ROUTE='tauri',
                   S06_IMPORT_REPLACE='false')
        env.update(overrides)
        return subprocess.run(['bash', '-e', '-c', step_script('Validate the optional routes')],
                              env=env, capture_output=True, text=True)

    def test_guarded_keyring_requires_only_the_tauri_split_route(self):
        result = self.validate()
        self.assertEqual(result.returncode, 0, result.stderr)
        for changes in ({'S06_SPLIT': 'false'}, {'S06_ROUTE': 'flutter'}, {'S06_ROUTE': 'both'},
                        {'INPUT_FIXTURE': 'true'}, {'S06_IMPORT_REPLACE': 'true'},
                        {'LINUX_DIRECT_SSH': 'tauri-key'}, {'LINUX_KEYRING_DENIAL': 'locked'},
                        {'LINUX_KEYRING_DENIAL': 'unavailable'},
                        {'FLUTTER_STOCK': 'true', 'FLUTTER_ONLY_RESTART': 'true'}):
            with self.subTest(changes=changes):
                result = self.validate(**changes)
                self.assertEqual(result.returncode, 1, result.stderr)

    def test_stock_keyring_and_legacy_flutter_guarded_still_validate(self):
        for changes in ({'S06_GUARDED': 'false', 'S06_ROUTE': 'both'},
                        {'S06_GUARDED': 'false', 'S06_SPLIT': 'false', 'LINUX_KEYRING_DENIAL': 'locked'},
                        {'LINUX_KEYRING': 'false', 'S06_ROUTE': 'flutter'}):
            with self.subTest(changes=changes):
                result = self.validate(**changes)
                self.assertEqual(result.returncode, 0, result.stderr)

    def route(self, route='tauri', *, probe=False, split=False, guarded=False, manifest=None, failure=0):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); (root/'pairing-venv/bin').mkdir(parents=True)
            python = root/'pairing-venv/bin/python'
            python.write_text('#!/bin/sh\nif [ "$1" = -c ]; then exec "$REAL_PYTHON" "$@"; fi\nprintf "%s\\n" "$@" > "$CALL_LOG"\nexit "$FAILURE"\n')
            python.chmod(0o755)
            xvfb = root/'xvfb-run'
            xvfb.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$XVFB_LOG"\nexit "$FAILURE"\n')
            xvfb.chmod(0o755)
            output = root/'paired-evidence'; output.mkdir()
            if manifest is not None: (output/'manifest.json').write_text(json.dumps(manifest))
            env = dict(os.environ, PATH=f'{root}:' + os.environ['PATH'], RUNNER_TEMP=name,
                GITHUB_WORKSPACE=str(ROOT), GUI_ROUTE=route, LINUX_KEYRING=str(probe).lower(),
                LINUX_KEYRING_DENIAL='off', FLUTTER_STOCK='false',
                INPUT_FIXTURE=str(guarded).lower(), S06_SPLIT=str(split).lower(),
                CALL_LOG=str(root/'call'), XVFB_LOG=str(root/'xvfb'), FAILURE=str(failure),
                REAL_PYTHON=sys.executable)
            result = subprocess.run(['bash','-e','-c',step_script('Review pairing, authorize the displayed key')],env=env,capture_output=True,text=True)
            trace=(root/'xvfb').read_text() if (root/'xvfb').exists() else (root/'call').read_text()
            result_manifest=json.loads((output/'manifest.json').read_text()) if manifest is not None else None
            return result, trace, result_manifest

    def test_tauri_stock_and_guarded_s06_use_private_wrapper_without_special_proof(self):
        for split,guarded in [(False,False),(False,True),(True,True)]:
            result,trace,_ = self.route(split=split,guarded=guarded)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('linux_pairing_keyring.py',trace)
            self.assertNotIn('--linux-keyring-probe',trace)
            self.assertEqual('--s06-split' in trace,split)
            self.assertEqual('--input-fixture' in trace,guarded)

    def test_tauri_guarded_s06_passes_both_fixture_and_verifier_through_one_wrapper(self):
        result, trace, _ = self.route(probe=True, split=True, guarded=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        args = trace.splitlines()
        wrapper = 'validation/remote-harness/linux_pairing_keyring.py'
        self.assertEqual(args.count(wrapper), 1)
        self.assertEqual(args[args.index(wrapper) + 1], '--')
        self.assertNotIn('dbus-run-session', args)
        command = args[args.index('--') + 1:]
        self.assertEqual(command[command.index('--paired-gui') + 1], 'tauri')
        self.assertIn('--s06-split', command)
        fixture = Path(command[command.index('--input-fixture') + 1])
        verifier = Path(command[command.index('--linux-keyring-probe') + 1])
        self.assertEqual(fixture, verifier.parent / 'input-fixture')
        self.assertEqual(verifier.name, 'linux-pairing-public')

    def test_explicit_probe_and_flutter_legacy_stay_distinct(self):
        result,trace,_=self.route(probe=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('linux_pairing_keyring.py',trace);self.assertIn('--linux-keyring-probe',trace)
        result,trace,_=self.route(route='flutter')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn('linux_pairing_keyring.py',trace);self.assertNotIn('--linux-keyring-probe',trace)

    def test_wrapper_failure_is_preserved_without_rewriting_report(self):
        manifest={'status':'failed','checks':[]}
        result,trace,output=self.route(split=True,guarded=True,manifest=manifest,failure=7)
        self.assertEqual(result.returncode,7,result.stderr)
        self.assertIn('linux_pairing_keyring.py',trace)
        self.assertEqual(output,manifest)

    def test_ordinary_ssh_does_not_install_the_pairing_keyring(self):
        text=WORKFLOW.read_text(encoding='utf-8')
        section=text.split('      - name: Prepare the private Linux Secret Service and public-key verifier',1)[1]
        condition=section.splitlines()[1]
        self.assertIn("matrix.route == 'tauri'",condition)
        self.assertIn('!contains(',condition)
        for ordinary in ('password','tauri-key','tauri-key-rotation','flutter-password','flutter-key','flutter-key-rotation'):
            self.assertIn(ordinary,condition)

if __name__ == '__main__': unittest.main()
