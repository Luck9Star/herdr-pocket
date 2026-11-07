import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'host_catalog.dart';
import 'network_profiles.dart';
import 'remote_adapter.dart';

final _uuid = RegExp(r'^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$');
Never _invalid() => throw const RemoteFailure('zerotier_device_unavailable');
bool _fields(dynamic value,Set<String> fields) => value is Map && value.length == fields.length && value.keys.every(fields.contains);
String _handle(dynamic value) => value is String && _uuid.hasMatch(value) ? value : _invalid();

/// Public metadata only: one identity for the entire device, never per network.
class ZeroTierDevice {
  const ZeroTierDevice._(this.handle,this.instanceId);
  final String handle,instanceId;
  factory ZeroTierDevice.checked(dynamic value) {
    if (!_fields(value,{'handle','instanceId'})) _invalid();
    return ZeroTierDevice._(_handle(value['handle']),_handle(value['instanceId']));
  }
  bool same(ZeroTierDevice other) => handle == other.handle && instanceId == other.instanceId;
}

class ZeroTierPending {
  const ZeroTierPending._(this.handle,this.phase);
  final String handle,phase;
  bool same(ZeroTierPending other) => handle == other.handle && phase == other.phase;
  factory ZeroTierPending.checked(dynamic value,{required bool creation}) {
    // These are the actual ZeroTierDeviceStoreCore phases, not runtime states.
    final phases = creation ? {'record-present','record-pending','finishing'} : {'record-present','record-removed','finishing'};
    if (!_fields(value,{'handle','phase'}) || value['phase'] is! String || !phases.contains(value['phase'])) _invalid();
    return ZeroTierPending._(_handle(value['handle']),value['phase'] as String);
  }
}

class ZeroTierDeviceStatus {
  const ZeroTierDeviceStatus._(this.available,this.device,this.pendingCreation,this.pendingDeletion);
  const ZeroTierDeviceStatus.unavailable() : this._(false,null,null,null);
  final bool available;
  final ZeroTierDevice? device;
  final ZeroTierPending? pendingCreation,pendingDeletion;
  factory ZeroTierDeviceStatus.checked(dynamic value) {
    if (!_fields(value,{'available','device','pendingCreation','pendingDeletion'}) || value['available'] is! bool) _invalid();
    final device = value['device'] == null ? null : ZeroTierDevice.checked(value['device']);
    final creation = value['pendingCreation'] == null ? null : ZeroTierPending.checked(value['pendingCreation'],creation:true);
    final deletion = value['pendingDeletion'] == null ? null : ZeroTierPending.checked(value['pendingDeletion'],creation:false);
    // Pending operations are exclusive; their record is deliberately not authenticated status.
    if ((creation != null && deletion != null) || (device != null && (creation != null || deletion != null)) ||
        (value['available'] == false && (device != null || creation != null || deletion != null))) _invalid();
    return ZeroTierDeviceStatus._(value['available'] as bool,device,creation,deletion);
  }
  bool get absent => available && device == null && pendingCreation == null && pendingDeletion == null;
}

abstract interface class ZeroTierDeviceStore {
  Future<ZeroTierDeviceStatus> status();
  Future<ZeroTierDevice> create(ZeroTierDeviceImpact impact);
  Future<void> forget(ZeroTierDevice device,ZeroTierDeviceImpact impact);
  Future<ZeroTierDevice> recoverPendingCreation(ZeroTierPending pending,ZeroTierDeviceImpact impact);
  Future<void> discardPendingCreation(ZeroTierPending pending,ZeroTierDeviceImpact impact);
  Future<void> recoverPendingDeletion(ZeroTierPending pending,ZeroTierDeviceImpact impact);
}

/// Frontend contract. Missing bridge/library is unavailable, never absent.
class NativeZeroTierDeviceStore implements ZeroTierDeviceStore {
  static const channel = MethodChannel('dev.herdr/zerotier-device');
  bool get supported => !kIsWeb && defaultTargetPlatform == TargetPlatform.android;
  @override
  Future<ZeroTierDeviceStatus> status() async {
    if (!supported) return const ZeroTierDeviceStatus.unavailable();
    try { return ZeroTierDeviceStatus.checked(await channel.invokeMethod<Object?>('status')); }
    catch (_) { return const ZeroTierDeviceStatus.unavailable(); }
  }
  Map<String,Object> _review(ZeroTierDeviceImpact impact) {
    if (!impact.ready) _invalid();
    return {'catalogRevision':impact.revision,'profileIds':impact.networks.map((p) => p.id).toList(),'hostIds':impact.hosts.map((h) => h.id).toList()};
  }
  Future<Object?> _write(String method,ZeroTierDeviceImpact impact,[ZeroTierPending? pending]) async {
    if (!supported) _invalid();
    if (pending != null && !zeroTierPendingActionAllowed(method,pending)) _invalid();
    try { return await channel.invokeMethod<Object?>(method,{..._review(impact),
      if (pending != null) ...{'handle':pending.handle,'expectedPhase':pending.phase}}); }
    catch (_) { throw const RemoteFailure('zerotier_device_write_unknown'); }
  }
  @override Future<ZeroTierDevice> create(ZeroTierDeviceImpact impact) async => ZeroTierDevice.checked(await _write('create',impact));
  @override Future<void> forget(ZeroTierDevice device,ZeroTierDeviceImpact impact) async {
    if (!supported) _invalid();
    try {
      final reply = await channel.invokeMethod<Object?>('forget',{..._review(impact),'handle':device.handle,'instanceId':device.instanceId});
      if (reply != null) _invalid();
    } catch (_) { throw const RemoteFailure('zerotier_device_write_unknown'); }
  }
  @override Future<ZeroTierDevice> recoverPendingCreation(ZeroTierPending pending,ZeroTierDeviceImpact impact) async {
    final recovered = ZeroTierDevice.checked(await _write('recoverPendingCreation',impact,pending));
    if (recovered.handle != pending.handle) throw const RemoteFailure('zerotier_device_write_unknown');
    return recovered;
  }
  @override Future<void> discardPendingCreation(ZeroTierPending pending,ZeroTierDeviceImpact impact) async {
    if (await _write('discardPendingCreation',impact,pending) != null) throw const RemoteFailure('zerotier_device_write_unknown');
  }
  @override Future<void> recoverPendingDeletion(ZeroTierPending pending,ZeroTierDeviceImpact impact) async {
    if (await _write('recoverPendingDeletion',impact,pending) != null) throw const RemoteFailure('zerotier_device_write_unknown');
  }
}

bool zeroTierPendingActionAllowed(String action,ZeroTierPending pending) => switch (action) {
  'recoverPendingCreation' => {'record-present','finishing'}.contains(pending.phase),
  'discardPendingCreation' => {'record-pending','finishing'}.contains(pending.phase),
  'recoverPendingDeletion' => {'record-present','record-removed','finishing'}.contains(pending.phase),
  _ => false,
};
String zeroTierPendingActionLabel(String action) => switch (action) {
  'recoverPendingCreation' => '恢复原身份创建',
  'discardPendingCreation' => '丢弃未完成创建',
  'recoverPendingDeletion' => '继续原身份移除',
  _ => '核对待完成操作',
};

/// Includes every ZeroTier network and all bound or legacy-labelled hosts,
/// including disabled and retired entries. No catalog write is performed.
class ZeroTierDeviceImpact {
  ZeroTierDeviceImpact._(this.key,this.revision,this.ready,this.networks,this.hosts);
  final String key,revision;
  final bool ready;
  final List<NetworkProfile> networks;
  final List<HostProfile> hosts;
  factory ZeroTierDeviceImpact.capture(HostCatalog catalog) {
    final networks = catalog.networkProfiles.where((p) => p.provider == 'zerotier').toList();
    final ids = networks.map((p) => p.id).toSet();
    final hosts = catalog.profiles.where((h) => ids.contains(h.networkProfileId) || h.provider == 'zerotier').toList();
    final key = jsonEncode({'revision':catalog.revision,'generation':catalog.generation,'ready':catalog.ready,'writing':catalog.writing,
      'networks':networks.map((n) => n.toJson()).toList(),'hosts':hosts.map((h) => h.toJson()).toList()});
    return ZeroTierDeviceImpact._(key,catalog.revision,catalog.ready && !catalog.writing,List.unmodifiable(networks),List.unmodifiable(hosts));
  }
}

class ZeroTierDeviceReview {
  ZeroTierDeviceReview._(this.device,this.impact);
  final ZeroTierDevice device;
  final ZeroTierDeviceImpact impact;
}
class ZeroTierPendingReview {
  ZeroTierPendingReview._(this.action,this.pending,this.impact);
  final String action;
  final ZeroTierPending pending;
  final ZeroTierDeviceImpact impact;
}
typedef BeforeZeroTierForget = Future<void> Function(ZeroTierDeviceReview review);

/// Device-wide admission survives route disposal and new native-store objects.
/// Keep the exact operation alive until it settles; completion only unlocks
/// another explicit action and asks visible sessions to read again.
class _ZeroTierDeviceWrites extends ChangeNotifier {
  Object? _owner;
  Future<dynamic>? _operation;
  bool get pending => _owner != null || _operation != null;
  Future<T> run<T>(Future<T> Function() action) {
    if (pending) throw const RemoteFailure('zerotier_device_write_pending');
    final owner = Object(); _owner = owner;
    final operation = Future<T>.sync(action); _operation = operation;
    notifyListeners();
    return operation.whenComplete(() {
      if (identical(_owner,owner)) { _owner = null; _operation = null; notifyListeners(); }
    });
  }
}
final _deviceWrites = _ZeroTierDeviceWrites();

/// A visible review owns no native capability. Epochs reject late reads and
/// invalidate both confirmation steps on background/catalog changes.
class ZeroTierDeviceSession extends ChangeNotifier {
  ZeroTierDeviceSession({required this.store,required this.impact,this.beforeForget}) {
    _deviceWrites.addListener(_writeChanged);
  }
  final ZeroTierDeviceStore store;
  final ZeroTierDeviceImpact Function() impact;
  final BeforeZeroTierForget? beforeForget;
  ZeroTierDeviceStatus? status;
  ZeroTierDeviceReview? review;
  ZeroTierPendingReview? pendingReview;
  String? notice;
  bool busy = false,_foreground = true,_disposed = false,_refreshQueued = false,_ownsWrite = false;
  int _epoch = 0;
  bool get known => status?.available == true;
  bool get writePending => _deviceWrites.pending;
  bool get canCreate => _active && !busy && !writePending && status?.absent == true;
  bool get canReview => _active && !busy && !writePending && status?.device != null && beforeForget != null;
  bool get _active => !_disposed && _foreground && impact().ready;
  void _publish() { if (!_disposed) notifyListeners(); }
  void invalidate() { _epoch++; status = null; review = null; pendingReview = null; notice = '审查已失效 · 请重新读取并核对完整影响列表。'; _publish(); }
  void _writeChanged() {
    if (_disposed || _ownsWrite) return;
    invalidate();
    if (writePending) { notice = '原设备操作尚未确认 · 本页暂时只读，不会重复操作。'; _publish(); }
    else if (_active) {
      if (busy) { _refreshQueued = true; } else { unawaited(refresh()); }
    }
  }
  void suspend() { _foreground = false; invalidate(); }
  Future<void> resume() async { _foreground = true; if (busy) { _refreshQueued = true; return; } await refresh(); }
  bool _current(int epoch,String key) => _active && epoch == _epoch && impact().key == key;
  Future<bool> _read(int epoch,String key) async {
    if (!_current(epoch,key)) return false;
    status = null;
    try {
      final result = await store.status();
      if (!_current(epoch,key)) return false;
      status = result; return result.available;
    } catch (_) { return false; }
  }
  void _finish() {
    busy = false; _publish();
    if (_refreshQueued && _active) { _refreshQueued = false; unawaited(refresh()); }
  }
  Future<void> refresh() async {
    if (!_active || busy) return;
    if (writePending) {
      invalidate(); notice = '原设备操作尚未确认 · 本页暂时只读，不会重复操作。'; _publish(); return;
    }
    review = null; pendingReview = null; status = null; busy = true; notice = null;
    final epoch = ++_epoch,key = impact().key; _publish();
    final read = await _read(epoch,key);
    if (_current(epoch,key) && !read) notice = '共享设备身份不可用 · 本版本可能未启用原生组件，或设备锁定、读取失败；请核对后重新读取，不会创建或替换身份。';
    _finish();
  }
  Future<void> create() async {
    if (!canCreate) return;
    final captured = impact();
    final epoch = ++_epoch,key = captured.key;
    status = null; review = null; pendingReview = null; busy = true; notice = null;
    ZeroTierDevice? created;
    _ownsWrite = true;
    try {
      final operation = _deviceWrites.run(() => store.create(captured)); _publish();
      created = await operation;
    } catch (_) { /* Unknown: read only. */ }
    finally { _ownsWrite = false; }
    final read = _current(epoch,key) && await _read(epoch,key);
    if (_current(epoch,key)) notice = read && created != null && status?.device?.same(created) == true
      ? '共享设备身份已创建 · 尚未启动 ZeroTier 或验证连通。'
      : '创建结果未确认 · 仅重新读取原状态，不会重发或替换身份。';
    _finish();
  }
  void beginReview() {
    if (!canReview) return;
    pendingReview = null; review = ZeroTierDeviceReview._(status!.device!,impact()); notice = null; _publish();
  }
  void cancelReview() { review = null; pendingReview = null; _publish(); }
  ZeroTierPending? _pendingFor(String action,ZeroTierDeviceStatus? value) =>
    action == 'recoverPendingDeletion' ? value?.pendingDeletion : value?.pendingCreation;
  bool canReviewPending(String action) {
    final pending = _pendingFor(action,status);
    return _active && !busy && !writePending && known && pending != null && zeroTierPendingActionAllowed(action,pending);
  }
  void beginPendingReview(String action) {
    if (!canReviewPending(action)) return;
    review = null; pendingReview = ZeroTierPendingReview._(action,_pendingFor(action,status)!,impact()); notice = null; _publish();
  }
  bool currentPendingReview(ZeroTierPendingReview value) => canReviewPending(value.action) && identical(pendingReview,value) &&
    impact().key == value.impact.key && _pendingFor(value.action,status)?.same(value.pending) == true;
  Future<void> confirmPending(ZeroTierPendingReview value) async {
    if (!currentPendingReview(value)) return;
    final epoch = ++_epoch,key = value.impact.key;
    pendingReview = null; busy = true; notice = null; _ownsWrite = true;
    bool success = false;
    ZeroTierDevice? recovered;
    try {
      final operation = _deviceWrites.run(() async {
        final observed = await store.status();
        if (!_current(epoch,key) || !observed.available || observed.device != null ||
            _pendingFor(value.action,observed)?.same(value.pending) != true) throw const RemoteFailure('zerotier_pending_changed');
        status = null;
        if (value.action == 'recoverPendingCreation') recovered = await store.recoverPendingCreation(value.pending,value.impact);
        else if (value.action == 'discardPendingCreation') await store.discardPendingCreation(value.pending,value.impact);
        else if (value.action == 'recoverPendingDeletion') await store.recoverPendingDeletion(value.pending,value.impact);
        else throw const RemoteFailure('zerotier_pending_changed');
        success = true;
      });
      _publish(); await operation;
    } catch (_) { /* Unknown outcomes permit only a status read, no fallback. */ }
    finally {
      _ownsWrite = false;
      final read = _current(epoch,key) && await _read(epoch,key);
      if (_current(epoch,key)) {
        final restoredRecord = recovered;
        final restored = value.action == 'recoverPendingCreation' && restoredRecord != null &&
          restoredRecord.handle == value.pending.handle && status?.device?.same(restoredRecord) == true;
        final cleared = value.action != 'recoverPendingCreation' && status?.absent == true;
        notice = success && read && (restored || cleared)
          ? restored ? '原身份创建已恢复 · 尚未启动网络连接。' : '原待完成操作已结束 · 已确认没有设备身份，不会自动新建。'
          : '操作结果未确认或原阶段已变化 · 已重新读取；不会自动重试、替换身份或改做其他操作。';
      }
      _finish();
    }
  }
  bool currentReview(ZeroTierDeviceReview value) => canReview && identical(review,value) &&
    impact().key == value.impact.key && status?.device?.same(value.device) == true;
  Future<void> forget(ZeroTierDeviceReview value) async {
    if (!currentReview(value)) return;
    final epoch = ++_epoch,key = value.impact.key;
    review = null; busy = true; notice = null;
    bool dispatched = false,success = false;
    _ownsWrite = true;
    try {
      final operation = _deviceWrites.run(() async {
        // This callback must prove all exact native nodes/attempts/streams retired.
        // Closing GUI tabs or leaving one network cannot satisfy this contract.
        await beforeForget!(value);
        if (!_current(epoch,key)) return;
        final observed = await store.status();
        if (!_current(epoch,key) || !observed.available || observed.device?.same(value.device) != true ||
            observed.pendingCreation != null || observed.pendingDeletion != null) {
          throw const RemoteFailure('zerotier_device_changed');
        }
        status = null; dispatched = true;
        await store.forget(value.device,value.impact); success = true;
      });
      _publish(); await operation;
    } catch (_) { /* Never repeat a mutation after an unknown result. */ }
    finally {
      _ownsWrite = false;
      final read = _current(epoch,key) && await _read(epoch,key);
      if (_current(epoch,key)) notice = dispatched && success && read && status?.absent == true
        ? '共享设备身份已移除 · 所有 ZeroTier 网络受影响；未自动创建新身份。'
        : '移除未确认或审查已变化 · 仅重新读取，不重发；请重新审查。';
      _finish();
    }
  }
  @override void dispose() {
    _disposed = true; _epoch++; review = null; pendingReview = null;
    _deviceWrites.removeListener(_writeChanged); super.dispose();
  }
}
