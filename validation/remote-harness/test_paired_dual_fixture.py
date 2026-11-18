"""Real helper/wire, owned temporary homes; no SSH/network/device claim."""
import json
from pathlib import Path
import tempfile
import time
import unittest

try:
    from paired_dual_fixture import PairingTarget, distinct_targets, GuiFailure
    from pairing import MemoryKeyStore, PendingPairing, encode
except ModuleNotFoundError as missing:
    if missing.name != 'cryptography': raise
    PairingTarget = None


@unittest.skipIf(PairingTarget is None, 'requires existing pinned pairing environment')
class DualPairingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='hp-dual-pair-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.keys = MemoryKeyStore()
        self.targets, self.pending = {}, {}
        for role in ('et', 'ts'):
            path = self.root / role; path.mkdir(mode=0o700)
            (path / 'authorized_keys').write_bytes(b'')
            public = self.keys.public(self.keys.create())
            config = dict(host='127.0.0.1', port=2222, username='fixture', session='qa',
                          socketPath=str(path / 'config/herdr/sessions/qa/herdr.sock'),
                          herdrPath=str(path / 'herdr'), expectedHostKey=public, paneId='w1:p1')
            target = PairingTarget(role, path, config); self.targets[role] = target
            handle = self.keys.create()
            self.pending[role] = PendingPairing(self.keys, handle, account='fixture',
                expected_host_key=target.host.pin, device='synthetic', now=int(time.time()))

    def test_profiles_use_existing_public_format_and_distinct_host_pins(self):
        targets = distinct_targets(self.targets['et'], self.targets['ts'])
        for role, target in targets.items():
            profile = json.loads(target.public_profile())
            self.assertEqual(profile['provider'], {'et':'easytier','ts':'tailscale'}[role])
            self.assertNotIn('privateKeyPem', profile)
        with self.assertRaises(GuiFailure): distinct_targets(targets['et'], targets['et'])

    def test_cross_request_response_and_unreviewed_approval_do_not_authorize(self):
        a, b = self.targets['et'], self.targets['ts']
        raw = encode(self.pending['et'].request)
        with self.assertRaises(ValueError): b.review(raw)
        review = a.review(raw)
        with self.assertRaisesRegex(GuiFailure, 'review_required'):
            a.approve(raw, request_id=review['requestId'], device_fingerprint=review['deviceFingerprint'])
        with self.assertRaisesRegex(GuiFailure, 'review_required'):
            a.approve(raw, request_id=review['requestId'], device_fingerprint='SHA256:wrong', reviewed=True)
        self.assertEqual((a.root/'authorized_keys').read_bytes(), b'')
        response = a.approve(raw, request_id=review['requestId'], device_fingerprint=review['deviceFingerprint'], reviewed=True)
        with self.assertRaisesRegex(ValueError, 'target mismatch'):
            self.pending['ts'].accept(response, now=int(time.time()), source_reviewed=True)
        self.assertEqual((b.root/'authorized_keys').read_bytes(), b'')
        a.revoke(); self.assertEqual((a.root/'authorized_keys').read_bytes(), b'')

    def test_pre_authorized_fixture_is_rejected(self):
        target = self.targets['et']; (target.root/'authorized_keys').write_bytes(b'pre-generated key')
        with self.assertRaisesRegex(GuiFailure, 'not_empty_owned'):
            PairingTarget('et', target.root, target.config)
