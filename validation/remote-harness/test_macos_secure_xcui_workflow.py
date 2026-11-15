import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
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
        self.assertIn("and peer and key_peer and live_peer and test_passed", WORKFLOW.read_text())


if __name__ == '__main__':
    unittest.main()
