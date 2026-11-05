import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/pairing.dart';
import 'remote_test_data.dart';

void main() {
  final key = fixtureConfig()['expectedHostKey'] as String;
  PendingDevicePairing pending() => PendingDevicePairing(handle:'opaque-local',publicKey:key,account:'fixture_user',
    hostKey:pairingFingerprint(key),device:'Test phone',now:1000);
  Map<String,dynamic> response(PendingDevicePairing p) => {
    'version':2,'type':'pairing-binding-response','request_id':p.request['request_id'],
    'account':p.request['account'],'host_key':p.request['host_key'],'issued_at':1000,'expires_at':1600,
    'fingerprint':pairingFingerprint(key),'status':'authorized','authorization_added':true,
  };
  test('strict UTF8 flat v2 rejects duplicate escaped fields, controls, bad TTL and unknowns',() {
    final p = pending(); final wire = p.wire;
    for (final text in [wire.replaceFirst('{','{"version":2,'),wire.replaceFirst('"version":2','"version":2,"\\u0076ersion":2'),
      wire.replaceFirst('Test phone',r'Test\u000aphone'),wire.replaceFirst('1600','1601'),wire.replaceFirst('{','{"extra":true,')]) {
      expect(() => decodePairing(Uint8List.fromList(utf8.encode(text)),1000),throwsA(isA<Exception>()));
    }
    expect(() => decodePairing(Uint8List.fromList([255,254,0,0]),1000),throwsA(isA<Exception>()));
  });
  test('review, full binding, expiry, consumed response and late generation fail closed',() {
    final p = pending(); final r = response(p);
    expect(() => p.accept(jsonEncode(r),now:1000,reviewed:false),throwsA(isA<Exception>()));
    expect(() => p.accept(jsonEncode({...r,'account':'other'}),now:1000,reviewed:true),throwsA(isA<Exception>()));
    p.accept(jsonEncode(r),now:1000,reviewed:true); expect(p.state,'authorized-unverified');
    expect(() => p.accept(jsonEncode(r),now:1000,reviewed:true),throwsA(isA<Exception>()));
    final generation = p.connect(); p.cancel(); p.connectionResult(generation,true); expect(p.state,'cancelled');
    final q = pending(); q.tick(1600); expect(() => q.accept(jsonEncode(response(q)),now:1000,reviewed:true),throwsA(isA<Exception>()));
  });
  test('unknown authorization after cancellation can accept reviewed matching revocation only',() {
    final p = pending(); p.cancel();
    p.accept(jsonEncode({...response(p),'status':'revoked'}),now:1000,reviewed:true);
    expect(p.state,'revoked'); expect(() => p.accept(jsonEncode(response(p)),now:1000,reviewed:true),throwsA(isA<Exception>()));
  });
}
