import 'dart:typed_data';
import 'package:flutter/services.dart';
import 'package:dartssh2/dartssh2.dart';
import 'pairing.dart';
import 'remote_adapter.dart';

/// Four-method boundary. Neither seed nor private key crosses the channel.
abstract interface class DeviceKeys {
  Future<String> create();
  Future<String> public(String handle);
  Future<Uint8List> sign(String handle, Uint8List payload);
  Future<void> delete(String handle);
}

class NativeDeviceKeys implements DeviceKeys {
  static const channel = MethodChannel('dev.herdr/device-keys');
  Future<T> _call<T>(String method, [Map<String,Object?>? args]) async {
    try {
      final value = await channel.invokeMethod<T>(method,args);
      if (value == null) throw const RemoteFailure('device_key_unavailable');
      return value;
    } catch (_) { throw const RemoteFailure('device_key_unavailable'); }
  }
  @override
  Future<String> create() => _call<String>('create');
  @override
  Future<String> public(String handle) => _call<String>('public',{'handle':handle});
  @override
  Future<Uint8List> sign(String handle,Uint8List payload) async {
    if (payload.length > 65536) throw const RemoteFailure('signature_limit');
    final bytes = await _call<Uint8List>('sign',{'handle':handle,'payload':payload});
    if (bytes.length != 64) throw const RemoteFailure('invalid_signature');
    return bytes;
  }
  @override
  Future<void> delete(String handle) async {
    try { await channel.invokeMethod<void>('delete',{'handle':handle}); }
    catch (_) { throw const RemoteFailure('device_key_unavailable'); }
  }
}

/// Each connection gets a revocable identity lease. A late native completion
/// cannot authenticate a cancelled attempt. SSHRawSignature needs the complete
/// RFC 4253 signature blob, not just the 64 raw Ed25519 signature bytes.
class DeviceIdentityLease {
  DeviceIdentityLease(this.store,this.handle,this.publicKey);
  final DeviceKeys store;
  final String handle, publicKey;
  bool active = true;
  void cancel() { active = false; }
  SSHIdentity identity() {
    final publicBlob = pairingPublicBlob(publicKey);
    return SSHIdentity.custom(type:'ssh-ed25519',publicKey:SSHRawHostKey(publicBlob),shouldProbe:true,
      signer:(payload) async {
        if (!active) throw const RemoteFailure('cancelled');
        Uint8List signature;
        try { signature = await store.sign(handle,Uint8List.fromList(payload)); }
        catch (_) { throw const RemoteFailure('device_key_unavailable'); }
        if (!active) throw const RemoteFailure('cancelled');
        if (signature.length != 64) throw const RemoteFailure('invalid_signature');
        final blob = Uint8List(4 + 11 + 4 + 64);
        final view = ByteData.sublistView(blob);
        view.setUint32(0,11); blob.setRange(4,15,'ssh-ed25519'.codeUnits);
        view.setUint32(15,64); blob.setRange(19,83,signature);
        return SSHRawSignature(blob);
      });
  }
}
