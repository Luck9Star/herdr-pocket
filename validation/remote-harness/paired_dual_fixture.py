#!/usr/bin/env python3
"""Two independent, already prepared QA hosts using the shipping pairing helper.

No device private key is accepted by this interface. Pairing v2 requests and
responses are public records requiring trusted-channel review, not signed
authorization credentials. Possession is established later by pinned SSH.
"""
import os
from pathlib import Path
import re
import tempfile
import time

from paired_gui import FixtureApproval, GuiFailure, Host, bounded_wire
from herdr_pocket_helper.profile import encode_profile
from herdr_pocket_helper.wire import fingerprint


PROVIDERS = {'et': 'easytier', 'ts': 'tailscale'}


class PairingTarget:
    """Adapt an owned empty-authorized_keys fixture, without provisioning SSH.

    config is public connection metadata plus paneId. Call public_profile() for
    the existing import format; review(raw) before approve(..., reviewed=True).
    The existing FixtureApproval remains the sole authorization/revoke writer.
    """
    def __init__(self, role, root, config):
        self.root = Path(root).resolve(strict=True)
        roots = (Path('/tmp').resolve(), Path(tempfile.gettempdir()).resolve())
        if role not in PROVIDERS or not any(self.root.is_relative_to(base) for base in roots):
            raise GuiFailure('dual_pairing_fixture_scope')
        info = self.root.stat()
        authorization = self.root / 'authorized_keys'
        if (info.st_uid != os.geteuid() or info.st_mode & 0o077
                or authorization.is_symlink() or not authorization.is_file()
                or authorization.stat().st_uid != os.geteuid()
                or authorization.stat().st_nlink != 1 or authorization.stat().st_size):
            raise GuiFailure('dual_pairing_authorization_not_empty_owned')
        if 'privateKeyPem' in config or 'private_key' in config:
            raise GuiFailure('dual_pairing_private_identity_forbidden')
        self.role, self.config = role, dict(config)
        public = {key: config[key] for key in ('host', 'port', 'username', 'session',
                  'socketPath', 'herdrPath', 'expectedHostKey')}
        public.update(version=1, type='herdr-connection-profile', provider=PROVIDERS[role])
        self.public = encode_profile(public)
        home = Path(tempfile.mkdtemp(prefix='pairing-helper-', dir=self.root))
        self.host = Host(home, config['username'], config['expectedHostKey'])
        self.approval = FixtureApproval(self.root, self.config, self.host)

    def public_profile(self):
        return self.public

    def review(self, raw):
        request = self.host.review(raw, int(time.time()))
        return {'requestId': request['request_id'], 'hostFingerprint': self.host.pin,
                'deviceFingerprint': fingerprint(request['public_key'])}

    def approve(self, raw, *, request_id, device_fingerprint, reviewed=False):
        expected = self.review(raw)
        if (reviewed is not True or expected['requestId'] != request_id
                or expected['deviceFingerprint'] != device_fingerprint):
            raise GuiFailure('dual_pairing_review_required')
        return self.approval.approve(raw)

    def revoke(self):
        return self.approval.revoke()

    def audit(self, expected):
        """Read independent sshd/capture evidence, never a device self-report."""
        self.approval.verify_ssh(expected)
        log = bounded_wire(self.root / 'sshd.log', 2097152).decode(errors='replace')
        pattern = (r'Accepted publickey for ' + re.escape(self.config['username'])
                   + r' from 127\.0\.0\.1 port [0-9]+ ssh2: ED25519 (SHA256:[A-Za-z0-9+/]+)(?:\s|$)')
        accepted = re.findall(pattern, log)
        matches = sum(value == self.approval.fingerprint for value in accepted)
        return {'acceptedSessions': len(accepted), 'approvedDeviceSessions': matches,
                'otherAcceptedDeviceSessions': len(accepted) - matches,
                'receivedBytes': len(bounded_wire(self.root / 'received.bin', 4096)),
                'exactBytes': True}


def distinct_targets(et, ts):
    if (et.role != 'et' or ts.role != 'ts' or et.root == ts.root
            or et.host.pin == ts.host.pin):
        raise GuiFailure('dual_pairing_hosts_not_independent')
    return {'et': et, 'ts': ts}
