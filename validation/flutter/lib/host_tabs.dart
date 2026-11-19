import 'dart:async';
import 'dart:convert';
import 'dart:math';
import 'package:flutter/widgets.dart';
import 'host_catalog.dart';
import 'network_profiles.dart';
import 'remote_adapter.dart';
import 'host_task_summary.dart';

const maxOpenHostTabs = 8;

/// Each tab owns a Navigator, visibility lease and optional independent test
/// adapter. Production adapters are constructed by that tab's RemotePage only.
class HostTab {
  HostTab(this.id,HostProfile profile,{this.adapter,this.requestedTarget,List<NetworkProfile> networks=const []}) : hostId = profile.id,label = profile.label,
    provider = profile.provider,networkLabel = networkFor(profile,networks),binding = bindingFor(profile,networks),
    authorization = profile.pairingRecord['authorization'] as String?,consumed = profile.pairingRecord['consumed'] == true,
    view = ValueNotifier<HostTabView>(HostTabView('stale',requestedTarget?.paneId,requestedTarget?.terminalId));
  final String id,hostId,binding;
  String label,provider,networkLabel;
  String? authorization;
  bool consumed;
  final RemoteReadOnlyAdapter? adapter;
  final RemotePane? requestedTarget;
  final navigator = GlobalKey<NavigatorState>();
  final visible = ValueNotifier<bool>(false);
  final inputEligible = ValueNotifier<bool>(false);
  // True while the layout (not the user) stashed this pane for narrow width;
  // re-widening consumes it to auto-resume the paused observation (D2).
  final layoutHidden = ValueNotifier<bool>(false);
  final ValueNotifier<HostTabView> view;
  HostDashboardLease? summaryLease;
  Future<void> Function()? _closeTransport;
  VoidCallback registerTransport(Future<void> Function() close) {
    _closeTransport = close;
    return () { if (identical(_closeTransport,close)) _closeTransport = null; };
  }
  Future<void> closeTransport() => _closeTransport?.call() ?? Future<void>.value();
  bool _disposed = false;
  int _viewRevision = 0;
  static String networkFor(HostProfile p,List<NetworkProfile> networks) {
    if (p.requiresNetworkBinding) return '待绑定网络';
    if (p.networkProfileId == null) return '系统直连';
    final found = networks.where((n) => n.id == p.networkProfileId).toList();
    return found.length == 1 ? '${found.single.label} · ${found.single.provider}' : '网络未知';
  }
  void report(String state,String? paneId,String? terminalId,DateTime? frameAt) {
    final revision = ++_viewRevision;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_disposed && revision == _viewRevision) view.value = HostTabView(state,paneId,terminalId,frameAt);
    });
  }
  static String bindingFor(HostProfile p,[List<NetworkProfile> networks=const []]) => jsonEncode({'id':p.id,'target':p.target,
    'networkProfileId':p.networkProfileId,'requiresNetworkBinding':p.requiresNetworkBinding,'network':p.networkProfileId == null ? null : networks.where((n) => n.id == p.networkProfileId).map((n) => n.toJson()).toList(),
    'pairing':{'handle':p.pairingRecord['handle'],'request':p.pairingRecord['request']}});
  void dispose() { _disposed = true; summaryLease?.close(); visible.value = false; inputEligible.value = false; visible.dispose(); inputEligible.dispose(); layoutHidden.dispose(); view.dispose(); }
}

class HostTabView {
  const HostTabView(this.state,this.paneId,this.terminalId,[this.frameAt]);
  final String state;
  final String? paneId,terminalId;
  final DateTime? frameAt;
  String get label => switch (state) { 'live' => '观察中', 'paused' => '已暂停', 'unknown' => '结果未知', _ => '陈旧' };
  String get target => paneId == null ? '尚未选目标' : '$paneId · ${terminalId ?? '未知终端'}';
  String get frameLabel => frameAt == null ? '尚无终端画面' : '画面更新于 ${frameAt!.toLocal().toIso8601String().substring(0,16).replaceAll('T',' ')}';
}

/// Selecting a tab revokes the previous visibility lease before granting the
/// new one. Returning only exposes stopped UI; it never dials or sends input.
class HostTabs extends ChangeNotifier {
  final List<HostTab> _tabs = [];
  final String _instance = List.generate(16,(_) => Random.secure().nextInt(256).toRadixString(16).padLeft(2,'0')).join();
  int _nextId = 0;
  List<HostTab> get tabs => List.unmodifiable(_tabs);
  String? activeId;
  String? splitId;
  String? splitLeftId;
  bool _splitAvailable = true;
  bool get splitAvailable => _splitAvailable;
  String? notice;
  int get activeIndex => activeId == null ? -1 : _tabs.indexWhere((t) => t.id == activeId);
  HostTab? get active => activeIndex < 0 ? null : _tabs[activeIndex];
  HostTab? find(String id) { final matches = _tabs.where((t) => t.id == id); return matches.isEmpty ? null : matches.single; }
  Iterable<HostTab> forHost(String hostId) => _tabs.where((tab) => tab.hostId == hostId);
  bool open(HostProfile profile,{RemoteReadOnlyAdapter? adapter,RemotePane? requestedTarget,List<NetworkProfile> networks=const []}) {
    if (!profile.enabled || profile.retired || !profile.hasIdentity || profile.requiresNetworkBinding || (profile.networkProfileId != null && !networks.any((n) => n.id == profile.networkProfileId))) return false;
    if (_tabs.length >= maxOpenHostTabs) { notice = '最多保留 $maxOpenHostTabs 个标签 · 请先关闭不需要的本地视图'; notifyListeners(); return false; }
    final id = '$_instance-${++_nextId}';
    final tab = HostTab(id,profile,adapter:adapter,requestedTarget:requestedTarget,networks:networks); _tabs.add(tab);
    select(tab.id); return true;
  }
  /// Both visible tabs may observe; input belongs only to the selected tab.
  void select(String? id) {
    if (id != null && find(id) == null) return;
    if (activeId == id) return;
    final old = active;
    old?.inputEligible.value = false;
    if (_splitAvailable && splitId != null && id == splitId) {
      splitId = activeId;
    } else {
      old?.summaryLease?.invalidate(); old?.visible.value = false;
      final other = splitId == null ? null : find(splitId!);
      other?.summaryLease?.invalidate(); other?.visible.value = false;
      splitId = null; splitLeftId = null;
    }
    activeId = id;
    active?.layoutHidden.value = false;
    active?.visible.value = true;
    active?.inputEligible.value = true;
    notice = null; notifyListeners();
  }
  void splitWith(String id) {
    final other = find(id);
    if (!_splitAvailable || active == null || other == null || id == activeId || id == splitId) return;
    final previous = splitId == null ? null : find(splitId!);
    previous?.summaryLease?.invalidate(); previous?.visible.value = false;
    splitId = id; splitLeftId = activeId;
    other.layoutHidden.value = false;
    other.visible.value = true;
    other.inputEligible.value = false;
    notice = null; notifyListeners();
  }
  void setSplitAvailable(bool available) {
    if (_splitAvailable == available) return;
    _splitAvailable = available;
    final other = splitId == null ? null : find(splitId!);
    if (other == null) return;
    if (!available) other.summaryLease?.invalidate();
    // Narrowing stashes the side pane; re-widening reveals it and the page's
    // visibility listener consumes layoutHidden to auto-resume observation.
    // User-driven reveals (select, splitWith, closeSplit) keep manual resume.
    if (!available) other.layoutHidden.value = true;
    other.visible.value = available;
    notifyListeners();
  }
  void closeSplit() {
    final other = splitId == null ? null : find(splitId!);
    if (other == null) { splitId = null; splitLeftId = null; return; }
    other.inputEligible.value = false; other.summaryLease?.invalidate(); other.layoutHidden.value = false; other.visible.value = false;
    splitId = null; splitLeftId = null; notifyListeners();
  }
  void close(String id) {
    final tab = find(id); if (tab == null) return;
    tab.inputEligible.value = false; tab.summaryLease?.close(); tab.visible.value = false;
    if (activeId == id) {
      final other = splitId == null ? null : find(splitId!);
      other?.summaryLease?.invalidate(); other?.visible.value = false;
      activeId = null; splitId = null; splitLeftId = null; // do not implicitly activate another host
    } else if (splitId == id) { splitId = null; splitLeftId = null; }
    _tabs.remove(tab); tab.dispose(); notifyListeners();
  }
  void closeHost(String hostId) { for (final tab in List<HostTab>.of(forHost(hostId))) { close(tab.id); } }
  /// Start cancellation before removing widgets; a frame is not a cleanup ack.
  Future<bool> closeHostsAndWait(Set<String> hostIds,{Duration budget = const Duration(seconds:5)}) async {
    final affected = _tabs.where((tab) => hostIds.contains(tab.hostId)).toList();
    final closing = [for (final tab in affected) Future<void>.sync(tab.closeTransport)];
    for (final tab in affected) { close(tab.id); }
    try { await Future.wait(closing).timeout(budget); return true; }
    catch (_) { return false; } // User stop remains available after bounded cleanup.
  }

  void reconcile(List<HostProfile> profiles,[List<NetworkProfile> networks=const []]) {
    var changed = false;
    for (final tab in List<HostTab>.of(_tabs)) {
      final matches = profiles.where((p) => p.id == tab.hostId && p.enabled && !p.retired).toList();
      final currentAuth = matches.length == 1 ? matches.single.pairingRecord['authorization'] : null;
      final currentConsumed = matches.length == 1 && matches.single.pairingRecord['consumed'] == true;
      final authorityReduced = currentAuth == 'revoked' || (tab.authorization == 'authorized' && currentAuth != 'authorized') ||
        (tab.consumed && !currentConsumed);
      if (matches.length != 1 || matches.single.requiresNetworkBinding || authorityReduced || HostTab.bindingFor(matches.single,networks) != tab.binding || (matches.single.networkProfileId != null && !networks.any((n) => n.id == matches.single.networkProfileId))) {
        close(tab.id); notice = '资料已停用、删除或绑定改变 · 对应标签已停止'; changed = true;
      } else {
        tab.authorization = currentAuth as String?; tab.consumed = currentConsumed;
        if (tab.label != matches.single.label || tab.provider != matches.single.provider) {
          tab.label = matches.single.label; tab.provider = matches.single.provider;
          tab.networkLabel = HostTab.networkFor(matches.single,networks); changed = true;
        }
      }
    }
    if (changed) notifyListeners();
  }
  @override
  void dispose() { for (final tab in _tabs) { tab.dispose(); } _tabs.clear(); super.dispose(); }
}
