import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/foundation.dart' show ChangeNotifier,TargetPlatform,defaultTargetPlatform,kIsWeb;
import 'package:flutter/services.dart' show MethodChannel;
import 'network_profiles.dart';
import 'remote_adapter.dart';

const networkSecretModes = ['PRIVATE', 'PUBLIC_NO_SECRET'];
final _identityUuid = RegExp(r'^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$');

/// Public native metadata only. Never part of the transferable catalog.
class NetworkIdentityRecord {
  NetworkIdentityRecord._(this.profileId,this.provider,this.handle,this.instanceId,this.mode);
  final String profileId,provider,handle,instanceId,mode;
  factory NetworkIdentityRecord.checked(dynamic value,NetworkProfile profile) {
    const fields = {'profileId','provider','handle','instanceId','mode'};
    if (value is! Map || value.length != fields.length || !value.keys.every(fields.contains) ||
        value['profileId'] != profile.id || value['provider'] != profile.provider ||
        value['handle'] is! String || !_identityUuid.hasMatch(value['handle'] as String) ||
        value['instanceId'] is! String || !_identityUuid.hasMatch(value['instanceId'] as String) ||
        !networkSecretModes.contains(value['mode'])) throw const RemoteFailure('network_identity_unavailable');
    return NetworkIdentityRecord._(profile.id,profile.provider,value['handle'] as String,
      value['instanceId'] as String,value['mode'] as String);
  }
}

void validateNetworkSecret(String mode,Uint8List secret) {
  if (!networkSecretModes.contains(mode) || secret.length > 1024 || secret.contains(0) ||
      (mode == 'PRIVATE' ? secret.isEmpty : secret.isNotEmpty)) {
    throw const RemoteFailure('invalid_network_secret');
  }
  try { utf8.decode(secret,allowMalformed:false); }
  catch (_) { throw const RemoteFailure('invalid_network_secret'); }
}

abstract interface class NetworkIdentityStore {
  bool get supported;
  Future<NetworkIdentityRecord?> status(NetworkProfile profile);
  Future<NetworkIdentityRecord> create(NetworkProfile profile,String mode,Uint8List secret);
  Future<void> delete(NetworkProfile profile,NetworkIdentityRecord identity);
}

/// Write-only provisioning; no secret, TOML or identity-export read channel.
class NativeNetworkIdentityStore implements NetworkIdentityStore {
  static const channel = MethodChannel('dev.herdr/network-identity');
  @override
  bool get supported => !kIsWeb && defaultTargetPlatform == TargetPlatform.android;
  void check(NetworkProfile profile) {
    if (!supported || profile.provider != 'easytier') throw const RemoteFailure('network_identity_unsupported');
  }
  Map<String,Object> args(NetworkProfile profile) => {'profileId':profile.id,'provider':profile.provider};
  @override
  Future<NetworkIdentityRecord?> status(NetworkProfile profile) async {
    check(profile);
    try {
      final reply = await channel.invokeMethod<Object?>('status',args(profile));
      return reply == null ? null : NetworkIdentityRecord.checked(reply,profile);
    } catch (_) { throw const RemoteFailure('network_identity_unavailable'); }
  }
  @override
  Future<NetworkIdentityRecord> create(NetworkProfile profile,String mode,Uint8List secret) async {
    check(profile); validateNetworkSecret(mode,secret);
    final bytes = Uint8List.fromList(secret);
    try {
      return NetworkIdentityRecord.checked(await channel.invokeMethod<Object?>('create',
        {...args(profile),'mode':mode,'secret':bytes}),profile);
    } catch (_) { throw const RemoteFailure('network_identity_write_unknown'); }
    finally { bytes.fillRange(0,bytes.length,0); }
  }
  @override
  Future<void> delete(NetworkProfile profile,NetworkIdentityRecord identity) async {
    check(profile);
    if (identity.profileId != profile.id || identity.provider != profile.provider) {
      throw const RemoteFailure('network_identity_unavailable');
    }
    try { await channel.invokeMethod<void>('delete',{...args(profile),'handle':identity.handle}); }
    catch (_) { throw const RemoteFailure('network_identity_write_unknown'); }
  }
}

/// One visible profile review. Unknown writes are only followed by a read;
/// no implicit retry, replacement, cleanup mutation or network connection.
class NetworkIdentitySession extends ChangeNotifier {
  NetworkIdentitySession({required this.profile,required this.store,
    required this.stillCurrent,required this.closeAffected});
  final NetworkProfile profile;
  final NetworkIdentityStore store;
  final bool Function() stillCurrent;
  final void Function() closeAffected;
  NetworkIdentityRecord? record;
  bool known = false,busy = false,_disposed = false;
  String? notice;
  bool get supported => store.supported && profile.provider == 'easytier';
  bool get canCreate => supported && known && record == null && !busy && stillCurrent();
  bool get canDelete => supported && known && record != null && !busy && stillCurrent();
  void publish() { if (!_disposed) notifyListeners(); }
  Future<bool> readStatus() async {
    record = null; known = false;
    try { record = await store.status(profile); known = true; return true; }
    catch (_) { return false; }
  }
  Future<void> refresh() async {
    if (busy || _disposed || !supported) return;
    busy = true; notice = null; publish();
    final read = await readStatus();
    if (!read) notice = '本机资料不可读取 · 请解锁设备后重新读取；不会新建或替换身份。';
    busy = false; publish();
  }
  Future<void> create(String mode,Uint8List secret) async {
    // Own and clear this short-lived input even when a stale/duplicate action is refused.
    try {
      if (!canCreate || _disposed) return;
      validateNetworkSecret(mode,secret);
      busy = true; known = false; notice = null; publish();
      NetworkIdentityRecord? created;
      try {
        if (!stillCurrent()) throw const RemoteFailure('network_binding_changed');
        closeAffected();
        created = await store.create(profile,mode,secret);
      } catch (_) { /* Only a read is permitted after an unknown mutation. */ }
      finally { secret.fillRange(0,secret.length,0); }
      final read = await readStatus();
      final matched = read && created != null && record?.handle == created.handle &&
        record?.instanceId == created.instanceId && record?.mode == mode && stillCurrent();
      notice = matched
        ? '本机入网资料已保存 · 尚未启动节点或验证连通，不会自动连接。'
        : '保存结果未确认 · 已重新读取本机状态；先核对，不会重发或替换身份。';
      busy = false; publish();
    } finally { secret.fillRange(0,secret.length,0); }
  }
  Future<void> delete() async {
    if (!canDelete || _disposed) return;
    final original = record!;
    busy = true; known = false; notice = null; publish();
    var acknowledged = false;
    try {
      if (!stillCurrent()) throw const RemoteFailure('network_binding_changed');
      closeAffected();
      await store.delete(profile,original); acknowledged = true;
    } catch (_) { /* A late completion must not cause a second delete. */ }
    final read = await readStatus();
    notice = acknowledged && read && record == null
      ? '本机入网资料已移除 · SSH 配对密钥和其他网络未改动。'
      : '移除结果未确认 · 先读取并核对当前状态，不会重复删除。';
    busy = false; publish();
  }
  @override
  void dispose() { _disposed = true; super.dispose(); }
}
