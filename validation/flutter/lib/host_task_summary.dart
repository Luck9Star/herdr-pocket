import 'dart:convert';
import 'package:flutter/widgets.dart';
import 'host_catalog.dart';
import 'network_profiles.dart';
import 'pairing.dart' show pairingFingerprint;
import 'remote_adapter.dart';
import 'remote_input.dart' show isValidOverlayRoute;

/// A single session snapshot, never a sum of duplicate views or routes.
class HostTaskSummary {
  const HostTaskSummary(this.source,this.syncedAt,this.paneCount,this.blockedCount,this.unknownCount,this.freshness);
  final RemoteDashboardSource source;
  final DateTime syncedAt;
  final int paneCount,blockedCount,unknownCount;
  final DashboardFreshness freshness;
  bool get current => freshness == DashboardFreshness.fresh;
  bool get priority => current && blockedCount > 0;
  HostTaskSummary stale() => HostTaskSummary(source,syncedAt,paneCount,blockedCount,unknownCount,DashboardFreshness.stale);
  String get label => '${current || freshness == DashboardFreshness.unavailable ? '主机报告' : '上次主机报告'} · 受阻${unknownCount > 0 ? '至少' : ''} $blockedCount 个${unknownCount > 0 ? '＋$unknownCount 个状态未知' : ''}${paneCount == 0 ? ' · 快照确认为空' : ' · 共 $paneCount 个窗格'}${current ? '' : freshness == DashboardFreshness.unavailable ? ' · 持续更新不可用（单次快照）' : ' · 状态待确认'}';
  String get detail => '原会话 ${source.session} · 最后同步 ${syncedAt.toLocal().toIso8601String()}';
}

/// Includes identity/endpoint/session/profile revision, but no private material.
String hostSummaryBinding(HostProfile profile,List<NetworkProfile> networks) => jsonEncode({
  'id':profile.id,'target':profile.target,'networkProfileId':profile.networkProfileId,
  'network':networks.where((p) => p.id == profile.networkProfileId).map((p) => p.toJson()).toList(),
  'handle':profile.pairingRecord['handle'],'request':profile.pairingRecord['request'],
});

/// Local memory only. The catalog is the authority for which row owns a report.
/// Notifications are deferred so a page can retire its lease during navigation.
class HostTaskSummaries extends ChangeNotifier {
  HostTaskSummaries(this.catalog) { catalog.addListener(reconcile); }
  final HostCatalog catalog;
  final _values = <String,HostTaskSummary>{};
  final _bindings = <String,String>{};
  final _owners = <String,HostDashboardLease>{};
  final _leases = <HostDashboardLease>{};
  final _admissions = <String,Object>{};
  bool _foreground = true,_disposed = false,_queued = false;
  int _lifecycle = 0;
  HostTaskSummary? forHost(String id) => _values[id];
  List<HostProfile> get orderedHosts => [
    for (final profile in catalog.profiles) if (forHost(profile.id)?.priority == true) profile,
    for (final profile in catalog.profiles) if (forHost(profile.id)?.priority != true) profile,
  ];
  void _publish() {
    if (_disposed || _queued) return; _queued = true;
    WidgetsBinding.instance.addPostFrameCallback((_) { _queued = false; if (!_disposed) notifyListeners(); });
    WidgetsBinding.instance.scheduleFrame();
  }
  HostProfile? _profile(String id) {
    if (!catalog.ready) return null;
    final matches = catalog.profiles.where((p) => p.id == id && p.enabled && !p.retired && p.hasIdentity && p.pairingRecord['authorization'] != 'revoked').toList();
    return matches.length == 1 ? matches.single : null;
  }
  HostDashboardLease open(HostProfile profile,{bool Function()? visible}) {
    final lease = HostDashboardLease._(this,profile.id,hostSummaryBinding(profile,catalog.networkProfiles),visible ?? (() => true));
    _leases.add(lease); return lease;
  }
  void setForeground(bool value) {
    if (_disposed || _foreground == value) return;
    _foreground = value;
    if (!value) {
      _lifecycle++;
      for (final lease in _leases.toList()) { lease.invalidate(); }
      for (final id in _values.keys.toList()) { _values[id] = _values[id]!.stale(); }
      _publish();
    }
  }
  void reconcile() {
    if (_disposed) return;
    if (!catalog.ready) {
      for (final lease in _leases.toList()) { lease.invalidate(); }
      for (final id in _values.keys.toList()) { _values[id] = _values[id]!.stale(); }
    } else {
      _admissions.removeWhere((id,_) => _profile(id) == null);
      for (final id in _values.keys.toList()) {
        final profile = _profile(id);
        if (profile == null || hostSummaryBinding(profile,catalog.networkProfiles) != _bindings[id]) {
          _values.remove(id); _bindings.remove(id); _owners.remove(id);
        }
      }
      for (final lease in _leases.toList()) {
        final profile = _profile(lease.hostId);
        if (profile == null || hostSummaryBinding(profile,catalog.networkProfiles) != lease.binding) lease.close();
      }
    }
    _publish();
  }
  bool _matches(HostProfile profile,RemoteDashboardSource source) {
    final target = profile.target;
    if (source.host != target['host'] || source.port != target['port'] || source.username != target['username'] ||
        source.session != target['session'] || source.socketPath != target['socketPath'] || source.herdrPath != target['herdrPath'] ||
        source.hostFingerprint != pairingFingerprint(target['expectedHostKey'] as String)) return false;
    if (profile.networkProfileId == null) return source.route == 'system';
    final matches = catalog.networkProfiles.where((p) => p.id == profile.networkProfileId && p.enabled).toList();
    if (matches.length != 1 || !isValidOverlayRoute(source.route)) return false;
    final network = matches.single,provider = network.provider == 'easytier' ? 'easy-tier' : network.provider;
    return source.route.startsWith('$provider:${network.id}:${network.revision}:');
  }
  void _stale(HostDashboardLease lease) {
    if (identical(_owners[lease.hostId],lease) && _values.containsKey(lease.hostId)) {
      _values[lease.hostId] = _values[lease.hostId]!.stale(); _publish();
    }
  }
  void _accept(HostDashboardAttempt attempt,RemoteDashboard board) {
    final lease = attempt.lease,source = board.source;
    if (_disposed || !_foreground || lease.closed || !_leases.contains(lease) || !lease.visible() ||
        attempt.epoch != lease.epoch || attempt.lifecycle != _lifecycle || !identical(attempt.admission,_admissions[lease.hostId]) || source == null || board.syncedAt == null) return;
    final profile = _profile(lease.hostId);
    if (profile == null || hostSummaryBinding(profile,catalog.networkProfiles) != lease.binding ||
        board.session != source.session || !_matches(profile,source)) { lease.invalidate(); return; }
    if (board.generation < attempt.generation || (board.generation == attempt.generation && board.revision <= attempt.revision)) return;
    if (attempt.source != null && attempt.source != source.endpointKey) { lease.invalidate(); return; }
    attempt.generation = board.generation; attempt.revision = board.revision;
    // Invalidations do not establish authority, even on the first report.
    // They may retire only their own last authoritative snapshot.
    if (board.freshness == DashboardFreshness.stale || board.freshness == DashboardFreshness.refreshing) {
      _stale(lease); return;
    }
    attempt.source = source.endpointKey;
    _values[lease.hostId] = HostTaskSummary(source,board.syncedAt!,board.panes.length,
      board.panes.where((pane) => pane.agentStatus == 'blocked').length,
      board.panes.where((pane) => !{'working','blocked','idle','done'}.contains(pane.agentStatus)).length,board.freshness);
    _bindings[lease.hostId] = lease.binding; _owners[lease.hostId] = lease; _publish();
  }
  @override void dispose() {
    _disposed = true; catalog.removeListener(reconcile);
    for (final lease in _leases.toList()) { lease.close(); }
    _values.clear(); _bindings.clear(); _owners.clear(); _admissions.clear(); super.dispose();
  }
}

class HostDashboardLease {
  HostDashboardLease._(this.registry,this.hostId,this.binding,this.visible);
  final HostTaskSummaries registry;
  final String hostId,binding;
  final bool Function() visible;
  bool closed = false;
  int epoch = 0;
  HostDashboardAttempt? begin() {
    if (closed || !registry._foreground || !visible()) return null;
    invalidate();
    final admission = Object();
    registry._admissions[hostId] = admission;
    final owner = registry._owners[hostId];
    if (owner != null) registry._stale(owner);
    return HostDashboardAttempt._(this,epoch,registry._lifecycle,admission);
  }
  void invalidate() { epoch++; registry._stale(this); }
  void close() { if (closed) return; invalidate(); closed = true; registry._leases.remove(this); }
}
class HostDashboardAttempt {
  HostDashboardAttempt._(this.lease,this.epoch,this.lifecycle,this.admission);
  final HostDashboardLease lease;
  final int epoch,lifecycle;
  final Object admission;
  int generation = -1,revision = -1;
  String? source;
  void publish(RemoteDashboard board) => lease.registry._accept(this,board);
}
