import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/device_keys.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'pairing_gui_test.dart' show TestDeviceKeys;
import 'remote_test_data.dart';

void main() {
  test('opaque asynchronous signer emits complete Ed25519 SSH signature envelope',() async {
    final store = TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
    final handle = await store.create(); final public = await store.public(handle);
    final lease = DeviceIdentityLease(store,handle,public);
    final identity = lease.identity(); final challenge = Uint8List.fromList([1,2,3,4]);
    expect(identity.shouldProbe,isTrue);
    final encoded = (await identity.sign(challenge)).encode();
    expect(encoded.length,83); expect(ByteData.sublistView(encoded).getUint32(0),11);
    expect(String.fromCharCodes(encoded.sublist(4,15)),'ssh-ed25519');
    expect(ByteData.sublistView(encoded).getUint32(15),64);
    expect(encoded,store.key.sign(challenge).encode());
    final config = RemoteConfig.fromDeviceJson({...fixtureConfig()}..remove('privateKeyPem'),identity);
    expect(config.privateKeyPem,isEmpty);
    expect(() => RemoteConfig.fromDeviceJson(fixtureConfig(),identity),throwsA(isA<RemoteFailure>()));
    lease.cancel();
    await expectLater(identity.sign(challenge),throwsA(isA<RemoteFailure>()));
    expect(store.signCalls,1);
  });
  test('locked native-equivalent backend cannot sign or create replacement through lease',() async {
    final store = TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
    final handle = await store.create(); final public = await store.public(handle);
    final lease = DeviceIdentityLease(store,handle,public); store.locked = true;
    await expectLater(lease.identity().sign(Uint8List(1)),throwsA(isA<RemoteFailure>()));
    expect(store.creates,1); expect(store.signCalls,0);
  });
}
