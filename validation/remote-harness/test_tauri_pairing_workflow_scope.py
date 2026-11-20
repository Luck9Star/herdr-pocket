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


def review_script():
    text = WORKFLOW.read_text(encoding='utf-8')
    begin = text.index('      - name: Review pairing, authorize the displayed key')
    end = text.index('      - name: Record the S06 GTK typography environment', begin)
    block = text[begin:end]
    return textwrap.dedent(block.split('        run: |\n', 1)[1])


class PairingWorkflowRouting(unittest.TestCase):
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
                INPUT_FIXTURE=str(guarded).lower(), S06_SPLIT=str(split).lower(),
                CALL_LOG=str(root/'call'), XVFB_LOG=str(root/'xvfb'), FAILURE=str(failure),
                REAL_PYTHON=sys.executable)
            result = subprocess.run(['bash','-e','-c',review_script()],env=env,capture_output=True,text=True)
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
