import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';
import 'pairing_public_key.dart';
export 'pairing_public_key.dart';
import 'remote_adapter.dart';

/// Flat v2 wire grammar: rejecting duplicate decoded keys before JSON decoding
/// also catches escaped duplicates. Nested values, non-UTF8, BOM and controls
/// are rejected; no unbounded recursive parser is used on untrusted input.
Map<String,dynamic> decodePairing(Uint8List raw,int now) {
  if (raw.isEmpty || raw.length > 2048) throw const RemoteFailure('invalid_pairing');
  try {
    final text = utf8.decode(raw);
    var at = 0;
    void ws() { while (at < text.length && ' \r\n\t'.contains(text[at])) { at++; } }
    String token(RegExp pattern) {
      ws(); final match = pattern.matchAsPrefix(text,at);
      if (match == null) throw const FormatException();
      at = match.end; return match[0]!;
    }
    final quoted = RegExp(r'"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"');
    final primitive = RegExp(r'"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"|true|false|0|[1-9][0-9]*');
    token(RegExp(r'\{'));
    final result = <String,dynamic>{};
    while (true) {
      final key = jsonDecode(token(quoted)) as String;
      if (result.containsKey(key)) throw const FormatException();
      token(RegExp(':')); result[key] = jsonDecode(token(primitive)); ws();
      if (at < text.length && text[at] == ',') { at++; continue; }
      token(RegExp(r'\}')); ws(); if (at != text.length) throw const FormatException(); break;
    }
    const base = {'version','type','request_id','account','host_key','issued_at','expires_at'};
    final expected = result['type'] == 'pairing-public-key-request' ? {...base,'device','public_key'} :
      result['type'] == 'pairing-binding-response' ? {...base,'fingerprint','status','authorization_added'} : <String>{};
    if (expected.isEmpty || result.length != expected.length || !result.keys.every(expected.contains) || result['version'] != 2) throw const FormatException();
    bool matches(String key,String pattern) => result[key] is String && RegExp('^(?:$pattern)\$').hasMatch(result[key] as String);
    if (!matches('request_id',r'[a-f0-9]{32}') || !matches('account',r'[a-z_][a-z0-9_-]{0,31}') ||
        !matches('host_key',r'SHA256:[A-Za-z0-9+/]{43}')) throw const FormatException();
    final start = result['issued_at'], end = result['expires_at'];
    if (start is! int || end is! int || start < 0 || start > now || now >= end || end-start < 1 || end-start > 600 || end > 9007199254740991) throw const FormatException();
    if (result['type'] == 'pairing-public-key-request') {
      if (!matches('device',r'[A-Za-z0-9 -]{1,48}')) throw const FormatException();
      pairingPublicBlob(result['public_key'] as String);
    } else if (!matches('fingerprint',r'SHA256:[A-Za-z0-9+/]{43}') ||
        !['authorized','revoked'].contains(result['status']) || result['authorization_added'] is! bool) { throw const FormatException(); }
    return result;
  } catch (_) { throw const RemoteFailure('invalid_pairing'); }
}

class PendingDevicePairing {
  PendingDevicePairing({required this.handle,required String publicKey,required String account,
    required String hostKey,required String device,required int now}) {
    final random = Random.secure();
    request = decodePairing(Uint8List.fromList(utf8.encode(jsonEncode({
      'version':2,'type':'pairing-public-key-request',
      'request_id':List.generate(16,(_) => random.nextInt(256).toRadixString(16).padLeft(2,'0')).join(),
      'account':account,'host_key':hostKey,'device':device,'public_key':publicKey,'issued_at':now,'expires_at':now+600,
    }))),now);
  }
  PendingDevicePairing._restored(this.handle,Map<String,dynamic> restored) { request = restored; }
  final String handle;
  late final Map<String,dynamic> request;
  String state = 'awaiting-host', authorization = 'unknown';
  bool consumed = false;
  int generation = 0;
  String get wire => jsonEncode(request);
  void tick(int now) {
    if (state == 'awaiting-host' && now >= (request['expires_at'] as int)) { state = 'expired'; generation++; }
  }
  void accept(String raw,{required int now,required bool reviewed}) {
    final response = decodePairing(Uint8List.fromList(utf8.encode(raw)),now);
    if (!reviewed || response['type'] != 'pairing-binding-response' ||
        ['request_id','account','host_key'].any((k) => response[k] != request[k]) ||
        response['fingerprint'] != pairingFingerprint(request['public_key'] as String)) throw const RemoteFailure('pairing_binding_mismatch');
    tick(now);
    if (response['status'] == 'revoked') {
      if (authorization == 'revoked') throw const RemoteFailure('pairing_replay');
      authorization = 'revoked'; state = 'revoked'; consumed = true; generation++; return;
    }
    if (state != 'awaiting-host' || consumed || (response['expires_at'] as int) > (request['expires_at'] as int)) throw const RemoteFailure('pairing_replay');
    authorization = 'authorized'; state = 'authorized-unverified'; consumed = true;
  }
  int connect() {
    if (!['authorized-unverified','waiting-connectivity','paired'].contains(state)) throw const RemoteFailure('pairing_unavailable');
    state = 'connecting'; return ++generation;
  }
  void connectionResult(int ticket,bool authenticated) {
    if (generation != ticket || state != 'connecting') return;
    state = authenticated ? 'paired' : 'waiting-connectivity';
  }
  void cancel() { state = 'cancelled'; generation++; }
}

extension PairingPersistence on PendingDevicePairing {
  Map<String,dynamic> toPublicRecord() => {
    'handle':handle,'request':Map<String,dynamic>.from(request),
    'state':state == 'connecting' || state == 'paired' ? 'waiting-connectivity' : state,
    'authorization':authorization,'consumed':consumed,
  };
}

PendingDevicePairing restoreDevicePairing(Map<String,dynamic> record,int now) {
  const fields = {'handle','request','state','authorization','consumed'};
  if (record.length != fields.length || !record.keys.every(fields.contains) ||
      record['handle'] is! String || !RegExp(r'^[A-Za-z0-9_-]{1,128}$').hasMatch(record['handle'] as String) ||
      record['request'] is! Map<String,dynamic> || record['consumed'] is! bool ||
      !['awaiting-host','expired','cancelled','authorized-unverified','waiting-connectivity','paired','connecting','revoked'].contains(record['state']) ||
      !['unknown','authorized','revoked'].contains(record['authorization'])) throw const RemoteFailure('invalid_catalog');
  final request = Map<String,dynamic>.from(record['request'] as Map);
  final start = request['issued_at'];
  if (start is! int || start > now) throw const RemoteFailure('invalid_catalog');
  final validated = decodePairing(Uint8List.fromList(utf8.encode(jsonEncode(request))),start);
  if (validated['type'] != 'pairing-public-key-request') throw const RemoteFailure('invalid_catalog');
  final authorization = record['authorization'] as String, state = record['state'] as String;
  final consumed = record['consumed'] as bool;
  if ((authorization == 'authorized' && !consumed) ||
      (['authorized-unverified','waiting-connectivity','paired','connecting'].contains(state) && authorization != 'authorized') ||
      (authorization == 'revoked' && (state != 'revoked' || !consumed)) ||
      (state == 'revoked' && authorization != 'revoked') ||
      (state == 'awaiting-host' && (authorization != 'unknown' || consumed))) throw const RemoteFailure('invalid_catalog');
  final p = PendingDevicePairing._restored(record['handle'] as String,validated);
  p.state = ['paired','connecting'].contains(state) ? 'waiting-connectivity' : state;
  p.authorization = authorization; p.consumed = consumed; p.tick(now);
  return p;
}
