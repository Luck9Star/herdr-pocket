import 'dart:convert';
import 'dart:typed_data';
import 'package:pointycastle/digests/sha256.dart';
import 'remote_failure.dart';

Uint8List pairingPublicBlob(String value) {
  final m = RegExp(r'^ssh-ed25519 ([A-Za-z0-9+/]+={0,2})$').firstMatch(value);
  if (m == null) throw const RemoteFailure('invalid_public_key');
  try {
    final b = base64Decode(m[1]!);
    if (b.length != 51 || base64Encode(b) != m[1] || ByteData.sublistView(b).getUint32(0) != 11 ||
        ascii.decode(b.sublist(4,15)) != 'ssh-ed25519' || ByteData.sublistView(b).getUint32(15) != 32) {
      throw const FormatException();
    }
    return b;
  } catch (_) { throw const RemoteFailure('invalid_public_key'); }
}
String pairingFingerprint(String publicKey) => 'SHA256:${base64Encode(SHA256Digest().process(pairingPublicBlob(publicKey))).replaceAll('=', '')}';
