import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/flutter-macos-secure-xcui.yml'


class LivePeerMonitorTests(unittest.TestCase):
    def run_monitor(self, scenario):
        workflow = WORKFLOW.read_text()
        start = workflow.index('          import json, subprocess, sys, time\n')
        end = workflow.index('          PY\n', start)
        monitor = '\n'.join(line[10:] for line in workflow[start:end].splitlines())
        child = '''import json, os, sys, time
path, scenario = sys.argv[1:]
fields = ('authAccepted', 'ptyRequested', 'shellRequested', 'sessionClosed', 'connectionsClosed')
facts = {name: dict(zip(fields, (True, True, True, False, False))) for name in ('password', 'encryptedKey')}
def save():
    with open(path, 'w') as output: json.dump(facts, output)
def stage(name):
    print('HP_XCUI_STAGE=' + name, flush=True)
save()
for name, peer in (('password', 'password'), ('key', 'encryptedKey')):
    stage(name + 'DisconnectAttempt')
    time.sleep(0.2 if scenario != 'no_before' else 0)
    stage(name + 'DisconnectTapped')
    if scenario != 'no_close':
        facts[peer]['sessionClosed'] = facts[peer]['connectionsClosed'] = True
        save()
    time.sleep(0.2)
    if scenario != 'no_end': stage(name + 'DisconnectWindowEnded')
    time.sleep(0.1)
'''
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            child_path = temp / 'child.py'
            child_path.write_text(child)
            result = subprocess.run([sys.executable, '-c', monitor, str(temp / 'log'), str(temp / 'facts'), str(temp / 'live'), sys.executable, str(child_path), str(temp / 'facts'), scenario], timeout=10)
            self.assertEqual(result.returncode, 0)
            return json.loads((temp / 'live').read_text())

    def test_verifies_both_peers_during_windows(self):
        self.assertEqual(self.run_monitor('ok'), {'password': True, 'key': True})

    def test_missing_close_or_window_end_fails_closed(self):
        for scenario in ('no_close', 'no_end', 'no_before'):
            with self.subTest(scenario=scenario):
                self.assertNotEqual(self.run_monitor(scenario), {'password': True, 'key': True})

    def test_report_requires_live_evidence(self):
        workflow = WORKFLOW.read_text()
        self.assertIn("and peer and key_peer and live_peer and test_passed", workflow)
        marker = "          python3 - \"$RUNNER_TEMP/macos-secure-evidence/result.json\" \"$result\" <<'PY'\n"
        body = workflow.split(marker, 1)[1].split("\n          PY\n", 1)[0]
        script = textwrap.dedent(body)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {**os.environ, 'RUNNER_TEMP': tmp}
            (root / 'macos-secure-private.log').write_text(
                'HP_XCUI_PEM=visible:1,draft:1,focus:0,expanded:1,editoradded:0,summarygone:1\n'
                'HP_XCUI_PEM=visible:1,draft:secret-data,focus:1,expanded:1,editoradded:1,summarygone:1\n'
                'HP_XCUI_KEYINPUT=visible:1,key:1,passphrase:0,sentinel:0,empty:0,length:1,trimmed:1 secret-data\n'
                'HP_XCUI_KEYINPUT=visible:0,key:0,passphrase:0,sentinel:0,empty:0,length:0,trimmed:0\n'
                'HP_XCUI_KEYINPUT=visible:1,key:secret-data,passphrase:1,sentinel:0,empty:0,length:1,trimmed:1\n'
                'RunnerTests.swift:456: error: form action center not visible and stable secret-data\n'
                'HP_XCUI_FORM=phase:paste,count:1,enabled:1,hittable:0,inside:0,scroll:1\n'
                'HP_XCUI_STAGE=returnCredentialEntered\n'
                'HP_XCUI_HIT=phase:returnSecure,exists:1,enabled:1,hittable:0,inside:1\n')
            for password, key in ((True, False), (False, True), (True, True)):
                with self.subTest(password=password, key=key):
                    (root / 'macos-secure-private-live.json').write_text(json.dumps({'password': password, 'key': key}))
                    output = root / 'result.json'
                    subprocess.run([sys.executable, '-', str(output), '1'], input=script, text=True, env=env, capture_output=True, check=False)
                    report = json.loads(output.read_text())
                    self.assertEqual(report['failureSourceLines'], [456])
                    self.assertIn('form action center not visible and stable',report['fixedFailures'])
                    self.assertEqual(report['formMetrics'][0], {'phase':'paste','count':1,'enabled':True,'hittable':False,'insideViewport':False,'scrollView':True})
                    self.assertIs(report['passwordPeerCloseObservedDuringDisconnectWindow'], password)
                    self.assertIs(report['encryptedKeyPeerCloseObservedDuringDisconnectWindow'], key)
                    self.assertIs(report['peerCloseObservedDuringDisconnectWindows'], password and key)
                    self.assertEqual(report['status'], 'failed')
                    self.assertEqual(report['pemOpenMetrics'], [{'visible':True,'draftExact':True,'focused':False,'expanded':True,'editorAdded':False,'summaryGone':True}])
                    self.assertEqual(report['keyInputMetrics'], [
                        {'visible': True, 'key': True, 'passphrase': False, 'sentinel': False, 'empty': False, 'lengthMatches': True, 'trimmedMatches': True},
                        {'visible': False, 'key': False, 'passphrase': False, 'sentinel': False, 'empty': False, 'lengthMatches': False, 'trimmedMatches': False}])
                    self.assertTrue(report['progress']['returnCredentialEntered'])
                    self.assertEqual(report['hitMetrics'][0]['phase'], 'returnsecure')
                    self.assertNotIn('secret-data', output.read_text())


if __name__ == '__main__':
    unittest.main()
