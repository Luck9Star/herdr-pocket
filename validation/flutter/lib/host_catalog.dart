import 'dart:convert';
import 'dart:math';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'pairing.dart';
import 'remote_adapter.dart';

const maxHostProfiles = 16;
const maxCatalogBytes = 262144;
const hostProviders = ['unspecified','direct','tailscale','easytier','zerotier'];
String hostProviderLabel(String provider) => switch (provider) {
  'direct' => '直连配置', 'tailscale' => 'Tailscale 配置', 'easytier' => 'EasyTier 配置',
  'zerotier' => 'ZeroTier 配置', _ => '未指定网络',
};

/// Bounded JSON parser rejecting duplicate decoded keys at every nesting level.
/// Profile files are public metadata, never general configuration or key import.
dynamic decodeCatalogJson(String raw) {
  if (utf8.encode(raw).length > maxCatalogBytes) throw const RemoteFailure('invalid_catalog');
  var index = 0;
  void ws() { while (index < raw.length && ' \r\n\t'.contains(raw[index])) { index++; } }
  final quoted = RegExp(r'"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"');
  dynamic value(int depth) {
    if (depth > 8) throw const RemoteFailure('invalid_catalog');
    ws(); if (index >= raw.length) throw const RemoteFailure('invalid_catalog');
    if (raw[index] == '{') {
      index++; final map = <String,dynamic>{}; ws();
      if (index < raw.length && raw[index] == '}') { index++; return map; }
      while (true) {
        ws(); final keyMatch = quoted.matchAsPrefix(raw,index);
        if (keyMatch == null) throw const RemoteFailure('invalid_catalog');
        index = keyMatch.end; final key = jsonDecode(keyMatch[0]!) as String; ws();
        if (map.containsKey(key) || index >= raw.length || raw[index++] != ':') throw const RemoteFailure('invalid_catalog');
        map[key] = value(depth+1); ws();
        if (index >= raw.length) throw const RemoteFailure('invalid_catalog');
        if (raw[index] == '}') { index++; return map; }
        if (raw[index++] != ',') throw const RemoteFailure('invalid_catalog');
      }
    }
    if (raw[index] == '[') {
      index++; final list = <dynamic>[]; ws();
      if (index < raw.length && raw[index] == ']') { index++; return list; }
      while (true) {
        if (list.length >= maxHostProfiles) throw const RemoteFailure('invalid_catalog');
        list.add(value(depth+1)); ws();
        if (index >= raw.length) throw const RemoteFailure('invalid_catalog');
        if (raw[index] == ']') { index++; return list; }
        if (raw[index++] != ',') throw const RemoteFailure('invalid_catalog');
      }
    }
    final match = (raw[index] == '"' ? quoted : RegExp(r'true|false|null|0|[1-9][0-9]*')).matchAsPrefix(raw,index);
    if (match == null) throw const RemoteFailure('invalid_catalog');
    index = match.end; return jsonDecode(match[0]!);
  }
  try { final result = value(0); ws(); if (index != raw.length) throw const RemoteFailure('invalid_catalog'); return result; }
  catch (_) { throw const RemoteFailure('invalid_catalog'); }
}

class HostProfile {
  HostProfile._(this.id,this.label,this.enabled,this.target,this.pairingRecord,this.provider,[this.expectedPrevious]);
  final String id,label,provider;
  final String? expectedPrevious;
  final bool enabled;
  final Map<String,dynamic> target, pairingRecord;
  static const targetFields = {'host','port','username','expectedHostKey','socketPath','herdrPath','session','paneId'};
  factory HostProfile.fromJson(Map<String,dynamic> data,int now) {
    const fields = {'id','label','enabled','target','pairing','provider'};
    if (data.length != fields.length || !data.keys.every(fields.contains) || data['id'] is! String ||
        !RegExp(r'^[a-f0-9]{32}$').hasMatch(data['id'] as String) || data['label'] is! String ||
        (data['label'] as String).trim().isEmpty || (data['label'] as String).length > 64 ||
        RegExp(r'[\x00-\x1f\x7f]').hasMatch(data['label'] as String) || data['enabled'] is! bool ||
        !hostProviders.contains(data['provider']) || data['target'] is! Map<String,dynamic> || data['pairing'] is! Map<String,dynamic>) throw const RemoteFailure('invalid_catalog');
    final target = Map<String,dynamic>.from(data['target'] as Map);
    if (target.length != targetFields.length || !target.keys.every(targetFields.contains)) throw const RemoteFailure('invalid_catalog');
    final checked = RemoteConfig.fromJson({...target,'schemaVersion':1,'reviewConfirmed':true,'privateKeyPem':'catalog-validation-only'});
    checked.configRoot;
    final p = restoreDevicePairing(Map<String,dynamic>.from(data['pairing'] as Map),now);
    if (p.request['account'] != checked.username || p.request['host_key'] != checked.expectedFingerprint) throw const RemoteFailure('invalid_catalog');
    return HostProfile._(data['id'] as String,data['label'] as String,data['enabled'] as bool,
      Map.unmodifiable(target),Map.unmodifiable(p.toPublicRecord()),data['provider'] as String);
  }
  factory HostProfile.create(String label,Map<String,dynamic> target,PendingDevicePairing pairing,int now,{String provider='unspecified'}) {
    final random = Random.secure();
    return HostProfile.fromJson({'id':List.generate(16,(_) => random.nextInt(256).toRadixString(16).padLeft(2,'0')).join(),
      'label':label,'enabled':true,'provider':provider,'target':{for (final k in targetFields) k:target[k]},'pairing':pairing.toPublicRecord()},now);
  }
  Map<String,dynamic> toJson() => {'id':id,'label':label,'enabled':enabled,'provider':provider,'target':target,'pairing':pairingRecord};
  PendingDevicePairing restore(int now) => restoreDevicePairing(Map<String,dynamic>.from(pairingRecord),now);
  HostProfile change({String? label,String? provider,bool? enabled,PendingDevicePairing? pairing,required int now}) {
    final checked = HostProfile.fromJson({...toJson(),if (label != null) 'label':label,if (enabled != null) 'enabled':enabled,if (provider != null) 'provider':provider,
      if (pairing != null) 'pairing':pairing.toPublicRecord()},now);
    return HostProfile._(checked.id,checked.label,checked.enabled,checked.target,checked.pairingRecord,checked.provider,jsonEncode(toJson()));
  }
}

abstract interface class HostCatalogStorage {
  Future<({String revision,String contents})> load();
  Future<String> save(String expected,String contents);
}
class NativeHostCatalogStorage implements HostCatalogStorage {
  static const channel = MethodChannel('dev.herdr/host-catalog');
  @override
  Future<({String revision,String contents})> load() async {
    try {
      final reply = await channel.invokeMapMethod<String,String>('load');
      if (reply == null || reply.length != 2 || reply['revision'] == null || reply['contents'] == null) throw const RemoteFailure('catalog_unavailable');
      return (revision:reply['revision']!,contents:reply['contents']!);
    } catch (_) { throw const RemoteFailure('catalog_unavailable'); }
  }
  @override
  Future<String> save(String expected,String contents) async {
    try {
      final result = await channel.invokeMethod<String>('save',{'expected':expected,'contents':contents});
      if (result == null || !RegExp(r'^[a-f0-9]{64}$').hasMatch(result)) throw const RemoteFailure('catalog_unavailable');
      return result;
    } catch (_) { throw const RemoteFailure('catalog_write_unknown'); }
  }
}

Map<String,dynamic>? validatePendingCreation(dynamic data) {
  if (data == null) return null;
  if (data is! Map<String,dynamic> || data.length != 4 || !data.keys.every({'id','label','target','handle'}.contains) ||
      data['id'] is! String || !RegExp(r'^[a-f0-9]{32}$').hasMatch(data['id'] as String) || data['label'] is! String ||
      (data['label'] as String).trim().isEmpty || (data['label'] as String).length > 64 || RegExp(r'[\x00-\x1f\x7f]').hasMatch(data['label'] as String) ||
      data['handle'] is! String || !RegExp(r'^[A-Za-z0-9_-]{0,128}$').hasMatch(data['handle'] as String) ||
      data['target'] is! Map<String,dynamic>) throw const RemoteFailure('invalid_catalog');
  final target = Map<String,dynamic>.from(data['target'] as Map);
  if (target.length != HostProfile.targetFields.length || !target.keys.every(HostProfile.targetFields.contains)) throw const RemoteFailure('invalid_catalog');
  final checked = RemoteConfig.fromJson({...target,'schemaVersion':1,'reviewConfirmed':true,'privateKeyPem':'catalog-validation-only'});
  checked.configRoot;
  return Map.unmodifiable({...data,'target':Map.unmodifiable(target)});
}

class HostCatalog extends ChangeNotifier {
  HostCatalog({HostCatalogStorage? storage,int Function()? clock}) : storage = storage ?? NativeHostCatalogStorage(),
    clock = clock ?? (() => DateTime.now().millisecondsSinceEpoch ~/ 1000);
  final HostCatalogStorage storage;
  final int Function() clock;
  List<HostProfile> profiles = const [];
  Map<String,dynamic>? pendingCreation;
  String revision = '',status = '尚未读取本机主机资料';
  bool ready = false,writing = false;
  bool _disposed = false;
  void _notify() { if (!_disposed) notifyListeners(); }
  @override
  void dispose() { _disposed = true; generation++; super.dispose(); }
  int generation = 0;
  Future<void> _tail = Future.value();
  Future<void> load() async {
    if (_disposed) return;
    if (writing) throw const RemoteFailure('catalog_busy');
    final ticket = ++generation; ready = false; _notify();
    try {
      final raw = await storage.load();
      if (ticket != generation) return;
      if (!RegExp(r'^(?:[a-f0-9]{64})?$').hasMatch(raw.revision) || (raw.contents.isEmpty != raw.revision.isEmpty)) throw const RemoteFailure('invalid_catalog');
      final loaded = <HostProfile>[];
      if (raw.contents.isNotEmpty) {
        final data = decodeCatalogJson(raw.contents);
        if (data is! Map<String,dynamic> || data.length != 3 || !data.keys.every({'schemaVersion','profiles','pendingCreation'}.contains) || ![1,2].contains(data['schemaVersion']) || data['profiles'] is! List) throw const RemoteFailure('invalid_catalog');
        pendingCreation = validatePendingCreation(data['pendingCreation']);
        for (final item in data['profiles'] as List) {
          if (item is! Map<String,dynamic>) throw const RemoteFailure('invalid_catalog');
          final normalized = data['schemaVersion'] == 1 ? {...item,'provider':item['provider'] ?? 'unspecified'} : item;
          final p = HostProfile.fromJson(normalized,clock());
          if (loaded.any((old) => old.id == p.id || old.restore(clock()).handle == p.restore(clock()).handle)) throw const RemoteFailure('invalid_catalog');
          loaded.add(p);
        }
      }
      if (raw.contents.isEmpty) pendingCreation = null;
      profiles = List.unmodifiable(loaded); revision = raw.revision; ready = true;
      status = profiles.isEmpty ? '没有本机主机资料 · 请明确新增配对' : '已恢复 ${profiles.length} 个本机资料 · 连接前需重新审查';
    } catch (_) { if (ticket == generation) { profiles = const []; ready = false; status = '资料损坏、存储锁定或不可用 · 已停止，不覆盖原记录或自动创建密钥'; } }
    if (ticket == generation) _notify();
  }
  Future<void> _mutate(List<HostProfile> Function(List<HostProfile>) action,{Map<String,dynamic>? pending,bool replacePending=false}) {
    final captured = generation;
    final operation = _tail.then((_) async {
      if (_disposed || !ready || generation != captured) throw const RemoteFailure('catalog_unavailable');
      writing = true; _notify();
      try {
        final next = action(List.of(profiles));
        if (next.length > maxHostProfiles) throw const RemoteFailure('catalog_limit');
        final nextPending = replacePending ? pending : pendingCreation;
        final text = jsonEncode({'schemaVersion':2,'profiles':next.map((p) => p.toJson()).toList(),'pendingCreation':nextPending});
        if (utf8.encode(text).length > maxCatalogBytes) throw const RemoteFailure('catalog_limit');
        final updated = await storage.save(revision,text);
        if (generation != captured) throw const RemoteFailure('catalog_stale');
        profiles = List.unmodifiable(next); pendingCreation = nextPending; revision = updated; status = '本机资料已保存 · 不代表主机授权或当前在线';
      } catch (_) { ready = false; generation++; status = '保存结果未知或版本冲突 · 已锁定写入，请重新读取核验，不重放保存'; rethrow; }
      finally { writing = false; _notify(); }
    });
    _tail = operation.catchError((Object _) {}); return operation;
  }
  Future<void> beginCreation(Map<String,dynamic> target,String label) {
    if (pendingCreation != null || profiles.length >= maxHostProfiles) throw const RemoteFailure('catalog_creation_pending');
    final random = Random.secure();
    final pending = validatePendingCreation({'id':List.generate(16,(_) => random.nextInt(256).toRadixString(16).padLeft(2,'0')).join(),
      'label':label,'target':{for (final k in HostProfile.targetFields) k:target[k]},'handle':''});
    return _mutate((list) { if (pendingCreation != null) throw const RemoteFailure('catalog_creation_pending'); return list; },pending:pending,replacePending:true);
  }
  Future<void> recordCreatedHandle(String handle) {
    if (pendingCreation == null) throw const RemoteFailure('catalog_creation_pending');
    final pending = validatePendingCreation({...pendingCreation!,'handle':handle});
    return _mutate((list) => list,pending:pending,replacePending:true);
  }
  Future<void> completeCreation(HostProfile profile) {
    if (pendingCreation == null || pendingCreation!['handle'] != profile.pairingRecord['handle'] ||
        jsonEncode(pendingCreation!['target']) != jsonEncode(profile.target)) throw const RemoteFailure('catalog_binding_changed');
    return _mutate((list) {
      if (list.any((p) => p.id == profile.id || p.pairingRecord['handle'] == profile.pairingRecord['handle'])) throw const RemoteFailure('catalog_duplicate');
      return [...list,profile];
    },pending:null,replacePending:true);
  }
  Future<void> clearUnstartedCreation(String id) {
    if (pendingCreation?['id'] != id || pendingCreation?['handle'] != '') throw const RemoteFailure('catalog_creation_pending');
    return _mutate((list) => list,pending:null,replacePending:true);
  }
  Future<void> clearDeletedCreation(String handle) {
    if (handle.isEmpty || pendingCreation?['handle'] != handle) throw const RemoteFailure('catalog_creation_pending');
    return _mutate((list) => list,pending:null,replacePending:true);
  }
  Future<void> add(HostProfile profile) => _mutate((list) {
    if (list.any((p) => p.id == profile.id || p.restore(clock()).handle == profile.restore(clock()).handle)) throw const RemoteFailure('catalog_duplicate');
    return [...list,profile];
  });
  Future<void> update(HostProfile profile) => _mutate((list) {
    final i = list.indexWhere((p) => p.id == profile.id); if (i < 0) throw const RemoteFailure('catalog_missing');
    if (profile.expectedPrevious == null || profile.expectedPrevious != jsonEncode(list[i].toJson())) throw const RemoteFailure('catalog_profile_stale');
    if (jsonEncode(list[i].target) != jsonEncode(profile.target) || list[i].pairingRecord['handle'] != profile.pairingRecord['handle']) throw const RemoteFailure('catalog_binding_changed');
    list[i] = profile; return list;
  });
  Future<void> remove(String id) => _mutate((list) { if (!list.any((p) => p.id == id)) throw const RemoteFailure('catalog_missing'); return list.where((p) => p.id != id).toList(); });
}
