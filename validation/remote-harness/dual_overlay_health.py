#!/usr/bin/env python3
"""Passive, local-only SSH fixture check. Never sends terminal input."""
import json
import socket
import sys


def rpc(path, method):
    request = {'id': 'fixture-health', 'method': method, 'params': {}}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.settimeout(5)
        stream.connect(path)
        stream.sendall(json.dumps(request).encode() + b'\n')
        data = bytearray()
        while b'\n' not in data and len(data) <= 1048576:
            chunk = stream.recv(4096)
            if not chunk:
                break
            data.extend(chunk)
    if len(data) > 1048576:
        raise ValueError('reply_too_large')
    reply = json.loads(data.split(b'\n', 1)[0])
    if reply.get('id') != 'fixture-health' or not isinstance(reply.get('result'), dict):
        raise ValueError('reply_invalid')
    return reply['result']


def check(path):
    snapshot = rpc(path, 'session.snapshot')
    capabilities = rpc(path, 'pocket.input.capabilities')
    return {'snapshot': isinstance(snapshot.get('snapshot'), dict),
            'inputCapability': (capabilities.get('type') == 'pocket_input_capabilities'
                and capabilities.get('version') == 1 and capabilities.get('protocol') == 22
                and capabilities.get('atomic_terminal_guard') is True
                and capabilities.get('raw_bytes') is True
                and capabilities.get('max_input_bytes') == 4096)}


def main():
    try:
        result = check(sys.argv[1])
    except (OSError, ValueError, IndexError, TypeError):
        result = {'snapshot': False, 'inputCapability': False}
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
