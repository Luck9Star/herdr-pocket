import 'dart:async';
import 'dart:convert';
import 'dart:math';
import 'package:flutter/widgets.dart';
import 'host_catalog.dart';
import 'network_profiles.dart';
import 'remote_adapter.dart';
import 'remote_terminal_screen.dart';
import 'host_task_summary.dart';

const maxOpenHostTabs = 8;

/// Each tab owns a Navigator, visibility lease and optional independent test
/// adapter. Production adapters are constructed by that tab's RemotePage only.
class HostTab {
  HostTab(this.id,HostProfile profile,{RemoteReadOnlyAdapter? adapter,this.requestedTarget,List<NetworkProfile> networks=const []}) : hostId = profile.id,label = profile.label,
    provider = profile.provider,networkLabel = networkFor(profile,networks),_binding = bindingFor(profile,networks),_adapter = adapter,
    authorization = profile.pairingRecord['authorization'] as String?,consumed = profile.pairingRecord['consumed'] == true,
    view = ValueNotifier<HostTabView>(HostTabView('stale',requestedTarget?.paneId,requestedTarget?.terminalId));
  final String id,hostId;
  String? _binding;
  String? get binding => _binding;
  String label,provider,networkLabel;
  String? authorization;
  bool consumed;
  RemoteReadOnlyAdapter? _adapter;
  RemoteReadOnlyAdapter? get adapter => _adapter;
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
  RetainedHostScreen? Function()? _takeScreen;
  RetainedHostScreen? _retainedScreen;
  RetainedHostScreen? get retainedScreen => _retainedScreen;
  final _routeClosures = <Future<void>>{};
  bool _retired = false;
  bool get retired => _retired;
  ReleaseHostTransport registerTransport(Future<void> Function() close,{RetainedHostScreen? Function()? takeScreen}) {
    _closeTransport = close;
    _takeScreen = takeScreen;
    return (closing,screen) {
      if (_disposed || _retired || !identical(_closeTransport,close)) { screen?.terminal.dispose(); return; }
      _closeTransport = null; _takeScreen = null;
      if (screen != null) { _retainedScreen?.terminal.dispose(); _retainedScreen = screen; }
      _routeClosures.add(closing);
      unawaited(closing.then<void>((_) { _routeClosures.remove(closing); },onError:(Object _,StackTrace __) {}));
    };
  }
  Future<void> closeTransport() async {
    final close = _closeTransport;
    await Future.wait({..._routeClosures,if (close != null) Future<void>.sync(close)});
  }
  void _retainScreen() {
    _retired = true;
    final screen = _takeScreen?.call();
    if (screen != null) { _retainedScreen?.terminal.dispose(); _retainedScreen = screen; }
    _reportRetirement('retiring');
  }
  void _reportRetirement(String state) {
    if (_disposed) return;
    final previous = view.value, screen = _retainedScreen;
    view.value = HostTabView(state,screen?.paneId ?? previous.paneId,
      screen?.terminalId ?? previous.terminalId,screen?.frameAt);
  }
  void _releaseAuthority() {
    visible.value = false; layoutHidden.value = false;
    summaryLease?.close(); summaryLease = null;
    _closeTransport = null; _takeScreen = null;
    _routeClosures.clear();
    _binding = null; _adapter = null; authorization = null; consumed = false;
  }
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
      if (!_disposed && !retired && revision == _viewRevision) view.value = HostTabView(state,paneId,terminalId,frameAt);
    });
  }
  static String bindingFor(HostProfile p,[List<NetworkProfile> networks=const []]) => jsonEncode({'id':p.id,'target':p.target,
    'networkProfileId':p.networkProfileId,'requiresNetworkBinding':p.requiresNetworkBinding,'network':p.networkProfileId == null ? null : networks.where((n) => n.id == p.networkProfileId).map((n) => n.toJson()).toList(),
    'pairing':{'handle':p.pairingRecord['handle'],'request':p.pairingRecord['request']}});
  void dispose() { _disposed = true; _retainedScreen?.terminal.dispose(); summaryLease?.close(); visible.value = false; inputEligible.value = false; visible.dispose(); inputEligible.dispose(); layoutHidden.dispose(); view.dispose(); }
}

class HostTabView {
  const HostTabView(this.state,this.paneId,this.terminalId,[this.frameAt]);
  final String state;
  final String? paneId,terminalId;
  final DateTime? frameAt;
  String get label => switch (state) {
    'live' => '观察中', 'paused' => '已暂停', 'unknown' => '结果未知',
    'retiring' => '已停用 · 正在关闭连接', 'retired' => '已停用 · 连接已停止',
    'retired-unconfirmed' => '已停用 · 连接关闭未确认', _ => '陈旧',
  };
  String get target => paneId == null ? '尚未选目标' : '$paneId · ${terminalId ?? '未知终端'}';
  String get frameLabel => frameAt == null ? '尚无终端画面' : '画面更新于 ${frameAt!.toLocal().toIso8601String().substring(0,16).replaceAll('T',' ')}';
}

/// Selecting a tab revokes the previous visibility lease before granting the
/// new one. Returning only exposes stopped UI; it never dials or sends input.
class HostTabs extends ChangeNotifier {
  final List<HostTab> _tabs = [];
  final Map<HostTab,Future<void>> _closingTransports = {};
  final Map<String,Set<Future<void>>> _replacementClosures = {};
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
    if (activeId == id) {
      final tab = active;
      if (tab != null && !tab.retired && !tab.inputEligible.value) {
        tab.inputEligible.value = true;
        notifyListeners();
      }
      return;
    }
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
    final selected = active;
    if (selected != null && !selected.retired) {
      selected.layoutHidden.value = false;
      selected.visible.value = true;
      selected.inputEligible.value = true;
    }
    notice = null; notifyListeners();
  }
  void splitWith(String id) {
    final other = find(id);
    if (!_splitAvailable || active == null || other == null || id == activeId || id == splitId) return;
    final previous = splitId == null ? null : find(splitId!);
    previous?.summaryLease?.invalidate(); previous?.visible.value = false;
    splitId = id; splitLeftId = activeId;
    other.layoutHidden.value = false;
    other.visible.value = !other.retired;
    other.inputEligible.value = false;
    notice = null; notifyListeners();
  }
  void setSplitAvailable(bool available) {
    if (_splitAvailable == available) return;
    _splitAvailable = available;
    final other = splitId == null ? null : find(splitId!);
    if (other == null || other.retired) return;
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
    if (!tab.retired) _startTransportClose(tab);
    _removeTab(tab);
  }
  Future<void> retireReplacedHosts(Set<String> hostIds,{Duration budget = const Duration(seconds:5)}) async {
    final affected = _tabs.where((tab) => !tab.retired && hostIds.contains(tab.hostId)).toList();
    for (final tab in affected) {
      tab._retainScreen();
      final closing = _startTransportClose(tab);
      final pending = _replacementClosures.putIfAbsent(tab.hostId,() => {});
      pending.add(closing);
      unawaited(closing.then<void>((_) {
        pending.remove(closing);
        if (pending.isEmpty) _replacementClosures.remove(tab.hostId);
        tab._reportRetirement('retired');
      },onError:(Object _,StackTrace __) { tab._reportRetirement('retired-unconfirmed'); }));
      tab._releaseAuthority();
    }
    if (affected.isNotEmpty) notifyListeners();
    try {
      await Future.wait({
        for (final id in hostIds) ...?_replacementClosures[id],
        for (final entry in _closingTransports.entries)
          if (hostIds.contains(entry.key.hostId)) entry.value,
      }).timeout(budget);
    } catch (_) {
      for (final tab in affected) {
        if (!tab._disposed && tab.view.value.state == 'retiring') tab._reportRetirement('retired-unconfirmed');
      }
      throw const RemoteFailure('catalog_transfer_close_unconfirmed');
    }
  }
  Future<void> _startTransportClose(HostTab tab) {
    final pending = _closingTransports[tab];
    if (pending != null) return pending;
    final completion = Completer<void>();
    final closing = _closingTransports[tab] = completion.future;
    tab.inputEligible.value = false;
    completion.complete(Future<void>.sync(tab.closeTransport));
    // The tab can disappear before the transport has finished. Node stop can
    // still join this attempt, and a UI-only close owns any asynchronous error.
    unawaited(closing.then<void>((_) { _closingTransports.remove(tab); },
      onError:(Object _,StackTrace __) { _closingTransports.remove(tab); }));
    return closing;
  }
  void _removeTab(HostTab tab) {
    if (!_tabs.remove(tab)) return;
    final id = tab.id;
    tab.inputEligible.value = false; tab.summaryLease?.close(); tab.visible.value = false;
    if (activeId == id) {
      final other = splitId == null ? null : find(splitId!);
      // Keep an already displayed pane visible without transferring input.
      activeId = other != null && (other.visible.value || (other.retired && _splitAvailable)) ? other.id : null;
      other?.layoutHidden.value = false;
      splitId = null; splitLeftId = null;
    } else if (splitId == id) { splitId = null; splitLeftId = null; }
    tab.dispose(); notifyListeners();
  }
  void closeHost(String hostId) { for (final tab in forHost(hostId).where((tab) => !tab.retired).toList()) { _removeTab(tab); } }
  /// Start cancellation before removing widgets; a frame is not a cleanup ack.
  Future<bool> closeHostsAndWait(Set<String> hostIds,{Duration budget = const Duration(seconds:5)}) async {
    final affected = _tabs.where((tab) => !tab.retired && hostIds.contains(tab.hostId)).toList();
    final closing = <Future<void>>{
      for (final entry in _closingTransports.entries)
        if (hostIds.contains(entry.key.hostId)) entry.value,
      for (final tab in affected) _startTransportClose(tab),
    };
    for (final tab in affected) { _removeTab(tab); }
    try { await Future.wait(closing).timeout(budget); return true; }
    catch (_) { return false; } // User stop remains available after bounded cleanup.
  }

  void reconcile(List<HostProfile> profiles,[List<NetworkProfile> networks=const []]) {
    var changed = false;
    for (final tab in List<HostTab>.of(_tabs)) {
      if (tab.retired) continue;
      final matches = profiles.where((p) => p.id == tab.hostId && p.enabled && !p.retired).toList();
      final currentAuth = matches.length == 1 ? matches.single.pairingRecord['authorization'] : null;
      final currentConsumed = matches.length == 1 && matches.single.pairingRecord['consumed'] == true;
      final authorityReduced = currentAuth == 'revoked' || (tab.authorization == 'authorized' && currentAuth != 'authorized') ||
        (tab.consumed && !currentConsumed);
      if (matches.length != 1 || matches.single.requiresNetworkBinding || authorityReduced || HostTab.bindingFor(matches.single,networks) != tab.binding || (matches.single.networkProfileId != null && !networks.any((n) => n.id == matches.single.networkProfileId))) {
        _removeTab(tab); notice = '资料已停用、删除或绑定改变 · 对应标签已停止'; changed = true;
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
  void dispose() { for (final tab in _tabs) { tab.dispose(); } _tabs.clear(); _replacementClosures.clear(); super.dispose(); }
}
