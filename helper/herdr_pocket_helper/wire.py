"""Shared v2 public pairing wire format, also used by the isolated probes."""
import base64
import hashlib
import json
import re
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, load_ssh_public_key

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
    if not isinstance(value, str) or len(value) > 128 or re.fullmatch(r"ssh-ed25519 [A-Za-z0-9+/]+={0,2}", value) is None:
        raise ValueError("canonical Ed25519 public key required")
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


def encode(obj: dict, *, ensure_ascii: bool = True) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=ensure_ascii).encode('utf-8')


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
