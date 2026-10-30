import 'dart:convert';
import 'dart:typed_data';
import 'package:dartssh2/dartssh2.dart';

Map<String,dynamic> fixtureConfig() {
  // Parser-only synthetic material, generated in memory. Never an authorization key.
  final pair = OpenSSHEd25519KeyPair(Uint8List(32),Uint8List(64),'parser-only');
  return {'schemaVersion':1,'host':'127.0.0.1','port':2222,'username':'fixture',
    'expectedHostKey':'ssh-ed25519 ${base64Encode(pair.toPublicKey().encode())}',
    'privateKeyPem':pair.toPem(),'socketPath':'/tmp/fixture-config/herdr/sessions/probe/herdr.sock',
    'herdrPath':'/tmp/fixture/herdr','session':'probe','paneId':'w1:p1','reviewConfirmed':true};
}
