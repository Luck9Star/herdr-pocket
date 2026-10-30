"""A new temporary fixture per run. Accepts no key, host, home or filesystem path."""
import argparse
import json
from pairing import MemoryKeyStore, PendingPairing, FixturePairingHost, CONFIRM_ADD, CONFIRM_REVOKE, encode, fingerprint


def demo(confirmation=''):
    keys = MemoryKeyStore()
    handle = keys.create()
    host_public = keys.public(keys.create())
    phone = PendingPairing(keys, handle, account='fixture-user', expected_host_key=fingerprint(host_public),
                           device='Fixture phone', now=100)
    events = [phone.state]
    with FixturePairingHost(host_public_key=host_public) as host:
        preview = host.preview(encode(phone.request), now=100)
        if confirmation != CONFIRM_ADD:
            return {'scope':'fixture-only', 'confirmed':False, 'fixtureBytesChanged':0,
                    'states':events, 'preview':preview, 'systemKeychainCalls':0, 'sshConnections':0}
        response = host.authorize(encode(phone.request), now=101, confirmation=confirmation)
        phone.accept(response, now=102, source_reviewed=True)
        events.append(phone.state)
        generation = phone.connect(explicit=True)
        phone.connection_result(generation, pinned_ssh_authenticated=False)
        events.append(phone.state)
        phone.cancel()
        events.append(phone.state)
        revoke = host.revoke(phone.request['request_id'], now=800, confirmation=CONFIRM_REVOKE)
        phone.accept(revoke, now=801, source_reviewed=True)
        events.append(phone.state)
        return {'scope':'fixture-only', 'confirmed':True, 'states':events,
                'emptyAfterRevoke':host.store.read()==b'', 'systemKeychainCalls':0, 'sshConnections':0,
                'privateKeysExported':False, 'nativeDeviceStorage':'not-executed',
                'sshSuccess':'not-executed', 'responseAuthenticity':'requires-trusted-source-review'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', required=True, action='store_true')
    parser.add_argument('--confirm-fixture', default='')
    args = parser.parse_args()
    print(json.dumps(demo(args.confirm_fixture), indent=2))
