import 'dart:convert';
import 'dart:math';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'pairing.dart';
import 'remote_adapter.dart';
import 'network_profiles.dart';
import 'config_transfer.dart' show PortableHost,PortableConfig,transferTargetFields,validateTerminalFontSize;

// Retaining old paired identities during a 16-host replacement needs room for
// both sets. The portable archive itself remains capped at 16 hosts.
const maxHostProfiles = 32;
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
  HostProfile._(this.id,this.label,this.enabled,this.target,this.pairingRecord,this.provider,this.retired,this.networkProfileId,this.requiresNetworkBinding,[this.expectedPrevious]);
  final String id,label,provider;
  final String? expectedPrevious,networkProfileId;
  final bool enabled,retired,requiresNetworkBinding;
  bool get hasIdentity => pairingRecord.isNotEmpty;
  final Map<String,dynamic> target, pairingRecord;
  static const targetFields = {'host','port','username','expectedHostKey','socketPath','herdrPath','session','paneId'};
  factory HostProfile.fromJson(Map<String,dynamic> data,int now) {
    const fields = {'id','label','enabled','target','pairing','provider','retired','networkProfileId','requiresNetworkBinding'};
    // Missing retired is accepted only as a legacy record normalization.
    data = {...data,if (!data.containsKey('retired')) 'retired':false,if (!data.containsKey('networkProfileId')) 'networkProfileId':null,if (!data.containsKey('requiresNetworkBinding')) 'requiresNetworkBinding':false};
    if (data.length != fields.length || !data.keys.every(fields.contains) || data['id'] is! String ||
        !RegExp(r'^[a-f0-9]{32}$').hasMatch(data['id'] as String) || data['label'] is! String ||
        (data['label'] as String).trim().isEmpty || ((data['label'] as String).length > 64 && utf8.encode(data['label'] as String).length > 96) ||
        RegExp(r'[\x00-\x1f\x7f]').hasMatch(data['label'] as String) || data['enabled'] is! bool ||
        (data['networkProfileId'] != null && (data['networkProfileId'] is! String || !RegExp(r'^[a-f0-9]{32}$').hasMatch(data['networkProfileId'] as String))) ||
        data['requiresNetworkBinding'] is! bool || (data['requiresNetworkBinding'] == true && (data['networkProfileId'] != null || !['tailscale','easytier','zerotier'].contains(data['provider']))) ||
        !hostProviders.contains(data['provider']) || data['retired'] is! bool || (data['retired'] == true && data['enabled'] == true) ||
        data['target'] is! Map<String,dynamic> || (data['pairing'] != null && data['pairing'] is! Map<String,dynamic>)) throw const RemoteFailure('invalid_catalog');
    final target = Map<String,dynamic>.from(data['target'] as Map);
    if (target.length != targetFields.length || !target.keys.every(targetFields.contains)) throw const RemoteFailure('invalid_catalog');
    final checked = RemoteConfig.fromJson({...target,'schemaVersion':1,'reviewConfirmed':true,'privateKeyPem':'catalog-validation-only'});
    checked.configRoot;
    final p = data['pairing'] == null ? null : restoreDevicePairing(Map<String,dynamic>.from(data['pairing'] as Map),now);
    if (p != null && (p.request['account'] != checked.username || p.request['host_key'] != checked.expectedFingerprint)) throw const RemoteFailure('invalid_catalog');
    return HostProfile._(data['id'] as String,data['label'] as String,data['enabled'] as bool,
      Map<String,dynamic>.unmodifiable({for (final key in targetFields) key:target[key]}),Map<String,dynamic>.unmodifiable(p?.toPublicRecord() ?? {}),data['provider'] as String,data['retired'] as bool,data['networkProfileId'] as String?,data['requiresNetworkBinding'] as bool);
  }
  factory HostProfile.create(String label,Map<String,dynamic> target,PendingDevicePairing pairing,int now,{String provider='unspecified',String? networkProfileId,bool requiresNetworkBinding=false}) {
    final random = Random.secure();
    return HostProfile.fromJson({'id':List.generate(16,(_) => random.nextInt(256).toRadixString(16).padLeft(2,'0')).join(),
      'label':label,'enabled':true,'provider':provider,'networkProfileId':networkProfileId,'requiresNetworkBinding':requiresNetworkBinding,'target':{for (final k in targetFields) k:target[k]},'pairing':pairing.toPublicRecord()},now);
  }
  factory HostProfile.imported(PortableHost host,int now,{String? networkProfileId}) {
    if (host.networkKey != null && networkProfileId == null) throw const RemoteFailure('catalog_binding_changed');
    final random = Random.secure();
    return HostProfile.fromJson({'id':List.generate(16,(_) => random.nextInt(256).toRadixString(16).padLeft(2,'0')).join(),
      'label':host.label,'enabled':true,'retired':false,'provider':host.provider,'networkProfileId':networkProfileId,'requiresNetworkBinding':host.requiresNetworkBinding,'target':{...host.target,'paneId':''},'pairing':null},now);
  }
  Map<String,dynamic> toJson() => {'id':id,'label':label,'enabled':enabled,'retired':retired,'provider':provider,'networkProfileId':networkProfileId,if (requiresNetworkBinding) 'requiresNetworkBinding':true,'target':target,'pairing':hasIdentity ? pairingRecord : null};
  PendingDevicePairing restore(int now) => restoreDevicePairing(Map<String,dynamic>.from(pairingRecord),now);
  HostProfile change({String? label,String? provider,bool? enabled,bool? retired,PendingDevicePairing? pairing,String? networkProfileId,bool replaceNetwork=false,required int now}) {
    if (requiresNetworkBinding && provider != null && provider != this.provider) throw const RemoteFailure('network_binding_required');
    if (requiresNetworkBinding && replaceNetwork && networkProfileId == null) throw const RemoteFailure('network_binding_required');
    if (this.retired && retired == false) throw const RemoteFailure('catalog_retired');
    final checked = HostProfile.fromJson({...toJson(),if (label != null) 'label':label,if (enabled != null) 'enabled':enabled,if (provider != null) 'provider':provider,
      if (pairing != null) 'pairing':pairing.toPublicRecord(),if (replaceNetwork) 'networkProfileId':networkProfileId,
      if (requiresNetworkBinding && replaceNetwork) 'requiresNetworkBinding':false},now);
    final finalRetired = retired ?? this.retired;
    if (finalRetired && checked.enabled) throw const RemoteFailure('catalog_retired');
    return HostProfile._(checked.id,checked.label,checked.enabled,checked.target,checked.pairingRecord,checked.provider,finalRetired,checked.networkProfileId,checked.requiresNetworkBinding,jsonEncode(toJson()));
  }
}

bool sameHostTarget(Map<String,dynamic> a,Map<String,dynamic> b) =>
  a.length == HostProfile.targetFields.length && b.length == HostProfile.targetFields.length &&
  HostProfile.targetFields.every((key) => a.containsKey(key) && b.containsKey(key) && a[key] == b[key]);

/// Connection status is per view; authorization and identity are shared.
Map<String,dynamic> hostPairingBinding(HostProfile host) => {
  for (final key in ['handle','request','authorization','consumed']) key:host.pairingRecord[key],
};
bool samePairingBinding(HostProfile a,HostProfile b) => _sameRecord(hostPairingBinding(a),hostPairingBinding(b));

bool _samePortableTarget(Map<String,dynamic> a,Map<String,dynamic> b) =>
  transferTargetFields.every((key) => a.containsKey(key) && b.containsKey(key) && a[key] == b[key]);

bool _sameRecord(dynamic a,dynamic b) {
  if (a is Map && b is Map) return a.length == b.length && a.keys.every((key) => b.containsKey(key) && _sameRecord(a[key],b[key]));
  if (a is List && b is List) return a.length == b.length && List.generate(a.length,(i) => i).every((i) => _sameRecord(a[i],b[i]));
  return a == b;
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

class ConfigImportPlan {
  ConfigImportPlan(this.revision,List<PortableHost> hosts,List<List<HostProfile>> conflicts,{this.config,List<List<NetworkProfile>> networkConflicts=const []})
    : hosts = List.unmodifiable(hosts), conflicts = List.unmodifiable(conflicts.map((items) => List<HostProfile>.unmodifiable(items))),
      networkConflicts = List.unmodifiable(networkConflicts.map((items) => List<NetworkProfile>.unmodifiable(items)));
  final String revision;
  final PortableConfig? config;
  final List<List<NetworkProfile>> networkConflicts;
  final List<PortableHost> hosts;
  final List<List<HostProfile>> conflicts;
}
enum ConfigImportAction { add,keep,replace }
class ConfigImportChoice {
  const ConfigImportChoice(this.action);
  final ConfigImportAction action;
}

Map<String,dynamic>? validatePendingCreation(dynamic data) {
  if (data == null) return null;
  if (data is! Map<String,dynamic> || ![4,5].contains(data.length) || !data.keys.every({'id','label','target','handle','sourceProfileId'}.contains) ||
      data['id'] is! String || !RegExp(r'^[a-f0-9]{32}$').hasMatch(data['id'] as String) || data['label'] is! String ||
      (data['label'] as String).trim().isEmpty || ((data['label'] as String).length > 64 && utf8.encode(data['label'] as String).length > 96) || RegExp(r'[\x00-\x1f\x7f]').hasMatch(data['label'] as String) ||
      data['handle'] is! String || !RegExp(r'^[A-Za-z0-9_-]{0,128}$').hasMatch(data['handle'] as String) ||
      data['target'] is! Map<String,dynamic> || (data.containsKey('sourceProfileId') &&
        (data['sourceProfileId'] is! String || !RegExp(r'^[a-f0-9]{32}$').hasMatch(data['sourceProfileId'] as String)))) throw const RemoteFailure('invalid_catalog');
  final target = Map<String,dynamic>.from(data['target'] as Map);
  if (target.length != HostProfile.targetFields.length || !target.keys.every(HostProfile.targetFields.contains)) throw const RemoteFailure('invalid_catalog');
  final checked = RemoteConfig.fromJson({...target,'schemaVersion':1,'reviewConfirmed':true,'privateKeyPem':'catalog-validation-only'});
  checked.configRoot;
  // The target is stored in a dynamic-valued record. Keep its runtime type
  // explicit so revalidating this immutable result uses the same strict schema.
  return Map<String,dynamic>.unmodifiable({...data,'target':Map<String,dynamic>.unmodifiable({for (final key in HostProfile.targetFields) key:target[key]})});
}

class HostCatalog extends ChangeNotifier {
  HostCatalog({HostCatalogStorage? storage,int Function()? clock}) : storage = storage ?? NativeHostCatalogStorage(),
    clock = clock ?? (() => DateTime.now().millisecondsSinceEpoch ~/ 1000);
  final HostCatalogStorage storage;
  final int Function() clock;
  List<HostProfile> profiles = const [];
  List<NetworkProfile> networkProfiles = const [];
  Map<String,dynamic>? pendingCreation;
  int terminalFontSize = 14;
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
      final loaded = <HostProfile>[],networks = <NetworkProfile>[];
      var loadedFontSize = 14;
      if (raw.contents.isNotEmpty) {
        final data = decodeCatalogJson(raw.contents);
        if (data is! Map<String,dynamic> || !data.keys.toSet().containsAll({'schemaVersion','profiles','pendingCreation'}) || ![3,4,5].contains(data.length) || !data.keys.every({'schemaVersion','profiles','pendingCreation','networkProfiles','preferences'}.contains) || ![1,2,3,4].contains(data['schemaVersion']) || data['profiles'] is! List) throw const RemoteFailure('invalid_catalog');
        if (data['schemaVersion'] == 4) {
          if (![4,5].contains(data.length) || data['networkProfiles'] is! List || (data['networkProfiles'] as List).length > maxNetworkProfiles) throw const RemoteFailure('invalid_catalog');
          for (final item in data['networkProfiles'] as List) {
            if (item is! Map<String,dynamic>) throw const RemoteFailure('invalid_catalog');
            final network = NetworkProfile.fromJson(item);
            if (networks.any((old) => old.id == network.id)) throw const RemoteFailure('invalid_catalog');
            networks.add(network);
          }
        } else if (data.length != 3 || !data.keys.every({'schemaVersion','profiles','pendingCreation'}.contains)) { throw const RemoteFailure('invalid_catalog'); }
        if (data['schemaVersion'] == 4 && data.containsKey('preferences')) {
          final prefs = data['preferences'];
          if (prefs is! Map<String,dynamic> || prefs.length != 1 || !prefs.containsKey('terminalFontSize')) throw const RemoteFailure('invalid_catalog');
          loadedFontSize = validateTerminalFontSize(prefs['terminalFontSize']);
        }
        pendingCreation = validatePendingCreation(data['pendingCreation']);
        for (final item in data['profiles'] as List) {
          if (item is! Map<String,dynamic>) throw const RemoteFailure('invalid_catalog');
          if ([3,4].contains(data['schemaVersion']) && !item.containsKey('retired')) throw const RemoteFailure('invalid_catalog');
          if (![3,4].contains(data['schemaVersion']) && item['pairing'] == null) throw const RemoteFailure('invalid_catalog');
          final normalized = data['schemaVersion'] == 1 ? {...item,'provider':item['provider'] ?? 'unspecified'} : item;
          if (data['schemaVersion'] == 4 && !item.containsKey('networkProfileId')) throw const RemoteFailure('invalid_catalog');
          if (data['schemaVersion'] != 4 && item['networkProfileId'] != null) throw const RemoteFailure('invalid_catalog');
          final p = HostProfile.fromJson(normalized,clock());
          if (p.networkProfileId != null && !networks.any((n) => n.id == p.networkProfileId)) throw const RemoteFailure('invalid_catalog');
          if (loaded.any((old) => old.id == p.id || (old.hasIdentity && p.hasIdentity && old.pairingRecord['handle'] == p.pairingRecord['handle']))) throw const RemoteFailure('invalid_catalog');
          loaded.add(p);
        }
      }
      if (raw.contents.isEmpty) pendingCreation = null;
      profiles = List.unmodifiable(loaded); networkProfiles = List.unmodifiable(networks); terminalFontSize = loadedFontSize; revision = raw.revision; ready = true;
      status = profiles.isEmpty ? '没有本机主机资料 · 请明确新增配对' : '已恢复 ${profiles.length} 个本机资料 · 连接前需重新审查';
    } catch (_) { if (ticket == generation) { profiles = const []; networkProfiles = const []; ready = false; status = '资料损坏、存储锁定或不可用 · 已停止，不覆盖原记录或自动创建密钥'; } }
    if (ticket == generation) _notify();
  }
  Future<void> _mutate(List<HostProfile> Function(List<HostProfile>) action,{Map<String,dynamic>? pending,bool replacePending=false,VoidCallback? beforeSave,Future<void> Function()? beforeSaveCheck,List<NetworkProfile> Function(List<NetworkProfile>)? networkAction,int? fontSize}) {
    final captured = generation;
    final operation = _tail.then((_) async {
      if (_disposed || !ready || generation != captured) throw const RemoteFailure('catalog_unavailable');
      writing = true; _notify();
      var saveStarted = false;
      try {
        final next = action(List.of(profiles));
        final nextNetworks = networkAction?.call(List.of(networkProfiles)) ?? networkProfiles;
        final nextFontSize = fontSize == null ? terminalFontSize : validateTerminalFontSize(fontSize);
        if (nextNetworks.length > maxNetworkProfiles || next.any((p) => p.networkProfileId != null && !nextNetworks.any((n) => n.id == p.networkProfileId))) throw const RemoteFailure('invalid_catalog');
        if (next.length > maxHostProfiles) throw const RemoteFailure('catalog_limit');
        final nextPending = replacePending ? pending : pendingCreation;
        final text = jsonEncode({'schemaVersion':4,'profiles':next.map((p) => p.toJson()).toList(),'pendingCreation':nextPending,'networkProfiles':nextNetworks.map((p) => p.toJson()).toList(),'preferences':{'terminalFontSize':nextFontSize}});
        if (utf8.encode(text).length > maxCatalogBytes) throw const RemoteFailure('catalog_limit');
        if (_disposed || generation != captured || !ready) throw const RemoteFailure('catalog_stale');
        // This hook is a read-only precondition, never another queued mutation.
        if (beforeSaveCheck != null) await beforeSaveCheck();
        if (_disposed || generation != captured || !ready) throw const RemoteFailure('catalog_stale');
        beforeSave?.call();
        saveStarted = true;
        final updated = await storage.save(revision,text);
        if (generation != captured) throw const RemoteFailure('catalog_stale');
        profiles = List.unmodifiable(next); networkProfiles = List.unmodifiable(nextNetworks); terminalFontSize = nextFontSize; pendingCreation = nextPending; revision = updated; status = '本机资料已保存 · 不代表主机授权或当前在线';
      } catch (_) {
        if (saveStarted) {
          ready = false; generation++; status = '保存结果未知或版本冲突 · 已锁定写入，请重新读取核验，不重放保存';
        } else { status = '操作前检查未通过 · 尚未写入，请修正或重新审查'; }
        rethrow;
      }
      finally { writing = false; _notify(); }
    });
    _tail = operation.catchError((Object _) {}); return operation;
  }
  /// Serialize one explicit native identity operation with public catalog writes.
  /// Callbacks must not enqueue another catalog operation on this same queue.
  Future<T> guardedNetworkOperation<T>(NetworkProfile profile,{required String expectedRevision,
      required Future<T> Function() operation,VoidCallback? beforeDispatch}) {
    final captured = generation;
    final pending = _tail.then((_) async {
      if (_disposed || !ready || generation != captured || revision != expectedRevision) {
        throw const RemoteFailure('network_profile_stale');
      }
      final matches = networkProfiles.where((p) => p.id == profile.id).toList();
      if (matches.length != 1 || jsonEncode(matches.single.toJson()) != jsonEncode(profile.toJson())) {
        throw const RemoteFailure('network_profile_stale');
      }
      writing = true; _notify();
      try {
        if (_disposed || !ready || generation != captured || revision != expectedRevision) {
          throw const RemoteFailure('network_profile_stale');
        }
        beforeDispatch?.call();
        return await operation();
      } finally { writing = false; _notify(); }
    });
    // An unknown native result releases serialization without retrying it or
    // changing the catalog. The identity session may only read status next.
    _tail = pending.then<void>((_) {},onError:(Object _,StackTrace __) {});
    return pending;
  }
  Future<void> beginCreation(Map<String,dynamic> target,String label,{String? sourceProfileId}) {
    if (pendingCreation != null || (profiles.length >= maxHostProfiles && sourceProfileId == null)) throw const RemoteFailure('catalog_creation_pending');
    final random = Random.secure();
    final pending = validatePendingCreation({'id':List.generate(16,(_) => random.nextInt(256).toRadixString(16).padLeft(2,'0')).join(),
      'label':label,'target':{for (final k in HostProfile.targetFields) k:target[k]},'handle':'',if (sourceProfileId != null) 'sourceProfileId':sourceProfileId});
    return _mutate((list) {
      if (pendingCreation != null) throw const RemoteFailure('catalog_creation_pending');
      if (sourceProfileId != null) {
        final source = list.where((p) => p.id == sourceProfileId && p.enabled && !p.retired && !p.hasIdentity).toList();
        if (source.length != 1 || !sameHostTarget(source.single.target,pending!['target'] as Map<String,dynamic>)) throw const RemoteFailure('catalog_binding_changed');
      }
      return list;
    },pending:pending,replacePending:true);
  }
  Future<void> recordCreatedHandle(String handle) {
    if (pendingCreation == null) throw const RemoteFailure('catalog_creation_pending');
    final pending = validatePendingCreation({...pendingCreation!,'handle':handle});
    return _mutate((list) => list,pending:pending,replacePending:true);
  }
  Future<void> completeCreation(HostProfile profile) {
    if (pendingCreation == null || pendingCreation!['handle'] != profile.pairingRecord['handle'] ||
        !sameHostTarget(pendingCreation!['target'] as Map<String,dynamic>,profile.target)) throw const RemoteFailure('catalog_binding_changed');
    return _mutate((list) {
      final sourceId = pendingCreation?['sourceProfileId'];
      if (sourceId != null) {
        final source = list.where((p) => p.id == sourceId && !p.hasIdentity && !p.retired && p.enabled).toList();
        if (source.length != 1 || !sameHostTarget(source.single.target,profile.target) || source.single.networkProfileId != profile.networkProfileId || source.single.requiresNetworkBinding != profile.requiresNetworkBinding || (profile.requiresNetworkBinding && source.single.provider != profile.provider)) throw const RemoteFailure('catalog_binding_changed');
        list.removeWhere((p) => p.id == sourceId);
      }
      if (list.any((p) => p.id == profile.id || (p.hasIdentity && p.pairingRecord['handle'] == profile.pairingRecord['handle']))) throw const RemoteFailure('catalog_duplicate');
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
    if (list.any((p) => p.id == profile.id || (p.hasIdentity && profile.hasIdentity && p.pairingRecord['handle'] == profile.pairingRecord['handle']))) throw const RemoteFailure('catalog_duplicate');
    return [...list,profile];
  });
  Future<void> update(HostProfile profile,{VoidCallback? beforeCommit,String? expectedRevision}) => _mutate((list) {
    if (expectedRevision != null && revision != expectedRevision) throw const RemoteFailure('catalog_profile_stale');
    final i = list.indexWhere((p) => p.id == profile.id); if (i < 0) throw const RemoteFailure('catalog_missing');
    if (profile.expectedPrevious == null || profile.expectedPrevious != jsonEncode(list[i].toJson())) throw const RemoteFailure('catalog_profile_stale');
    if (!sameHostTarget(list[i].target,profile.target) || list[i].pairingRecord['handle'] != profile.pairingRecord['handle']) throw const RemoteFailure('catalog_binding_changed');
    if (list[i].requiresNetworkBinding && !profile.requiresNetworkBinding) {
      final selected = networkProfiles.where((n) => n.id == profile.networkProfileId && n.enabled && n.provider == list[i].provider).toList();
      if (selected.length != 1) throw const RemoteFailure('network_binding_required');
    }
    if (list[i].retired && (!profile.retired || profile.enabled)) throw const RemoteFailure('catalog_retired');
    list[i] = profile; return list;
  },beforeSave:beforeCommit);
  Future<void> remove(String id) => _mutate((list) { if (!list.any((p) => p.id == id)) throw const RemoteFailure('catalog_missing'); return list.where((p) => p.id != id).toList(); });

  List<HostProfile> networkImpact(String id) => List.unmodifiable(profiles.where((p) => p.networkProfileId == id));
  NetworkProfile? networkFor(HostProfile host) {
    if (host.networkProfileId == null) return null;
    final found = networkProfiles.where((p) => p.id == host.networkProfileId).toList();
    if (found.length != 1) throw const RemoteFailure('network_binding_changed');
    return found.single;
  }
  NetworkConnectionBinding freezeNetwork(HostProfile host) {
    if (host.requiresNetworkBinding) throw const RemoteFailure('network_binding_required');
    final network = networkFor(host);
    final binding = jsonEncode({'networkProfileId':host.networkProfileId,'network':network?.toJson()});
    return NetworkConnectionBinding(network,() {
      if (!ready || _disposed) return false;
      final current = profiles.where((p) => p.id == host.id && p.enabled && !p.retired).toList();
      if (current.length != 1 || current.single.requiresNetworkBinding || !sameHostTarget(current.single.target,host.target) ||
          !samePairingBinding(current.single,host)) return false;
      try {
        final n = networkFor(current.single);
        return (n == null || n.enabled) && jsonEncode({'networkProfileId':current.single.networkProfileId,'network':n?.toJson()}) == binding;
      } catch (_) { return false; }
    },changes:this,fontSize:() => terminalFontSize);
  }
  Future<void> addNetwork(NetworkProfile profile) => _mutate((list) => list,networkAction:(list) {
    if (profile.revision != 1 || list.any((p) => p.id == profile.id)) throw const RemoteFailure('network_profile_stale');
    return [...list,profile];
  });
  Future<void> updateNetwork(NetworkProfile profile,{VoidCallback? beforeCommit,String? expectedRevision,Future<void> Function()? beforeChange}) => _mutate((list) => list,networkAction:(list) {
    if (expectedRevision != null && revision != expectedRevision) throw const RemoteFailure('network_profile_stale');
    final index = list.indexWhere((p) => p.id == profile.id);
    if (index < 0 || profile.expectedPrevious != jsonEncode(list[index].toJson()) || profile.revision != list[index].revision+1) throw const RemoteFailure('network_profile_stale');
    list[index] = profile; return list;
  },beforeSave:beforeCommit,beforeSaveCheck:beforeChange);
  Future<void> removeNetwork(NetworkProfile profile,{VoidCallback? beforeCommit,String? expectedRevision,
      Future<void> Function()? beforeRemove}) => _mutate((list) {
    if (expectedRevision != null && revision != expectedRevision) throw const RemoteFailure('network_profile_stale');
    if (list.any((p) => p.networkProfileId == profile.id)) throw const RemoteFailure('network_in_use');
    return list;
  },networkAction:(list) {
    final matches = list.where((p) => p.id == profile.id).toList();
    if (matches.length != 1 || jsonEncode(matches.single.toJson()) != jsonEncode(profile.toJson())) throw const RemoteFailure('network_profile_stale');
    return list.where((p) => p.id != profile.id).toList();
  },beforeSave:beforeCommit,beforeSaveCheck:beforeRemove);

  Future<void> updateTerminalFontSize(int fontSize,{String? expectedRevision}) => _mutate((list) {
    if (expectedRevision != null && expectedRevision != revision) throw const RemoteFailure('catalog_profile_stale');
    return list;
  },fontSize:validateTerminalFontSize(fontSize));
  PortableConfig exportConfig(Set<String> hostIds,Set<String> networkIds,{bool includePreferences=false}) {
    if (!ready || writing || pendingCreation != null || hostIds.length > 16) throw const RemoteFailure('catalog_transfer_unavailable');
    final hosts = profiles.where((p) => hostIds.contains(p.id) && !p.retired).toList();
    if (hosts.length != hostIds.length) throw const RemoteFailure('catalog_transfer_stale');
    final allNetworks = {...networkIds,for (final host in hosts) if (host.networkProfileId != null) host.networkProfileId!};
    final networks = networkProfiles.where((n) => allNetworks.contains(n.id)).toList();
    if (networks.length != allNetworks.length || networks.length > 16) throw const RemoteFailure('catalog_transfer_unavailable');
    final keys = <String,String>{for (var i = 0; i < networks.length; i++) networks[i].id:'network_$i'};
    return PortableConfig.fromJson({'version':2,'hosts':[for (final host in hosts) {
      'label':host.label,'provider':host.provider,'target':{for (final key in transferTargetFields) key:host.target[key]},
      if (host.networkProfileId != null) 'provider':networks.singleWhere((n) => n.id == host.networkProfileId).provider,
      'networkKey':keys[host.networkProfileId],if (host.requiresNetworkBinding) 'requiresNetworkBinding':true,
    }],'networks':[for (final network in networks) {'key':keys[network.id],'label':network.label,'provider':network.provider,'settings':network.settings}],
      'preferences':includePreferences ? {'terminalFontSize':terminalFontSize} : null});
  }
  ConfigImportPlan previewConfigImport(PortableConfig config) {
    if (!ready || writing || pendingCreation != null) throw const RemoteFailure('catalog_transfer_unavailable');
    return ConfigImportPlan(revision,config.hosts,[for (final host in config.hosts) profiles.where((p) => !p.retired &&
      (p.label == host.label || _samePortableTarget(p.target,host.target))).toList()],config:config,
      networkConflicts:[for (final network in config.networks) networkProfiles.where((n) => n.label == network.label).toList()]);
  }
  ({List<HostProfile> hosts,List<NetworkProfile> networks,int fontSize}) _prepareConfigImport(ConfigImportPlan plan,List<ConfigImportChoice> choices,
      Set<String> selectedNetworks,bool applyPreferences) {
    final config = plan.config;
    if (config == null || !ready || pendingCreation != null || plan.revision != revision || choices.length != plan.hosts.length ||
        selectedNetworks.any((key) => !config.networks.any((n) => n.key == key)) || (applyPreferences && config.terminalFontSize == null)) {
      throw const RemoteFailure('catalog_transfer_stale');
    }
    final needed = {...selectedNetworks,for (var i = 0; i < choices.length; i++)
      if (choices[i].action != ConfigImportAction.keep && plan.hosts[i].networkKey != null) plan.hosts[i].networkKey!};
    final networks = List<NetworkProfile>.of(networkProfiles),ids = <String,String>{};
    for (final source in config.networks.where((n) => needed.contains(n.key))) {
      final created = NetworkProfile.create(source.label,source.provider,source.settings);
      if (networks.any((n) => n.id == created.id)) throw const RemoteFailure('catalog_duplicate');
      final network = NetworkProfile.fromJson({...created.toJson(),'enabled':false});
      ids[source.key] = network.id; networks.add(network);
    }
    if (networks.length > maxNetworkProfiles) throw const RemoteFailure('catalog_limit');
    final hosts = _prepareImport(plan,choices,networkIds:ids);
    final fontSize = applyPreferences ? config.terminalFontSize! : terminalFontSize;
    final text = jsonEncode({'schemaVersion':4,'profiles':hosts.map((p) => p.toJson()).toList(),'pendingCreation':pendingCreation,
      'networkProfiles':networks.map((n) => n.toJson()).toList(),'preferences':{'terminalFontSize':fontSize}});
    if (utf8.encode(text).length > maxCatalogBytes) throw const RemoteFailure('catalog_limit');
    return (hosts:hosts,networks:networks,fontSize:fontSize);
  }
  Future<void> applyConfigImport(ConfigImportPlan plan,List<ConfigImportChoice> choices,{Set<String> selectedNetworks=const {},bool applyPreferences=false,
      void Function(Set<String>)? beforeCommit}) {
    if (writing) throw const RemoteFailure('catalog_busy');
    choices = List<ConfigImportChoice>.unmodifiable(choices);
    selectedNetworks = Set<String>.unmodifiable(selectedNetworks);
    _prepareConfigImport(plan,choices,selectedNetworks,applyPreferences);
    late ({List<HostProfile> hosts,List<NetworkProfile> networks,int fontSize}) prepared;
    return _mutate((_) {
      prepared = _prepareConfigImport(plan,choices,selectedNetworks,applyPreferences);
      return prepared.hosts;
    },networkAction:(_) => prepared.networks,fontSize:applyPreferences ? plan.config!.terminalFontSize : null,
      beforeSave:() => beforeCommit?.call({for (var i = 0; i < choices.length; i++)
        if (choices[i].action == ConfigImportAction.replace) ...plan.conflicts[i].map((p) => p.id)}));
  }

  List<PortableHost> exportProfiles(Set<String> ids) {
    if (!ready || writing || pendingCreation != null || ids.isEmpty || ids.length > 16) throw const RemoteFailure('catalog_transfer_unavailable');
    if (profiles.any((p) => ids.contains(p.id) && p.networkProfileId != null)) throw const RemoteFailure('transfer_network_unavailable');
    final selected = profiles.where((p) => ids.contains(p.id) && !p.retired).toList();
    if (selected.length != ids.length) throw const RemoteFailure('catalog_profile_stale');
    return List.unmodifiable(selected.map(PortableHost.fromProfile));
  }
  ConfigImportPlan previewImport(List<PortableHost> hosts) {
    if (!ready || writing || pendingCreation != null || hosts.isEmpty || hosts.length > 16) throw const RemoteFailure('catalog_transfer_unavailable');
    return ConfigImportPlan(revision,hosts,[for (final host in hosts) profiles.where((p) => !p.retired &&
      (p.label == host.label || _samePortableTarget(p.target,host.target))).toList()]);
  }
  List<HostProfile> _prepareImport(ConfigImportPlan plan,List<ConfigImportChoice> choices,{Map<String,String> networkIds=const {}}) {
    if (_disposed || !ready || pendingCreation != null || revision != plan.revision || choices.length != plan.hosts.length ||
        (plan.hosts.isEmpty && plan.config == null) || plan.hosts.length > 16 || plan.conflicts.length != plan.hosts.length) {
      throw const RemoteFailure('catalog_transfer_stale');
    }
      final list = List<HostProfile>.of(profiles), replaced = <String>{};
      for (var index = 0; index < choices.length; index++) {
        final action = choices[index].action, host = plan.hosts[index];
        final actual = profiles.where((p) => !p.retired && (p.label == host.label ||
          _samePortableTarget(p.target,host.target))).toList();
        if (!_sameRecord(actual.map((p) => p.toJson()).toList(),plan.conflicts[index].map((p) => p.toJson()).toList())) {
          throw const RemoteFailure('catalog_transfer_stale');
        }
        if (action == ConfigImportAction.keep) continue;
        if (action == ConfigImportAction.replace) {
          if (actual.isEmpty) throw const RemoteFailure('catalog_transfer_choice');
          for (final old in actual) {
            if (!replaced.add(old.id)) throw const RemoteFailure('catalog_transfer_duplicate_replacement');
            final position = list.indexWhere((p) => p.id == old.id && !p.retired);
            if (position < 0) throw const RemoteFailure('catalog_transfer_stale');
            if (old.hasIdentity) { list[position] = old.change(enabled:false,retired:true,now:clock()); }
            else { list.removeAt(position); }
          }
        }
        if (list.any((p) => !p.retired && _samePortableTarget(p.target,host.target))) {
          throw const RemoteFailure('catalog_transfer_target_conflict');
        }
        if (host.networkKey != null && !networkIds.containsKey(host.networkKey)) throw const RemoteFailure('catalog_transfer_stale');
        final imported = HostProfile.imported(host,clock(),networkProfileId:networkIds[host.networkKey]);
        if (list.any((p) => p.id == imported.id)) throw const RemoteFailure('catalog_duplicate');
        list.add(imported);
      }
      if (list.length > maxHostProfiles || utf8.encode(jsonEncode({'schemaVersion':4,
          'profiles':list.map((p) => p.toJson()).toList(),'pendingCreation':null,'networkProfiles':networkProfiles.map((p) => p.toJson()).toList(),'preferences':{'terminalFontSize':terminalFontSize}})).length > maxCatalogBytes) {
        throw const RemoteFailure('catalog_limit');
      }
      return list;
  }
  Future<void> applyImport(ConfigImportPlan plan,List<ConfigImportChoice> choices,{void Function(Set<String>)? beforeCommit}) {
    if (writing) throw const RemoteFailure('catalog_busy');
    _prepareImport(plan,choices); // Pure whole-plan preflight before any view is revoked.
    var affected = <String>{};
    return _mutate((_) {
      // Recheck after queued work settles, before closing tabs or invoking CAS.
      final next = _prepareImport(plan,choices);
      affected = {for (var i = 0; i < choices.length; i++)
        if (choices[i].action == ConfigImportAction.replace) ...plan.conflicts[i].map((p) => p.id)};
      return next;
    },beforeSave:() { beforeCommit?.call(Set<String>.unmodifiable(affected)); });
  }
}
