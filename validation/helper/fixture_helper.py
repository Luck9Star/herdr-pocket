"""Disposable fixture exercise, not a host authorization tool.

No path, user, home, network, real-key, or request-file CLI arguments exist.
The only store is a newly-created private temporary directory.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import stat
import struct
import tempfile
from dataclasses import dataclass

MAX_BYTES = 65536
CONFIRM_ADD = 'AUTHORIZE FIXTURE'
CONFIRM_REVOKE = 'REVOKE FIXTURE'


def synthetic_key(byte: int = 70) -> str:
    """SSH wire-shaped public test bytes; no private key exists or is generated."""
    kind = b'ssh-ed25519'
    blob = struct.pack('>I', len(kind)) + kind + struct.pack('>I', 32) + bytes([byte]) * 32
    return 'ssh-ed25519 ' + base64.b64encode(blob).decode('ascii')


def canonical_key(value: str) -> str:
    """Bounded wire-shape validation only, NOT a production SSH crypto parser."""
    if not isinstance(value, str) or len(value) > 256:
        raise ValueError('key length/type')
    if not re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/]+={0,2}', value):
        raise ValueError('single key without options/comments/control characters required')
    blob = base64.b64decode(value.split(' ')[1], validate=True)
    prefix = struct.pack('>I', 11) + b'ssh-ed25519' + struct.pack('>I', 32)
    if len(blob) != len(prefix) + 32 or not blob.startswith(prefix):
        raise ValueError('invalid ed25519 wire shape')
    if base64.b64encode(blob).decode('ascii') != value.split(' ')[1]:
        raise ValueError('noncanonical base64')
    return value


def fingerprint(key: str) -> str:
    blob = base64.b64decode(canonical_key(key).split(' ')[1])
    return 'SHA256:' + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip('=')


def request(raw: bytes, now: int) -> dict:
    if len(raw) > 2048:
        raise ValueError('request too large')
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ValueError('duplicate field')
            result[k] = v
        return result
    try:
        obj = json.loads(raw, object_pairs_hook=pairs)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
        raise ValueError('invalid request') from exc
    fields = {'version', 'type', 'request_id', 'device', 'public_key', 'expires_at'}
    if not isinstance(obj, dict) or set(obj) != fields:
        raise ValueError('request field allowlist')
    if type(obj['version']) is not int or obj['version'] != 1 or obj['type'] != 'fixture-public-key-request':
        raise ValueError('request version/type')
    if not isinstance(obj['request_id'], str) or not re.fullmatch(r'[a-z0-9-]{1,48}', obj['request_id']):
        raise ValueError('request id')
    if not isinstance(obj['device'], str) or not re.fullmatch(r'[A-Za-z0-9 -]{1,48}', obj['device']):
        raise ValueError('device label')
    if type(obj['expires_at']) is not int or not now < obj['expires_at'] <= now + 600:
        raise ValueError('request expired or validity too long')
    canonical_key(obj['public_key'])
    return obj


@dataclass(frozen=True)
class Receipt:
    request_id: str
    key: str
    added_line: bytes | None
    separator_added: bool = False
    before_sha256: str = ""


class FixtureStore:
    """POSIX temporary fixture only; constructor accepts no filesystem location."""
    name = 'authorization.fixture'

    def __init__(self):
        if os.name != 'posix' or not hasattr(os, 'O_NOFOLLOW'):
            raise RuntimeError('POSIX fixture checks required; Windows is unverified')
        self._temp = tempfile.TemporaryDirectory(prefix='herdr-helper-fixture-')
        self._fd = os.open(self._temp.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self._receipts: dict[str, Receipt] = {}
        self._atomic_write(b'', None)

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        os.close(self._fd)
        self._temp.cleanup()

    def read(self) -> bytes:
        fd = os.open(self.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=self._fd)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError('regular private fixture file required')
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
                raise ValueError('fixture owner/permissions')
            if info.st_size > MAX_BYTES:
                raise ValueError('fixture too large')
            content = os.read(fd, MAX_BYTES + 1)
            if len(content) > MAX_BYTES:
                raise ValueError('fixture too large')
            return content
        finally:
            os.close(fd)

    def _atomic_write(self, content: bytes, expected: bytes | None):
        if len(content) > MAX_BYTES:
            raise ValueError('fixture too large')
        tmp = 'pending-' + os.urandom(12).hex()
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self._fd)
        try:
            with os.fdopen(fd, 'wb') as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            if expected is not None and self.read() != expected:
                raise ValueError('fixture changed; refuse replacement')
            os.replace(tmp, self.name, src_dir_fd=self._fd, dst_dir_fd=self._fd)
            os.fsync(self._fd)
        finally:
            try:
                os.unlink(tmp, dir_fd=self._fd)
            except FileNotFoundError:
                pass

    def authorize(self, obj: dict, confirmation: str) -> Receipt:
        if confirmation != CONFIRM_ADD:
            raise ValueError('explicit fixture confirmation required')
        key = canonical_key(obj['public_key'])
        rid = obj['request_id']
        if not isinstance(rid, str) or not re.fullmatch(r'[a-z0-9-]{1,48}', rid):
            raise ValueError('request id')
        if rid in self._receipts:
            receipt = self._receipts[rid]
            if receipt.key != key:
                raise ValueError('request id reused with different key')
            return receipt
        before = self.read()
        blob = key.split(' ')[1].encode()
        already = False
        for line in before.splitlines():
            stripped = line.lstrip()
            if not stripped or stripped.startswith(b'#'):
                continue
            fields = stripped.split()
            if fields[:2] == [b'ssh-ed25519', blob]:
                already = True
            elif b'ssh-ed25519' in fields and blob in fields:
                raise ValueError('unsupported existing options or misplaced key tokens')
        added = None if already else (key + ' herdr-fixture:' + rid + '\n').encode()
        separator = b''
        if added:
            separator = b'' if not before or before.endswith(b'\n') else b'\n'
            self._atomic_write(before + separator + added, before)
        receipt = Receipt(rid, key, added, bool(separator), hashlib.sha256(before).hexdigest())
        self._receipts[rid] = receipt
        return receipt

    def revoke(self, receipt: Receipt, confirmation: str) -> bool:
        if confirmation != CONFIRM_REVOKE:
            raise ValueError('explicit fixture revoke confirmation required')
        if self._receipts.get(receipt.request_id) != receipt:
            raise ValueError('receipt is not owned by this fixture session')
        if receipt.added_line is None:
            return False
        before = self.read()
        lines = before.splitlines(keepends=True)
        if receipt.added_line not in lines:
            return False
        if lines.count(receipt.added_line) != 1:
            raise ValueError('ambiguous owned line')
        lines.remove(receipt.added_line)
        remaining = b''.join(lines)
        if (receipt.separator_added and remaining.endswith(b'\n')
                and hashlib.sha256(remaining[:-1]).hexdigest() == receipt.before_sha256):
            remaining = remaining[:-1]
        self._atomic_write(remaining, before)
        return True


def response_matches(obj: dict, pending: dict, *, now: int, consumed: bool = False) -> bool:
    """In-memory response binding experiment; no QR authenticity/one-use claim."""
    if consumed or set(obj) != {'version', 'type', 'request_id', 'fingerprint', 'account', 'host_key', 'expires_at'}:
        return False
    return (type(obj['version']) is int and obj['version'] == 1
            and obj['type'] == 'fixture-pairing-response'
            and obj['request_id'] == pending['request_id']
            and obj['fingerprint'] == fingerprint(pending['public_key'])
            and obj['account'] == 'fixture-user'
            and obj['host_key'] == fingerprint(synthetic_key(71))
            and type(obj['expires_at']) is int and now < obj['expires_at'] <= pending['expires_at'])


def demo(confirm: str) -> dict:
    raw = json.dumps({'version': 1, 'type': 'fixture-public-key-request', 'request_id': 'demo-01',
                      'device': 'fixture-phone', 'public_key': synthetic_key(), 'expires_at': 600}).encode()
    obj = request(raw, now=1)
    with FixtureStore() as store:
        before = store.read()
        if confirm != CONFIRM_ADD:
            return {'scope': 'fixture-only', 'confirmed': False, 'bytesChanged': 0}
        receipt = store.authorize(obj, confirm)
        after = store.read()
        revoked = store.revoke(receipt, CONFIRM_REVOKE)
        return {'scope': 'fixture-only', 'confirmed': True, 'bytesChanged': len(after) - len(before),
                'revokeSimulation': revoked, 'emptyAfterRevoke': store.read() == before,
                'realAuthorization': 'not-implemented', 'network': 'not-implemented'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', action='store_true', required=True)
    parser.add_argument('--confirm-fixture', default='')
    args = parser.parse_args()
    print(json.dumps(demo(args.confirm_fixture), indent=2))
