import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/host_tabs.dart';
import 'package:herdr_flutter_probe/network_profiles_page.dart';
import 'package:herdr_flutter_probe/pairing_page.dart';
import 'package:herdr_flutter_probe/pairing_public_key.dart';
import 'package:herdr_flutter_probe/pairing.dart' show decodePairing;
import 'package:herdr_flutter_probe/remote_page.dart';
import 'package:herdr_flutter_probe/connection_diagnostics.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart' show RemoteReadOnlyAdapter;
import 'dart:typed_data';
import 'package:terminal_view/terminal_view.dart';

import 'android_pairing_observe_test.dart' as existing;

Finder remotePaneChoices() => find.byWidgetPredicate((widget) => widget is FilledButton &&
    widget.key is ValueKey<String> && (widget.key! as ValueKey<String>).value.startsWith('remote-pane-'));

bool hostBindingReady(HostCatalog catalog, String hostId, String networkId) =>
    catalog.ready && !catalog.writing &&
    catalog.profiles.any((host) => host.id == hostId && host.networkProfileId == networkId);

/// Real UI actions shared by the two independently paired overlay targets.
/// Requests, responses and credentials stay in the app's private exchange.
class DualOverlayUiSteps {
  DualOverlayUiSteps(this.tester, this.exchange, {this.diagnosticClock});
  final WidgetTester tester;
  final Directory exchange;
  final int Function()? diagnosticClock;
  String currentStage = 'fixture_validation';
  Map<String, Object>? nodeDiagnostic;
  bool responseReceived = false;
  Map<String, Object>? responseCheck;
  Map<String, Object>? bindingCheck;
  bool? bindingSelectionMatches;
  Map<String, Object>? remoteCheck;
  bool selectionAttempted = false;
  String? expectedPane, expectedTerminal;
  String? currentRemoteRole;

  Future<void> stage(String value) async {
    if (!RegExp(r'^[a-z][a-z0-9_]{0,50}$').hasMatch(value)) {
      throw StateError('dual_stage_invalid');
    }
    currentStage = value;
    if (!value.contains('_response_')) responseCheck = null;
    if (!value.contains('_bind_')) { bindingCheck = null; bindingSelectionMatches = null; }
    if (!value.contains('_remote_')) remoteCheck = null;
    if (!(value.endsWith('_node_wait') || value == 'ts_node_ready_refresh')) {
      nodeDiagnostic = null;
    }
    existing.publish(exchange, 'stage', value);
    await tester.pump();
  }

  Future<String> awaitFile(String name) async {
    if (!RegExp(r'^[a-z0-9-]+\.(json|txt)$').hasMatch(name)) {
      throw StateError('dual_exchange_name_invalid');
    }
    final file = File('${exchange.path}/$name');
    await existing.until(tester, file.existsSync, seconds: 90);
    final value = await file.readAsString();
    if (utf8.encode(value).length > 65536) throw StateError('dual_exchange_oversize');
    return value;
  }

  Future<void> enter(String key, String text) async {
    final field = find.byKey(ValueKey(key));
    await tester.ensureVisible(field);
    await tester.enterText(field, text);
    await tester.pump();
  }

  Future<void> choose(String key, String value) async {
    final field = find.byKey(ValueKey(key));
    final dropdown = find.descendant(of: field, matching: find.byType(DropdownButton<String>));
    await existing.tapStablePointer(tester, dropdown);
    final option = find.text(value).last;
    await existing.tapPopupOption(tester, option);
  }

  String readVisibleNotice() {
    final notice = find.byKey(const ValueKey('networks-notice'));
    if (notice.evaluate().length != 1) return 'not_visible';
    final message = tester.widget<Text>(notice).data ?? '';
    return message.contains('节点启动未确认') ? 'start_unconfirmed'
      : message.contains('不支持无密码模式') ? 'public_unsupported' : 'other';
  }

  Future<void> captureFailureNotice() async {
    if (currentStage.contains('_remote_')) {
      try { remoteCheck = inspectRemote(); } catch (_) { /* Keep the original failure. */ }
    }
    if (nodeDiagnostic == null ||
        !(currentStage.endsWith('_node_wait') || currentStage == 'ts_node_ready_refresh')) return;
    try {
      final add = find.byKey(const ValueKey('networks-add'));
      if (add.evaluate().isEmpty) {
        await tester.scrollUntilVisible(add, -300, scrollable: find.byType(Scrollable).last, maxScrolls: 12);
      } else {
        await tester.ensureVisible(add);
      }
      await tester.pump();
      nodeDiagnostic!['notice'] = readVisibleNotice();
    } catch (_) {
      // Keep the previous fixed diagnostic and always preserve the original failure.
    }
  }

  Map<String, Object> readNodeDiagnostic(String id) {
    final status = find.byKey(ValueKey('network-node-status-$id'));
    final text = status.evaluate().length == 1 ? (tester.widget<Text>(status).data ?? '') : '';
    final state = text.contains('引擎已启动') ? 'engine_started'
      : text.contains('等待本设备授权') ? 'needs_login'
      : text.contains('等待网络管理员批准') ? 'needs_machine_auth'
      : text.contains('Tailscale 已就绪') ? 'running'
      : text.contains('正在启动') ? 'starting'
      : text.contains('正在停止') ? 'closing'
      : text.contains('已停止') ? 'stopped'
      : text.contains('状态未知') ? 'unknown'
      : text.contains('运行时不可用') ? 'unavailable' : 'other';
    final edit = find.byKey(ValueKey('network-edit-$id'));
    final add = find.byKey(const ValueKey('networks-add'));
    return {'nodeState': state, 'statusPresent': status.evaluate().length == 1,
      'editPresent': edit.evaluate().length == 1,
      'editEnabled': edit.evaluate().length == 1 && tester.widget<TextButton>(edit).onPressed != null,
      'addPresent': add.evaluate().length == 1,
      'addEnabled': add.evaluate().length == 1 && tester.widget<FilledButton>(add).onPressed != null,
      'notice': readVisibleNotice()};
  }

  Future<String> createNetwork({required String role, required String label,
      required String controlUrl, required String networkName,
      required String peerUrl, required String networkSecret}) async {
    if (!{'et', 'ts'}.contains(role)) throw StateError('dual_role_invalid');
    nodeDiagnostic = null;
    await stage('${role}_network_create');
    await existing.tapKey(tester, 'networks-add');
    await enter('network-label', label);
    await tester.testTextInput.receiveAction(TextInputAction.done); await tester.pump();
    if (role == 'et') {
      await choose('network-provider', 'easytier');
      await enter('network-networkName', networkName);
      await enter('network-peers', peerUrl);
    } else {
      await enter('network-controlUrl', controlUrl);
    }
    await tester.testTextInput.receiveAction(TextInputAction.done); await tester.pump();
    await stage('${role}_network_save');
    await existing.tapKey(tester, 'network-save');
    final page = tester.widget<NetworkProfilesPage>(find.byType(NetworkProfilesPage));
    await existing.until(tester, () => page.catalog.networkProfiles.where((profile) => profile.label == label).length == 1);
    final matches = page.catalog.networkProfiles.where((profile) => profile.label == label).toList();
    final profile = matches.single;
    expect(profile.provider, role == 'et' ? 'easytier' : 'tailscale');
    await existing.tap(tester, find.byKey(PageStorageKey('network-details-${profile.id}')));
    await stage('${role}_identity_open');
    final identity = find.byKey(ValueKey('network-identity-${profile.id}'));
    await existing.until(tester, () => identity.evaluate().length == 1 &&
      tester.widget<TextButton>(identity).onPressed != null);
    await existing.tapStablePointer(tester, identity);
    await stage('${role}_identity_load');
    await existing.until(tester, () => find.byKey(const ValueKey('network-identity-absent')).evaluate().length == 1);
    if (role == 'et') {
      await enter('network-identity-secret', networkSecret);
      await tester.testTextInput.receiveAction(TextInputAction.done); await tester.pump();
    }
    await stage('${role}_identity_review');
    final review = await existing.stableReviewCheckbox(tester, 'network-identity-review');
    await tester.tap(review); await tester.pump();
    await stage('${role}_identity_create');
    await existing.tapKey(tester, 'network-identity-create');
    await existing.until(tester, () => find.byKey(const ValueKey('network-identity-present')).evaluate().length == 1);
    await existing.tap(tester, find.text('关闭').last);
    await stage('${role}_node_refresh');
    await existing.tapKey(tester, 'network-node-refresh-${profile.id}');
    await existing.until(tester, () {
      final control = find.byKey(ValueKey('network-node-start-${profile.id}'));
      return control.evaluate().length == 1 && tester.widget<TextButton>(control).onPressed != null;
    });
    await stage('${role}_node_start');
    await existing.tapKey(tester, 'network-node-start-${profile.id}');
    await stage('${role}_node_wait');
    await existing.until(tester, () {
      nodeDiagnostic = readNodeDiagnostic(profile.id);
      // Edit is enabled only after this profile's start and catalog operation
      // have settled; the add control may be outside the lazily built viewport.
      return nodeDiagnostic!['editEnabled'] == true &&
        (role == 'ts' || nodeDiagnostic!['nodeState'] == 'engine_started');
    }, seconds: 90);
    if (role == 'ts') {
      await stage('ts_node_ready_refresh');
      final deadline = DateTime.now().add(const Duration(seconds: 60));
      while (true) {
        nodeDiagnostic = readNodeDiagnostic(profile.id);
        if (nodeDiagnostic!['nodeState'] == 'needs_login') break;
        if (DateTime.now().isAfter(deadline)) throw StateError('dual_node_not_ready');
        await existing.tapKey(tester, 'network-node-refresh-${profile.id}');
        await tester.pump(const Duration(milliseconds: 600));
      }
    }
    return profile.id;
  }

  Future<void> authorizeTailscale(String profileId) async {
    await stage('ts_login_open');
    final open = find.byKey(ValueKey('network-node-login-$profileId'));
    await existing.until(tester, () => open.evaluate().length == 1 &&
      tester.widget<TextButton>(open).onPressed != null);
    await existing.tap(tester, open);
    final review = await existing.stableReviewCheckbox(tester, 'tailscale-login-review');
    await tester.tap(review); await tester.pump();
    await existing.tapKey(tester, 'tailscale-login-authorize');
    final url = find.byKey(const ValueKey('tailscale-login-url'));
    await existing.until(tester, () => url.evaluate().length == 1);
    final raw = tester.widget<SelectableText>(url).data!;
    final parsed = Uri.tryParse(raw);
    if (parsed == null || parsed.scheme != 'https') throw StateError('dual_login_url_invalid');
    existing.publish(exchange, 'ts-url.txt', raw);
    await stage('ts_wait_authorization');
    expect(await awaitFile('ts-authorized.txt'), 'authorized');
    await existing.tapKey(tester, 'tailscale-login-refresh');
    await existing.until(tester, () => find.textContaining('可关闭此页，回到主机列表').evaluate().isNotEmpty);
    await existing.tapKey(tester, 'tailscale-login-close');
  }

  Future<void> navigation(int index) async {
    final bar = find.byType(NavigationBar);
    expect(bar, findsOneWidget);
    final destinations = find.descendant(of: bar, matching: find.byType(NavigationDestination));
    expect(destinations.evaluate().length, 4);
    await existing.tap(tester, destinations.at(index));
  }

  Future<void> showNetworkControls(String networkId) async {
    final page = find.byType(NetworkProfilesPage);
    await existing.until(tester, () => page.evaluate().length == 1);
    final list = find.descendant(of: page, matching: find.byType(ListView)).first;
    final scrollable = find.descendant(of: list, matching: find.byType(Scrollable)).first;
    final tile = find.byKey(PageStorageKey('network-details-$networkId'));
    if (tile.evaluate().isEmpty) {
      for (var i = 0; i < 30 && tester.state<ScrollableState>(scrollable).position.pixels > 0; i++) {
        await tester.drag(scrollable, const Offset(0, 500)); await tester.pump();
      }
      if (tile.evaluate().isEmpty) {
        await tester.scrollUntilVisible(tile, 300, scrollable: scrollable, maxScrolls: 30);
        await tester.pump();
      }
    }
    await existing.until(tester, () => tile.evaluate().length == 1);
    final header = find.descendant(of: tile, matching: find.byType(ListTile)).first;
    await existing.until(tester, () => header.evaluate().length == 1);
    await tester.ensureVisible(header); await tester.pump();
    final controller = ExpansibleController.of(tester.element(header));
    if (!controller.isExpanded) {
      await existing.tapStablePointer(tester, header);
    }
    await existing.until(tester, () => controller.isExpanded &&
      find.byKey(ValueKey('network-node-refresh-$networkId')).evaluate().length == 1);
    await tester.pump(const Duration(milliseconds: 350));
  }

  Future<void> stopNetwork(String role, String networkId) async {
    await stage('${role}_stop_network');
    await navigation(2);
    await existing.until(tester, () => find.byType(NetworkProfilesPage).evaluate().length == 1);
    await showNetworkControls(networkId);
    final refresh = find.byKey(ValueKey('network-node-refresh-$networkId'));
    await existing.until(tester, () => refresh.evaluate().length == 1 && tester.widget<TextButton>(refresh).onPressed != null);
    await existing.tapStablePointer(tester, refresh);
    final stop = find.byKey(ValueKey('network-node-stop-$networkId'));
    await existing.until(tester, () => stop.evaluate().length == 1 && tester.widget<TextButton>(stop).onPressed != null);
    await existing.tapStablePointer(tester, stop);
    final status = find.byKey(ValueKey('network-node-status-$networkId'));
    await existing.until(tester, () => status.evaluate().length == 1 &&
      (tester.widget<Text>(status).data ?? '').contains('已停止'));
  }

  Future<void> bindHost(String hostId, String networkId, String label, String provider) async {
    final role = provider == 'easytier' ? 'et' : 'ts';
    await stage('${role}_bind_open');
    await showHostControl('host-management-$hostId');
    await existing.tapStablePointer(tester, find.byKey(ValueKey('host-management-$hostId')));
    await existing.tapKey(tester, 'host-network-$hostId');
    await choose('host-network-choice', '$label · $provider');
    bindingSelectionMatches = tester.state<FormFieldState<String>>(find.byKey(const ValueKey('host-network-choice'))).value == networkId;
    expect(bindingSelectionMatches, isTrue);
    await stage('${role}_bind_preview');
    await existing.tapKey(tester, 'host-network-preview');
    await stage('${role}_bind_confirm');
    await existing.tapKey(tester, 'host-network-confirm');
    await stage('${role}_bind_save');
    await existing.until(tester, () {
      final home = find.byType(HostCatalogPage);
      if (home.evaluate().length != 1) return false;
      final dynamic state = tester.state(home);
      final catalog = state.catalog as HostCatalog;
      final add = find.byKey(const ValueKey('hosts-add'));
      final addPresent = add.evaluate().length == 1;
      final matches = catalog.profiles.where((host) => host.id == hostId).toList();
      bindingCheck = {'hostPresent': matches.length == 1,
        'hostEnabled': matches.length == 1 && matches.single.enabled,
        'bindingMatches': matches.length == 1 && matches.single.networkProfileId == networkId,
        'catalogReady': catalog.ready, 'catalogWriting': catalog.writing,
        'addPresent': addPresent, 'addEnabled': addPresent && tester.widget<FilledButton>(add).onPressed != null};
      return hostBindingReady(catalog, hostId, networkId);
    });
  }

  Map<String, Object> inspectRemote() {
    final page = find.byType(RemotePage);
    final review = find.byKey(const ValueKey('remote-review'));
    final connect = find.byKey(const ValueKey('remote-connect'));
    final panes = remotePaneChoices();
    final present = page.evaluate().length == 1;
    var busy = false, live = false, dashboardPresent = false, paneCount = 0;
    var boardSelectable = false, paneEnabled = false, paneHit = false, selected = false, selectedMatches = false;
    var statusClass = 'unavailable';
    var adapterPhase = 'unavailable', adapterError = 'none', adapterKind = 'none';
    var channelOpenCode = 0; var snapshotReceived = false;
    var network = 'unknown', hostKey = 'unknown', authentication = 'unknown', dashboard = 'unknown', firstFrame = 'unknown';
    if (present) {
      final dynamic state = tester.state(page);
      busy = state.busy as bool; live = state.live as bool;
      final dynamic board = state.dashboard;
      dashboardPresent = board != null;
      if (dashboardPresent) {
        final int count = board.panes.length as int; paneCount = count > 64 ? 64 : count;
        boardSelectable = board.selectable as bool;
      }
      selected = state.selectedPane != null;
      selectedMatches = selected && expectedPane != null && state.selectedPane == expectedPane &&
        state.selectedTarget?.terminalId == expectedTerminal;
      if (panes.evaluate().length == 1) {
        paneEnabled = tester.widget<FilledButton>(panes).onPressed != null;
        paneHit = panes.hitTestable().evaluate().length == 1;
      }
      final ConnectionDiagnostics? diagnostic = state.connectionDiagnostics as ConnectionDiagnostics?;
      if (diagnostic != null) {
        network = diagnostic.network.name; hostKey = diagnostic.hostKey.name;
        authentication = diagnostic.authentication.name; dashboard = diagnostic.dashboard.name;
        firstFrame = diagnostic.firstFrame.name;
      }
      final evidence = (state.adapter as RemoteReadOnlyAdapter).evidence;
      adapterPhase = evidence.diagnosticPhase; adapterKind = evidence.diagnosticErrorKind;
      const errors = {'host_key_mismatch','authentication_failed','authentication_aborted','timeout',
        'connection_failed','snapshot_rejected','session_mismatch','pane_missing','invalid_response',
        'invalid_snapshot','truncated_response','output_limit','channel_cleanup_timeout','channel_capacity',
        'channel_identity','invalid_terminal_id','unsupported_protocol','network_binding_changed','snapshot_forward_denied'};
      adapterError = evidence.errorCode == null ? 'none' : errors.contains(evidence.errorCode) ? evidence.errorCode! : 'other';
      channelOpenCode = evidence.channelOpenCode; snapshotReceived = evidence.snapshotReceived;
      final String status = state.status as String;
      statusClass = status.contains('主机拒绝会话套接字转发') ? 'snapshot_forward_denied'
        : status.contains('provider_unavailable') ? 'provider_unavailable'
        : status.contains('节点未确认') ? 'network_node_not_started'
        : status.contains('本机网络身份不可用') ? 'network_identity_unavailable'
        : status.contains('节点状态或连接桥不可确认') ? 'network_runtime_unavailable'
        : status.contains('网络绑定已改变') ? 'network_binding_changed'
        : status.contains('设备密钥') ? 'device_key_unavailable'
        : status.contains('主机指纹不符') ? 'host_key_mismatch'
        : status.contains('SSH 认证未通过') ? 'authentication_failed'
        : status.contains('指定会话或目标不匹配') ? 'session_or_target_mismatch'
        : status.contains('超时') ? 'timeout'
        : status.contains('连接或读取失败') ? 'connection_failed'
        : status.contains('正在连接') ? 'connecting' : status.isEmpty ? 'empty' : 'other';
    }
    final rp = review.evaluate().length == 1, cp = connect.evaluate().length == 1;
    return {'pagePresent': present, 'reviewPresent': rp,
      'reviewChecked': rp && tester.widget<CheckboxListTile>(review).value == true,
      'connectPresent': cp, 'connectEnabled': cp && tester.widget<FilledButton>(connect).onPressed != null,
      'busy': busy, 'live': live, 'dashboardPresent': dashboardPresent, 'paneCount': paneCount,
      'paneControlCount': panes.evaluate().length.clamp(0, 64), 'statusClass': statusClass,
      'network': network, 'hostKey': hostKey, 'authentication': authentication,
      'dashboard': dashboard, 'firstFrame': firstFrame, 'adapterPhase': adapterPhase,
      'adapterError': adapterError, 'adapterKind': adapterKind, 'channelOpenCode': channelOpenCode,
      'snapshotReceived': snapshotReceived, 'boardSelectable': boardSelectable, 'paneEnabled': paneEnabled,
      'paneHit': paneHit, 'selectionAttempted': selectionAttempted, 'selected': selected, 'selectedMatches': selectedMatches,
      'terminalPresent': find.byType(TerminalView).evaluate().length == 1,
      'sequencePresent': existing.displayedSequence(tester) != null,
      'markerObserved': currentRemoteRole != null && find.byType(TerminalView).evaluate().length == 1 &&
        existing.screenHasMarker(tester.widget<TerminalView>(find.byType(TerminalView)).terminal, 'Synthetic observe tick')};
  }

  Future<void> selectUniquePane() async {
    final page = find.byType(RemotePage);
    final panes = remotePaneChoices();
    bool ready() {
      if (page.evaluate().length != 1 || panes.evaluate().length != 1) return false;
      final dynamic state = tester.state(page);
      final dynamic board = state.dashboard;
      final adapter = state.adapter as RemoteReadOnlyAdapter;
      if (board == null || !state.busy || !board.selectable || board.generation != adapter.generation ||
          board.panes.length != 1 || state.selectedPane != null || tester.widget<FilledButton>(panes).onPressed == null) return false;
      final pane = board.panes.single;
      return (tester.widget<FilledButton>(panes).key as ValueKey<String>).value == 'remote-pane-${pane.paneId}';
    }
    await existing.until(tester, ready, onTimeout: () { remoteCheck = inspectRemote(); return {}; });
    await tester.ensureVisible(panes); await tester.pump();
    Rect? previous; String? target, terminal; int? generation; var stable = 0;
    await existing.until(tester, () {
      if (!ready() || panes.hitTestable().evaluate().length != 1) { stable = 0; previous = null; return false; }
      final dynamic state = tester.state(page);
      final dynamic board = state.dashboard;
      final String nextTarget = board.panes.single.paneId as String;
      final String nextTerminal = board.panes.single.terminalId as String;
      final int nextGeneration = board.generation as int;
      final bounds = tester.getRect(panes.hitTestable());
      stable = bounds == previous && target == nextTarget && terminal == nextTerminal && generation == nextGeneration ? stable + 1 : 0;
      previous = bounds; target = nextTarget; terminal = nextTerminal; generation = nextGeneration;
      return stable >= 3;
    }, onTimeout: () { remoteCheck = inspectRemote(); return {}; });
    expectedPane = target; expectedTerminal = terminal; selectionAttempted = true;
    await tester.tap(panes.hitTestable()); await tester.pump();
    await existing.until(tester, () {
      if (page.evaluate().length != 1) return false;
      final dynamic state = tester.state(page);
      return state.selectedPane == expectedPane && state.selectedTarget?.terminalId == expectedTerminal &&
        (state.adapter as RemoteReadOnlyAdapter).generation == generation;
    }, onTimeout: () { remoteCheck = inspectRemote(); return {}; });
  }

  HostTabs currentHostTabs() {
    final home = find.byType(HostCatalogPage);
    if (home.evaluate().length != 1) throw StateError('dual_host_page_ambiguous');
    final dynamic state = tester.state(home);
    return state.tabs as HostTabs;
  }

  Set<String> hostTabIds() {
    final tabs = currentHostTabs().tabs;
    final ids = tabs.map((tab) => tab.id).toSet();
    if (ids.length != tabs.length) throw StateError('dual_host_tabs_ambiguous');
    return ids;
  }

  String requireNewActiveHostTab(Set<String> before, String hostId, {bool requireRemote = false}) {
    final tabs = currentHostTabs();
    final current = hostTabIds();
    final added = current.difference(before);
    if (!current.containsAll(before) || added.length != 1) throw StateError('dual_host_tab_change_invalid');
    final id = added.single;
    final matches = tabs.tabs.where((tab) => tab.id == id && tab.hostId == hostId).toList();
    if (matches.length != 1 || tabs.activeId != id || !matches.single.visible.value) {
      throw StateError('dual_host_tab_target_invalid');
    }
    if (requireRemote) {
      final view = find.byKey(ValueKey('host-tab-view-$id'));
      final remote = find.descendant(of: view, matching: find.byType(RemotePage));
      if (view.evaluate().length != 1 || remote.evaluate().length != 1 || find.byType(RemotePage).evaluate().length != 1) {
        throw StateError('dual_host_tab_view_invalid');
      }
      final dynamic home = tester.state(find.byType(HostCatalogPage));
      final catalog = home.catalog as HostCatalog;
      final hosts = catalog.profiles.where((host) => host.id == hostId).toList();
      final target = tester.widget<RemotePage>(remote).pairedTarget;
      if (hosts.length != 1 || target == null ||
          ['host','port','username','session','socketPath','herdrPath','expectedHostKey'].any((key) => target[key] != hosts.single.target[key])) {
        throw StateError('dual_host_tab_target_invalid');
      }
    }
    return id;
  }

  Future<String> openAndObserve(String role, String hostId) async {
    selectionAttempted = false; expectedPane = null; expectedTerminal = null; currentRemoteRole = role;
    await stage('${role}_open_host');
    final previousTabs = hostTabIds();
    await showHostControl('host-open-$hostId');
    await existing.tapStablePointer(tester, find.byKey(ValueKey('host-open-$hostId')));
    await existing.until(tester, () => find.byKey(const ValueKey('pair-connect')).evaluate().length == 1);
    requireNewActiveHostTab(previousTabs, hostId);
    await existing.tapKey(tester, 'pair-connect');
    await existing.until(tester, () => find.byKey(const ValueKey('remote-review')).evaluate().length == 1);
    await stage('${role}_remote_review');
    await existing.tapKey(tester, 'remote-review');
    await stage('${role}_remote_connect');
    final connect = find.byKey(const ValueKey('remote-connect'));
    await existing.until(tester, () => connect.evaluate().length == 1 &&
      tester.widget<FilledButton>(connect).onPressed != null, onTimeout: () { remoteCheck = inspectRemote(); return {}; });
    await existing.tapStablePointer(tester, connect);
    await stage('${role}_remote_pane');
    selectionAttempted = false; expectedPane = null; expectedTerminal = null; currentRemoteRole = role;
    await selectUniquePane();
    await stage('${role}_remote_first_frame');
    await existing.until(tester, () => find.byType(TerminalView).evaluate().length == 1 &&
      find.textContaining('只读观察中').evaluate().isNotEmpty && existing.displayedSequence(tester) != null,
      onTimeout: () { remoteCheck = inspectRemote(); return {}; });
    final firstSequence = existing.displayedSequence(tester)!;
    final terminal = tester.widget<TerminalView>(find.byType(TerminalView)).terminal;
    await stage('${role}_remote_marker');
    await existing.until(tester, () => find.byType(TerminalView).evaluate().length == 1 &&
      identical(tester.widget<TerminalView>(find.byType(TerminalView)).terminal, terminal) &&
      (existing.displayedSequence(tester) ?? -1) > firstSequence &&
      existing.screenHasMarker(terminal, 'Synthetic observe tick'));
    await stage('${role}_remote_tab');
    final tabId = requireNewActiveHostTab(previousTabs, hostId, requireRemote: true);
    return 'host-tab-$tabId';
  }

  Future<void> closeHostTab(String tabKey) async {
    final tab = find.byKey(ValueKey(tabKey));
    expect(tab, findsOneWidget);
    final close = find.byKey(ValueKey(tabKey.replaceFirst('host-tab-', 'host-tab-close-')));
    await existing.tapStablePointer(tester, close);
    await existing.until(tester, () => tab.evaluate().isEmpty && close.evaluate().isEmpty);
  }

  Future<void> resumeTab(String role, String tabKey, Terminal previous) async {
    await stage('${role}_resume');
    await existing.tapKey(tester, tabKey);
    final resume = find.byKey(const ValueKey('remote-resume'));
    await existing.until(tester, () => resume.evaluate().length == 1);
    expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-observe'))).selected, isTrue);
    await existing.tap(tester, resume);
    await existing.until(tester, () => find.byType(TerminalView).evaluate().length == 1 &&
      existing.displayedSequence(tester) != null &&
      !identical(tester.widget<TerminalView>(find.byType(TerminalView)).terminal, previous) &&
      existing.screenHasMarker(tester.widget<TerminalView>(find.byType(TerminalView)).terminal,
        'Synthetic ${role.toUpperCase()} ACK ONE') &&
      find.textContaining('只读观察中').evaluate().isNotEmpty);
    expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-observe'))).selected, isTrue);
  }

  Future<void> tapVisibleTerminal() async {
    final terminal = find.byType(TerminalView);
    await existing.until(tester, () => terminal.evaluate().length == 1);
    await tester.ensureVisible(terminal); await tester.pump();
    final media = MediaQuery.of(tester.element(terminal));
    final viewport = Rect.fromLTWH(0, 0, media.size.width, media.size.height - media.viewInsets.bottom);
    final visible = tester.getRect(terminal).intersect(viewport);
    if (visible.width <= 0 || visible.height <= 0) throw StateError('dual_terminal_not_visible');
    await tester.tapAt(visible.center); await tester.pump();
  }

  Future<void> commitCharacter(String role, String character) async {
    if (!{'et': {'E', 'e'}, 'ts': {'T', 't'}}[role]!.contains(character)) {
      throw StateError('dual_input_invalid');
    }
    final expectedAck = 'Synthetic ${role.toUpperCase()} ACK ${character == character.toUpperCase() ? 'ONE' : 'TWO'}';
    await stage('${role}_input');
    await existing.tapKey(tester, 'remote-mode-direct');
    final terminal = find.byType(TerminalView);
    await tapVisibleTerminal();
    await existing.until(tester, () => tester.widget<TerminalView>(terminal).focusNode!.hasFocus &&
      tester.state<TerminalViewState>(terminal).hasInputConnection);
    final activeTerminal = tester.widget<TerminalView>(terminal).terminal;
    final receipt = find.byKey(const ValueKey('remote-input-receipt'));
    final before = receipt.evaluate().isEmpty ? null : tester.widget<Text>(receipt).data;
    final previous = before == null ? null : RegExp(r'request ([0-9a-f]{32})').firstMatch(before)?.group(1);
    tester.testTextInput.enterText(character);
    await tester.pump();
    await existing.accepted(tester, previousRequest: previous);
    final sequenceAfterReceipt = existing.displayedSequence(tester)!;
    await existing.until(tester, () => find.byType(TerminalView).evaluate().length == 1 &&
      identical(tester.widget<TerminalView>(find.byType(TerminalView)).terminal, activeTerminal) &&
      (existing.displayedSequence(tester) ?? -1) > sequenceAfterReceipt &&
      existing.screenHasMarker(activeTerminal, expectedAck));
  }

  Map<String, Object> inspectResponse(String response) {
    final field = find.byKey(const ValueKey('pair-response'));
    final present = field.evaluate().length == 1;
    final bytes = Uint8List.fromList(utf8.encode(response));
    var category = bytes.length > 2048 ? 'oversize' : 'invalid';
    var skew = 0;
    if (bytes.length <= 2048) {
      final now = diagnosticClock?.call() ?? DateTime.now().millisecondsSinceEpoch ~/ 1000;
      try {
        if (decodePairing(bytes, now)['type'] == 'pairing-binding-response') category = 'valid';
      } catch (_) {
        try {
          final value = jsonDecode(response);
          if (value is Map && value['issued_at'] is int && value['expires_at'] is int) {
            final int issued = value['issued_at'], expires = value['expires_at'];
            if (issued > now && issued - now <= 600) {
              if (decodePairing(bytes, issued)['type'] == 'pairing-binding-response') {
                category = 'future'; skew = issued - now;
              }
            } else if (expires <= now && expires > 0) {
              if (decodePairing(bytes, expires - 1)['type'] == 'pairing-binding-response') category = 'expired';
            }
          }
        } catch (_) { /* Never publish untrusted input or parser errors. */ }
      }
    }
    final recheck = find.byKey(const ValueKey('pair-response-recheck'));
    final source = find.byKey(const ValueKey('pair-source-review'));
    return {'inputMatches': present && tester.widget<TextField>(field).controller?.text == response,
      'recheckPresent': recheck.evaluate().length == 1,
      'recheckEnabled': recheck.evaluate().length == 1 && tester.widget<TextButton>(recheck).onPressed != null,
      'previewPresent': find.byKey(const ValueKey('pair-response-preview')).evaluate().length == 1,
      'sourceChecked': source.evaluate().length == 1 && tester.widget<CheckboxListTile>(source).value == true,
      'fieldPresent': present, 'pagePresent': find.byType(PairingPage).evaluate().length == 1,
      'foreground': WidgetsBinding.instance.lifecycleState == null || WidgetsBinding.instance.lifecycleState == AppLifecycleState.resumed,
      'category': category, 'futureSeconds': skew};
  }

  Future<void> acceptPairResponse(String role, String response, Map<String, dynamic> requestData, String expectedFingerprint) async {
    await stage('${role}_response_enter');
    await enter('pair-response', response);
    await stage('${role}_response_finish_edit');
    await tester.testTextInput.receiveAction(TextInputAction.done); await tester.pump();
    await stage('${role}_response_preview');
    final responsePreview = find.byKey(const ValueKey('pair-response-preview'));
    responseCheck = inspectResponse(response);
    expect(responseCheck!['inputMatches'], isTrue);
    final deadline = DateTime.now().add(const Duration(seconds: 6));
    var polls = 0;
    while (responsePreview.evaluate().isEmpty && polls < 6 &&
        (responseCheck!['category'] == 'valid' ||
         (responseCheck!['category'] == 'future' && (responseCheck!['futureSeconds'] as int) <= 5)) &&
        DateTime.now().isBefore(deadline)) {
      polls++;
      await tester.pump(const Duration(milliseconds: 500));
      final retry = find.byKey(const ValueKey('pair-response-recheck'));
      if (retry.evaluate().length == 1 && tester.widget<TextButton>(retry).onPressed != null) {
        await existing.tapStablePointer(tester, retry);
      }
      responseCheck = inspectResponse(response);
    }
    expect(responsePreview, findsOneWidget);
    final responseText = tester.widget<Text>(responsePreview).data!;
    for (final field in [requestData['request_id'], requestData['account'], expectedFingerprint,
      pairingFingerprint(requestData['public_key'] as String)]) {
      expect(responseText, contains(field.toString()));
    }
    await stage('${role}_response_source');
    final source = await existing.stableReviewCheckbox(tester, 'pair-source-review');
    await tester.tap(source); await tester.pump();
    await stage('${role}_response_accept');
    await existing.tapStablePointer(tester, find.byKey(const ValueKey('pair-accept')));
    await stage('${role}_response_saved');
    await existing.until(tester, () => find.textContaining('authorized-unverified').evaluate().isNotEmpty);
  }

  Future<void> showCatalogAdd() async {
    final add = find.byKey(const ValueKey('hosts-add'));
    if (add.evaluate().isEmpty) {
      final list = find.byKey(const ValueKey('host-catalog-list'));
      final scrollable = find.descendant(of: list, matching: find.byType(Scrollable)).first;
      await tester.scrollUntilVisible(add, -400, scrollable: scrollable, maxScrolls: 30);
      await tester.pump();
    }
    await existing.until(tester, () => add.evaluate().length == 1 &&
      tester.widget<FilledButton>(add).onPressed != null);
    await tester.ensureVisible(add);
    await tester.pump();
  }

  Future<void> showHostControl(String key) async {
    await showCatalogAdd();
    final target = find.byKey(ValueKey(key));
    if (target.evaluate().isEmpty) {
      final list = find.byKey(const ValueKey('host-catalog-list'));
      final scrollable = find.descendant(of: list, matching: find.byType(Scrollable)).first;
      await tester.scrollUntilVisible(target, 400, scrollable: scrollable, maxScrolls: 30);
      await tester.pump();
    }
  }

  Future<void> openPairingFromCatalog({String? routeStage}) async {
    final chooser = find.byKey(const ValueKey('choose-herdr'));
    final pairing = find.byType(PairingPage);
    bool isCurrent(Finder finder) {
      final matches = finder.evaluate();
      return matches.length == 1 && ModalRoute.of(matches.single)?.isCurrent == true;
    }

    await showCatalogAdd();
    await existing.tapStablePointer(tester, find.byKey(const ValueKey('hosts-add')));
    if (routeStage != null) await stage(routeStage);
    await existing.until(tester, () {
      existing.checkPointerError(tester);
      return isCurrent(pairing) || isCurrent(chooser);
    }, seconds: 10);
    if (!isCurrent(pairing)) await existing.tapStablePointer(tester, chooser);
    await existing.until(tester, () {
      existing.checkPointerError(tester);
      return isCurrent(pairing);
    }, seconds: 10);
  }

  Future<String> pairHost(String role, String profileJson, {String? provider}) async {
    if (!{'et', 'ts'}.contains(role)) throw StateError('dual_role_invalid');
    responseReceived = false;
    responseCheck = null;
    await stage('${role}_pair_profile');
    await openPairingFromCatalog(routeStage: '${role}_pair_page');
    final page = tester.widget<PairingPage>(find.byType(PairingPage));
    expect(page.keys, isNull); expect(page.adapter, isNull);
    final before = page.catalog!.profiles.map((profile) => profile.id).toSet();
    final profile = jsonDecode(profileJson) as Map<String, dynamic>;
    final expectedFingerprint = pairingFingerprint(profile['expectedHostKey'] as String);
    expect(profile['provider'], provider ?? (role == 'et' ? 'easytier' : 'tailscale'));
    await stage('${role}_pair_input');
    await enter('profile-input', profileJson);
    await existing.until(tester, () => find.byKey(const ValueKey('profile-preview')).evaluate().length == 1);
    await stage('${role}_pair_preview');
    final preview = tester.widget<SelectableText>(find.byKey(const ValueKey('profile-preview'))).data!;
    expect(preview, contains(expectedFingerprint));
    for (final field in ['host', 'port', 'username', 'session', 'socketPath', 'herdrPath']) {
      expect(preview, contains(profile[field].toString()));
    }
    await stage('${role}_pair_fill');
    await existing.tapKey(tester, 'profile-fill');
    expect(tester.widget<SelectableText>(find.byKey(const ValueKey('pair-target-fingerprint'))).data, expectedFingerprint);
    await tester.testTextInput.receiveAction(TextInputAction.done); await tester.pump();
    await stage('${role}_pair_target_review');
    final review = await existing.stableReviewCheckbox(tester, 'pair-target-review');
    await tester.tap(review); await tester.pump();
    await stage('${role}_pair_create');
    await existing.tapStablePointer(tester, find.byKey(const ValueKey('pair-create')));
    await stage('${role}_pair_request');
    final request = find.byKey(const ValueKey('pair-request'));
    await existing.until(tester, () => request.evaluate().length == 1);
    final requestWire = tester.widget<SelectableText>(request).data!;
    final requestData = jsonDecode(requestWire) as Map<String, dynamic>;
    existing.publish(exchange, '$role-request.json', requestWire);
    await stage('${role}_pair_review');
    final response = await awaitFile('$role-response.json');
    responseReceived = true;
    await acceptPairResponse(role, response, requestData, expectedFingerprint);
    final added = page.catalog!.profiles.where((profile) => !before.contains(profile.id)).toList();
    expect(added.length, 1);
    expect(added.single.requiresNetworkBinding, isTrue);
    return added.single.id;
  }
}
