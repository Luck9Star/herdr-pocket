"""Offline public pairing reference; temporary fixture authorization only.

No SSH connection, host trust, QR camera, production key store, or persisted
one-time authorization is implemented by this module.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re
import secrets
import sys
from typing import Protocol

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, load_ssh_public_key

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'helper'))
from fixture_helper import FixtureStore, CONFIRM_ADD, CONFIRM_REVOKE, canonical_key

MAX_BYTES = 2048
MAX_TTL = 600
VERSION = 2
REQUEST = 'pairing-public-key-request'
RESPONSE = 'pairing-binding-response'
BASE = {'version', 'type', 'request_id', 'account', 'host_key', 'issued_at', 'expires_at'}
REQUEST_FIELDS = BASE | {'device', 'public_key'}
RESPONSE_FIELDS = BASE | {'fingerprint', 'status', 'authorization_added'}


def public_key(value: str) -> str:
    """Strict single OpenSSH Ed25519 record, parsed by a mature SSH key parser."""
    canonical_key(value)  # reject options, comments, controls and noncanonical b64
    parsed = load_ssh_public_key(value.encode('ascii'))
    if not isinstance(parsed, Ed25519PublicKey):
        raise ValueError('Ed25519 required')
    normalized = parsed.public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode('ascii')
    if normalized != value:
        raise ValueError('noncanonical SSH public key')
    return normalized


def fingerprint(value: str) -> str:
    blob = base64.b64decode(public_key(value).split()[1], validate=True)
    return 'SHA256:' + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip('=')


def encode(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def decode(raw: bytes, *, now: int) -> dict:
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_BYTES or type(now) is not int:
        raise ValueError('wire limit/type')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate field')
            result[key] = value
        return result
    try:
        # json.loads(bytes) also auto-detects UTF-16/32; the wire is UTF-8 only.
        obj = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
        raise ValueError('invalid JSON') from exc
    if not isinstance(obj, dict):
        raise ValueError('object required')
    kind = obj.get('type')
    fields = REQUEST_FIELDS if kind == REQUEST else RESPONSE_FIELDS if kind == RESPONSE else set()
    if not fields or set(obj) != fields or type(obj['version']) is not int or obj['version'] != VERSION:
        raise ValueError('unknown type/version/field')
    patterns = {'request_id': r'[a-f0-9]{32}', 'account': r'[a-z_][a-z0-9_-]{0,31}',
                'host_key': r'SHA256:[A-Za-z0-9+/]{43}'}
    if kind == REQUEST:
        patterns['device'] = r'[A-Za-z0-9 -]{1,48}'
        public_key(obj['public_key'])
    else:
        patterns['fingerprint'] = r'SHA256:[A-Za-z0-9+/]{43}'
        if obj['status'] not in ('authorized', 'revoked') or type(obj['authorization_added']) is not bool:
            raise ValueError('response status/type')
    for name, pattern in patterns.items():
        if not isinstance(obj[name], str) or re.fullmatch(pattern, obj[name]) is None:
            raise ValueError('invalid public field')
    start, end = obj['issued_at'], obj['expires_at']
    if (type(start) is not int or type(end) is not int or start < 0
            or not start <= now < end or not 0 < end - start <= MAX_TTL):
        raise ValueError('future/expired/overlong record')
    return obj


class DeviceKeyStore(Protocol):
    """App-facing boundary: key handles stay local, no private export/import API.

    Native adapters must fail on locked/unavailable/invalidated storage. Never
    silently regenerate a missing key for an existing handle or use plaintext.
    """
    def create(self) -> str: ...
    def public(self, handle: str) -> str: ...
    def sign(self, handle: str, payload: bytes) -> bytes: ...
    def delete(self, handle: str) -> None: ...


class MemoryKeyStore:
    """Test double only. Does not model Keychain/Keystore or guarantee erasure."""
    def __init__(self):
        self._keys: dict[str, Ed25519PrivateKey] = {}
        self.locked = False
        self.available = True

    def _ready(self):
        if self.locked or not self.available:
            raise RuntimeError('protected storage unavailable')

    def create(self) -> str:
        self._ready()
        handle = secrets.token_hex(16)
        self._keys[handle] = Ed25519PrivateKey.generate()
        return handle

    def public(self, handle: str) -> str:
        self._ready()
        return self._keys[handle].public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode()

    def sign(self, handle: str, payload: bytes) -> bytes:
        self._ready()
        if type(payload) is not bytes or len(payload) > 65536:
            raise ValueError('signature payload bound')
        return self._keys[handle].sign(payload)

    def delete(self, handle: str) -> None:
        self._ready()
        del self._keys[handle]


class PendingPairing:
    """Phone state reference. Callers retain this instance across UI operations.

    A binding response is NOT authenticated: explicit review means the user has
    checked its trusted out-of-band source and expected account/host fingerprint.
    The caller may mark connected only after actual pinned SSH authentication.
    """
    def __init__(self, store: DeviceKeyStore, handle: str, *, account: str,
                 expected_host_key: str, device: str, now: int):
        self.store, self.handle = store, handle
        self.request = decode(encode({'version': VERSION, 'type': REQUEST,
            'request_id': secrets.token_hex(16), 'account': account, 'host_key': expected_host_key,
            'device': device, 'public_key': store.public(handle),
            'issued_at': now, 'expires_at': now + MAX_TTL}), now=now)
        self.state = 'awaiting-host'
        self.authorization = 'unknown'
        self.authorization_added: bool | None = None
        self.generation = 0
        self.consumed = False

    def tick(self, now: int):
        if self.state == 'awaiting-host' and now >= self.request['expires_at']:
            self.state = 'expired'
            self.generation += 1

    def accept(self, raw: bytes, *, now: int, source_reviewed: bool):
        response = decode(raw, now=now)
        if response['type'] != RESPONSE:
            raise ValueError('binding response required')
        for key in ('request_id', 'account', 'host_key'):
            if response[key] != self.request[key]:
                raise ValueError('response target mismatch')
        if response['fingerprint'] != fingerprint(self.request['public_key']):
            raise ValueError('device fingerprint mismatch')
        if source_reviewed is not True:
            raise ValueError('trusted source/account/host fingerprint review required')
        self.tick(now)
        if response['status'] == 'revoked':
            if self.authorization == 'revoked':
                raise ValueError('already revoked')
            # The host may have authorized before its response reached the phone.
            # A reviewed matching revocation closes that unknown cleanup state.
            self.authorization = 'revoked'
            self.state = 'revoked'
            self.consumed = True
            self.generation += 1
            return
        if self.state != 'awaiting-host' or self.consumed:
            raise ValueError('cancelled/expired/already consumed')
        if response['expires_at'] > self.request['expires_at']:
            raise ValueError('response extends request lifetime')
        self.authorization = 'authorized'
        self.authorization_added = response['authorization_added']
        self.state = 'authorized-unverified'
        self.consumed = True

    def connect(self, *, explicit: bool) -> int:
        if explicit is not True or self.state not in ('authorized-unverified', 'waiting-connectivity'):
            raise ValueError('explicit connection with live authorization required')
        self.generation += 1
        self.state = 'connecting'
        return self.generation

    def connection_result(self, generation: int, *, pinned_ssh_authenticated: bool):
        if type(pinned_ssh_authenticated) is not bool:
            raise ValueError('typed SSH verification event required')
        if generation != self.generation or self.state != 'connecting':
            return False
        self.state = 'paired' if pinned_ssh_authenticated else 'waiting-connectivity'
        return True

    def cancel(self):
        self.generation += 1
        self.state = 'cancelled'  # does not remove a host key or generate a replacement


class FixturePairingHost:
    """Offline helper adapter over a newly-created FixtureStore, never a host home.

    Consumption/revocation metadata live only in this process. No production
    persistence, concurrency guarantee, automatic approval or network transport.
    """
    def __init__(self, *, host_public_key: str, fixture_account: str = 'fixture-user'):
        if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', fixture_account):
            raise ValueError('invalid fixture account')
        self.fixture_account = fixture_account
        self.host_key = fingerprint(host_public_key)
        self.store = FixtureStore()
        self._records: dict[str, tuple[dict, object, str]] = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.store.__exit__(*args)

    def _request(self, raw: bytes, *, now: int) -> dict:
        req = decode(raw, now=now)
        if req['type'] != REQUEST or req['account'] != self.fixture_account or req['host_key'] != self.host_key:
            raise ValueError('only the explicit fixture target is supported')
        return req

    def preview(self, raw: bytes, *, now: int) -> dict:
        req = self._request(raw, now=now)
        return {'account': req['account'], 'device': req['device'],
                'fingerprint': fingerprint(req['public_key']), 'host_key': self.host_key,
                'proposed_change': 'append one public key to a new temporary authorization.fixture',
                'confirmation': CONFIRM_ADD, 'real_authorization': False}

    def authorize(self, raw: bytes, *, now: int, confirmation: str) -> bytes:
        req = self._request(raw, now=now)
        if confirmation != CONFIRM_ADD:
            raise ValueError('host-side fixture confirmation required')
        rid = req['request_id']
        if rid in self._records:
            old, receipt, state = self._records[rid]
            if req != old or state != 'authorized':
                raise ValueError('request reuse/revoked request')
        else:
            receipt = self.store.authorize(req, confirmation)
            self._records[rid] = (req, receipt, 'authorized')
        return self._response(req, now=now, status='authorized', added=receipt.added_line is not None)

    def revoke(self, request_id: str, *, now: int, confirmation: str) -> bytes:
        if confirmation != CONFIRM_REVOKE:
            raise ValueError('host-side fixture revoke confirmation required')
        req, receipt, state = self._records[request_id]
        if state == 'revoked':
            raise ValueError('already revoked')
        if receipt.added_line is None:
            raise ValueError('pre-existing key is not owned; manual revocation required')
        if not self.store.revoke(receipt, confirmation):
            raise ValueError('owned line missing; revocation unverified')
        self._records[request_id] = (req, receipt, 'revoked')
        return self._response(req, now=now, status='revoked', added=True)

    def _response(self, req: dict, *, now: int, status: str, added: bool) -> bytes:
        return encode({'version': VERSION, 'type': RESPONSE, 'request_id': req['request_id'],
            'account': req['account'], 'host_key': self.host_key, 'issued_at': now,
            'expires_at': min(req['expires_at'], now + MAX_TTL) if status == 'authorized' else now + MAX_TTL,
            'fingerprint': fingerprint(req['public_key']), 'status': status, 'authorization_added': added})
