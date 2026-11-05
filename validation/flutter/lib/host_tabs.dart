import 'dart:convert';
import 'package:flutter/widgets.dart';
import 'host_catalog.dart';
import 'remote_adapter.dart';

const maxOpenHostTabs = 8;

/// Each tab owns a Navigator, visibility lease and optional independent test
/// adapter. Production adapters are constructed by that tab's RemotePage only.
class HostTab {
  HostTab(HostProfile profile,{this.adapter}) : id = profile.id,label = profile.label,
    provider = profile.provider,binding = bindingFor(profile);
  final String id,binding;
  String label,provider;
  final RemoteReadOnlyAdapter? adapter;
  final navigator = GlobalKey<NavigatorState>();
  final visible = ValueNotifier<bool>(false);
  static String bindingFor(HostProfile p) => jsonEncode({'id':p.id,'target':p.target,
    'handle':p.pairingRecord['handle'],'publicKey':(p.pairingRecord['request'] as Map)['public_key']});
  void dispose() { visible.value = false; visible.dispose(); }
}

/// Selecting a tab revokes the previous visibility lease before granting the
/// new one. Returning only exposes stopped UI; it never dials or sends input.
class HostTabs extends ChangeNotifier {
  final List<HostTab> _tabs = [];
  List<HostTab> get tabs => List.unmodifiable(_tabs);
  String? activeId;
  String? notice;
  int get activeIndex => activeId == null ? -1 : _tabs.indexWhere((t) => t.id == activeId);
  HostTab? get active => activeIndex < 0 ? null : _tabs[activeIndex];
  HostTab? find(String id) { final matches = _tabs.where((t) => t.id == id); return matches.isEmpty ? null : matches.single; }
  bool open(HostProfile profile,{RemoteReadOnlyAdapter? adapter}) {
    if (!profile.enabled) return false;
    var tab = find(profile.id);
    if (tab == null) {
      if (_tabs.length >= maxOpenHostTabs) { notice = '最多保留 $maxOpenHostTabs 个标签 · 请先关闭不需要的本地视图'; notifyListeners(); return false; }
      tab = HostTab(profile,adapter:adapter); _tabs.add(tab);
    } else if (tab.binding != HostTab.bindingFor(profile)) {
      close(tab.id); notice = '资料绑定已改变 · 原标签已关闭，请重新审查'; notifyListeners(); return false;
    }
    select(tab.id); return true;
  }
  void select(String? id) {
    if (id != null && find(id) == null) return;
    if (activeId == id) return;
    active?.visible.value = false;
    activeId = id; active?.visible.value = true; notice = null; notifyListeners();
  }
  void close(String id) {
    final tab = find(id); if (tab == null) return;
    tab.visible.value = false;
    if (activeId == id) activeId = null; // do not implicitly activate another host
    _tabs.remove(tab); tab.dispose(); notifyListeners();
  }
  void reconcile(List<HostProfile> profiles) {
    var changed = false;
    for (final tab in List<HostTab>.of(_tabs)) {
      final matches = profiles.where((p) => p.id == tab.id && p.enabled).toList();
      if (matches.length != 1 || HostTab.bindingFor(matches.single) != tab.binding) {
        close(tab.id); notice = '资料已停用、删除或绑定改变 · 对应标签已停止'; changed = true;
      } else if (tab.label != matches.single.label || tab.provider != matches.single.provider) {
        tab.label = matches.single.label; tab.provider = matches.single.provider; changed = true;
      }
    }
    if (changed) notifyListeners();
  }
  @override
  void dispose() { for (final tab in _tabs) { tab.dispose(); } _tabs.clear(); super.dispose(); }
}
