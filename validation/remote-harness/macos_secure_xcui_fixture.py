"""Owned loopback server for opt-in macOS native UI acceptance; no secret output."""
import json
import os
from pathlib import Path
import sys
import time

from direct_ssh_fixture import DirectSshFixture

root = Path(sys.argv[1]).resolve()
if os.environ.get('GITHUB_ACTIONS') != 'true' or not root.is_dir() or not root.is_relative_to(Path(os.environ.get('RUNNER_TEMP','/nonexistent')).resolve()):
    raise SystemExit('fixture_scope_invalid')
os.umask(0o077)
with DirectSshFixture() as peer:
    pending = root / 'fixture.pending'
    pending.write_text(json.dumps({'port':peer.port,'username':peer.username,
        'password':peer.password,'fingerprint':peer.fingerprint}))
    pending.replace(root / 'fixture.json')
    for _ in range(1800):
        (root / 'facts.json').write_text(json.dumps(peer.snapshot()))
        if (root / 'stop').exists():
            break
        time.sleep(.1)
