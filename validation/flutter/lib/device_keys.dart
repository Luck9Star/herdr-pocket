import 'package:flutter/services.dart';
import 'package:flutter/foundation.dart';
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
  static bool get linuxStore => !kIsWeb && defaultTargetPlatform == TargetPlatform.linux;
  Future<T> _call<T>(String method, [Map<String,Object?>? args]) async {
    try {
      final value = await channel.invokeMethod<T>(method,args);
      if (value == null) throw const RemoteFailure('device_key_unavailable');
      return value;
    } catch (error) { throw _nativeFailure(error); }
  }
  RemoteFailure _nativeFailure(Object error) {
    if (linuxStore && error is PlatformException && const {
      'device_key_missing','device_key_locked','device_key_store_unavailable',
      'device_key_write_unknown','device_key_handle_exists',
    }.contains(error.code)) return RemoteFailure(error.code);
    return const RemoteFailure('device_key_unavailable');
  }
  Future<String> reserve() async {
    final handle = await _call<String>('reserve');
    if (!RegExp(r'^[0-9a-f]{32}$').hasMatch(handle)) throw const RemoteFailure('device_key_unavailable');
    return handle;
  }
  Future<void> createReserved(String handle) async {
    await _call<String>('createReserved',{'handle':handle});
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
    catch (error) { throw _nativeFailure(error); }
  }
}

String? linuxDeviceKeyNotice(Object error) => switch (error is RemoteFailure ? error.code : '') {
  'device_key_locked' => '系统密钥环已锁定 · 请解锁后核验原设备身份',
  'device_key_missing' => '系统密钥环中未找到原设备密钥 · 请检查原密钥环和身份引用',
  'device_key_store_unavailable' => '系统密钥环服务不可用 · 请配置 Secret Service 后核验原设备身份',
  'device_key_write_unknown' || 'device_key_handle_exists' => '设备密钥写入结果待核验 · 请核验已保存的原身份引用',
  _ => null,
};

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
        catch (error) {
          if (linuxDeviceKeyNotice(error) != null) rethrow;
          throw const RemoteFailure('device_key_unavailable');
        }
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
