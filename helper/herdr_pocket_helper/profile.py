"""Produce public connection coordinates; this format conveys no authorization."""
import ipaddress
import re

from .wire import MAX_BYTES, encode, public_key


FIELDS = {'version', 'type', 'host', 'port', 'username', 'provider', 'session',
          'socketPath', 'herdrPath', 'expectedHostKey'}
PROVIDERS = ('direct', 'tailscale', 'easytier', 'zerotier')


def _path(value):
    if (not isinstance(value, str) or not value.startswith('/')
            or not 1 <= len(value.encode('utf-8')) <= 1024
            or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)
            or any(part in ('', '.', '..') for part in value.split('/')[1:])):
        raise ValueError('canonical absolute path required')


def _host(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 253 or not value.isascii():
        raise ValueError('ASCII hostname or unbracketed IPv6 required')
    if ':' in value:
        if any(char in value for char in '[]%'):
            raise ValueError('IPv6 zones and brackets are unsupported')
        ipaddress.IPv6Address(value)
        return
    label = r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?'
    if any(re.fullmatch(label, part) is None for part in value.split('.')):
        raise ValueError('invalid DNS hostname')


def encode_profile(obj):
    """Validate the producer's complete flat v1 object and encode it as JSON."""
    if (not isinstance(obj, dict) or set(obj) != FIELDS
            or type(obj['version']) is not int or obj['version'] != 1
            or obj['type'] != 'herdr-connection-profile'):
        raise ValueError('unknown connection profile type/version/field')
    _host(obj['host'])
    if type(obj['port']) is not int or not 1 <= obj['port'] <= 65535:
        raise ValueError('integer SSH port required')
    for name, pattern in (('username', r'[a-z_][a-z0-9_-]{0,31}'),
                          ('session', r'[A-Za-z0-9_-]{1,64}')):
        if not isinstance(obj[name], str) or re.fullmatch(pattern, obj[name]) is None:
            raise ValueError('invalid username/session')
    if obj['session'] == 'default' or obj['provider'] not in PROVIDERS:
        raise ValueError('named session and known provider required')
    _path(obj['socketPath'])
    _path(obj['herdrPath'])
    suffix = '/herdr/sessions/' + obj['session'] + '/herdr.sock'
    if not obj['socketPath'].endswith(suffix) or len(obj['socketPath']) <= len(suffix):
        raise ValueError('socket must use a nonempty root and match the named session')
    public_key(obj['expectedHostKey'])
    raw = encode(obj, ensure_ascii=False)
    if len(raw) > MAX_BYTES:
        raise ValueError('connection profile exceeds 2048 UTF-8 bytes')
    return raw
