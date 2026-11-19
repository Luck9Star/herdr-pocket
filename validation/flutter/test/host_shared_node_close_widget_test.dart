import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:terminal_view/terminal_view.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/host_tabs.dart';
import 'package:herdr_flutter_probe/network_identity.dart';
import 'package:herdr_flutter_probe/network_runtime.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'package:herdr_flutter_probe/remote_input.dart';
import 'host_catalog_test.dart' show MemoryCatalogStorage;
import 'host_split_widget_test.dart' show SplitAdapter;
import 'host_tabs_widget_test.dart' show connectTab, tabProfile;
import 'network_profiles_test.dart' show testNetwork;
import 'pairing_gui_test.dart' show TestDeviceKeys, tapVisible;
import 'remote_test_data.dart' show fixtureConfig;

// Only the transport, device identity, and native status are fixtures. The
// workspace, freeze checks, button callbacks, visibility listener and renderer
// are the pinned application's widgets. No socket or native node is opened.
class SharedRouteAdapter extends SplitAdapter {
  SharedRouteAdapter(this.route);
  final String route;
  int gracefulCloses = 0;

  @override
  void requestGracefulClose() { gracefulCloses++; }

  @override
  void selectPane(int expectedGeneration, String paneId) {
    super.selectPane(expectedGeneration, paneId);
    final selected = target!;
    target = RemoteInputTarget(connection: selected.connection, generation: selected.generation,
      host: selected.host, port: selected.port, username: selected.username,
      hostFingerprint: selected.hostFingerprint, session: selected.session, socketPath: selected.socketPath,
      paneId: selected.paneId, terminalId: selected.terminalId, route: route);
  }
}

enum CloseCase {
  stopConnection('stopping A keeps B observing'),
  focused('closing focused A keeps B observing without input'),
  unfocused('closing unfocused A keeps B observing with its existing input eligibility'),
  mobile('closing hidden A in the mobile EasyTier layout keeps B observing'),
  paused('closing A keeps already paused B visible and paused'),
  stashed('closing A does not revive the narrow-window side'),
  hidden('closing A does not revive a hidden B');

  const CloseCase(this.label);
  final String label;
}

void main() {
  for (final scenario in CloseCase.values) {
    testWidgets(scenario.label, (tester) async {
      final mobile = scenario == CloseCase.mobile;
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = mobile ? const Size(390, 844) : const Size(1440, 900);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.view.resetPhysicalSize);
      final previousPlatform = debugDefaultTargetPlatformOverride;
      debugDefaultTargetPlatformOverride = TargetPlatform.android;
      final catalog = HostCatalog(storage: MemoryCatalogStorage(), clock: () => 1000);
      await catalog.load();
      final network = testNetwork(mobile ? 'easytier' : 'tailscale');
      await catalog.addNetwork(network);
      HostProfile host(String name, String address) => tabProfile(name, 'probe$name', address, network.provider, 'opaque-$name')
          .change(networkProfileId: network.id, replaceNetwork: true, now: 1000);
      final a = host('A', '127.0.0.1'), b = host('B', '127.0.0.2');
      await catalog.add(a);
      await catalog.add(b);
      expect(a.id, isNot(b.id));
      expect(a.networkProfileId, b.networkProfileId);
      final identity = {'profileId': network.id, 'provider': network.provider,
        'handle': 'a0000000-0000-4000-8000-000000000001',
        'instanceId': 'b0000000-0000-4000-8000-000000000002', 'mode': mobile ? 'PRIVATE' : 'DEVICE_STATE'};
      final binding = NetworkNodeBinding.forProfile(network, NetworkIdentityRecord.checked(identity, network));
      final route = '${binding.routeProvider}:${binding.profileId}:${binding.profileRevision}:${binding.identityRef}';
      final aAdapter = SharedRouteAdapter(route), bAdapter = SharedRouteAdapter(route);
      final adapters = {a.id: aAdapter, b.id: bAdapter};
      final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
      final statusProfiles = <String>[];
      var stops = 0;
      messenger.setMockMethodCallHandler(NativeNetworkIdentityStore.channel, (call) async {
        expect((call.arguments as Map)['profileId'], network.id);
        return identity;
      });
      messenger.setMockMethodCallHandler(NativeNetworkRuntime.channel, (call) async {
        if (call.method == 'available') return {'available': true, 'reason': null};
        if (call.method == 'nodeStatus') {
          final id = (call.arguments as Map)['profileId'] as String;
          expect(id, network.id);
          statusProfiles.add(id);
          return {'state': mobile ? 'engine-started' : 'running', 'binding': binding.toMap()};
        }
        if (call.method == 'nodeStop') { stops++; return {'state':'stopped', 'binding':null}; }
        throw StateError('Unexpected mock network method ${call.method}');
      });
      final tabs = HostTabs();
      try {
        final tokens = (await tester.runAsync(DesignTokens.load))!;
        final keys = TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
        await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: HostCatalogPage(
          tokens: tokens, catalog: catalog, tabs: tabs, keys: keys,
          overlayAdapterFactory: (p, connector) => adapters[p.id]!, offlineBuilder: (_) => const SizedBox(),
        )));
        await tester.pumpAndSettle();
        for (final p in [a, b]) {
          await tapVisible(tester, 'host-open-${p.id}');
          await tester.pumpAndSettle();
          await tapVisible(tester, 'pair-connect');
          await tester.pumpAndSettle();
          await connectTab(tester, adapters[p.id]!);
          if (p.id == a.id) await tapVisible(tester, 'hosts-board-tab');
        }
        final tabA = tabs.forHost(a.id).single, tabB = tabs.forHost(b.id).single;
        Finder panel(HostTab tab) => find.byKey(ValueKey('host-tab-view-${tab.id}'));
        Finder inside(HostTab tab, Finder target) => find.descendant(of: panel(tab), matching: target);
        Future<void> tap(Finder target) async {
          expect(target, findsOneWidget);
          await tester.ensureVisible(target);
          await tester.tap(target);
          await tester.pump();
        }
        if (mobile) {
          expect(tabA.visible.value, isFalse);
          expect(aAdapter.pauses, 1);
        } else {
          await tapVisible(tester, 'host-split-${tabA.id}');
          await tester.pumpAndSettle();
          await tap(inside(tabA, find.byKey(const ValueKey('remote-resume'))));
          aAdapter.frame!(aAdapter.generation, 'w1:p1', const RemoteFrame(0, true, 'A-LIVE', observationEpoch: 1));
        }
        bAdapter.frame!(bAdapter.generation, 'w1:p1', const RemoteFrame(1, false, '\r\nB-BEFORE'));
        await tester.pump();
        final bFocused = mobile || scenario == CloseCase.unfocused;
        if (!bFocused) {
          await tapVisible(tester, 'workspace-focus-${tabA.id}');
        }
        final terminal = tester.widget<TerminalView>(inside(tabB, find.byType(TerminalView))).terminal;
        expect(terminal.buffer.getText(), contains('B-BEFORE'));
        expect(tabs.active, same(bFocused ? tabB : tabA));
        expect(tabB.visible.value, isTrue);
        expect(tabB.inputEligible.value, bFocused);
        final inputNotice = inside(tabB, find.byKey(const ValueKey('remote-input-ineligible')));
        if (!bFocused) {
          expect(tester.widget<Text>(inputNotice).data, '只读观察 · 获取输入焦点后可选择输入模式');
        }
        expect(bAdapter.pauses, 0);
        expect(aAdapter.calls, 1);
        expect(bAdapter.calls, 1);
        expect(statusProfiles.where((id) => id == network.id).length, greaterThanOrEqualTo(2));
        expect(aAdapter.config.host, isNot(bAdapter.config.host));
        final originalTarget = bAdapter.inputTarget!, connection = bAdapter.connection, generation = bAdapter.generation;
        expect(originalTarget.route, route);
        expect((mobile ? aAdapter.pausedTarget : aAdapter.inputTarget)!.route, route);
        expect(aAdapter.writes, isEmpty);
        expect(bAdapter.writes, isEmpty);
        if (scenario == CloseCase.stashed) {
          tester.view.physicalSize = const Size(1183, 900);
          await tester.pumpAndSettle();
          expect(tabB.layoutHidden.value, isTrue);
        }
        if (scenario == CloseCase.paused || scenario == CloseCase.hidden) {
          await tapVisible(tester, 'workspace-close-split');
          if (scenario == CloseCase.paused) {
            await tapVisible(tester, 'host-split-${tabB.id}');
          }
          await tester.pumpAndSettle();
        }
        final observing = switch (scenario) {
          CloseCase.stopConnection || CloseCase.focused || CloseCase.unfocused || CloseCase.mobile => true,
          _ => false,
        };
        final visible = observing || scenario == CloseCase.paused;
        expect(tabB.visible.value, visible);
        expect(bAdapter.pauses, observing ? 0 : 1);
        expect(bAdapter.resumes, 0);

        final closeTab = scenario != CloseCase.stopConnection;
        if (!closeTab) {
          await tap(inside(tabA, find.byTooltip('停止并断开')));
        } else {
          await tapVisible(tester, 'host-tab-close-${tabA.id}');
        }
        await tester.pumpAndSettle();
        if (scenario == CloseCase.stashed) {
          tester.view.physicalSize = const Size(1440, 900);
          await tester.pumpAndSettle();
          expect(tabB.layoutHidden.value, isFalse);
        }
        expect(tabs.forHost(a.id).isEmpty, closeTab);
        expect(aAdapter.gracefulCloses, closeTab ? 1 : 0);
        expect(aAdapter.cancels, 1);
        expect(tabs.forHost(b.id).single, same(tabB));
        if (closeTab) {
          expect(tabs.active, visible ? same(tabB) : isNull);
          expect(tabs.splitId, isNull);
        }
        expect(tabB.inputEligible.value, bFocused);
        expect(bAdapter.connection, same(connection));
        expect(bAdapter.generation, generation);
        expect(bAdapter.cancels, 0);
        expect(bAdapter.gracefulCloses, 0);
        expect(bAdapter.calls, 1);
        expect(bAdapter.resumes, 0);
        expect(stops, 0);
        bAdapter.frame!(generation, 'w1:p1', const RemoteFrame(2, false, '\r\nB-AFTER'));
        await tester.pump();
        final after = (visible: tabB.visible.value, pauses: bAdapter.pauses,
            sameTarget: identical(originalTarget, bAdapter.inputTarget),
            freshFrame: terminal.buffer.getText().contains('B-AFTER'));
        expect(after, (visible: visible, pauses: observing ? 0 : 1, sameTarget: observing, freshFrame: observing));
        final visibleTerminal = inside(tabB, find.byType(TerminalView));
        if (visible) {
          expect(tester.widget<TerminalView>(visibleTerminal).terminal, same(terminal));
        } else {
          expect(visibleTerminal, findsNothing);
        }
        final resume = inside(tabB, find.byKey(const ValueKey('remote-resume')));
        expect(resume, scenario == CloseCase.paused ? findsOneWidget : findsNothing);
        terminal.textInput('BLOCKED');
        await tester.pump();
        expect(bAdapter.writes, isEmpty);
        if (scenario == CloseCase.focused) {
          expect(tester.widget<Text>(inputNotice).data, '只读观察 · 获取输入焦点后可选择输入模式');
          final direct = inside(tabB, find.byKey(const ValueKey('remote-mode-direct')));
          expect(tester.widget<ChoiceChip>(direct).onSelected, isNull);
          final focus = inside(tabB, find.byKey(ValueKey('workspace-focus-${tabB.id}')));
          expect(find.descendant(of: focus, matching: find.text('B · 观察中 · 获取输入焦点')), findsOneWidget);
          await tap(focus);
          expect(tabB.inputEligible.value, isTrue);
          expect(inputNotice, findsNothing);
          expect(focus, findsNothing);
          expect(bAdapter.inputTarget, same(originalTarget));
          expect(bAdapter.resumes, 0);
          terminal.textInput('STILL OBSERVING');
          await tester.pump();
          expect(bAdapter.writes, isEmpty);
          await tap(direct);
          terminal.textInput('B');
          await tester.pump();
          await tester.pump();
          expect(bAdapter.writes, ['probeB:B']);
        }
        if (scenario == CloseCase.paused) {
          await tapVisible(tester, 'host-tab-${tabB.id}');
          expect(tabB.inputEligible.value, isTrue);
          expect(resume, findsOneWidget);
          expect(bAdapter.resumes, 0);
        }
        expect(aAdapter.writes, isEmpty);
        if (closeTab) {
          await tapVisible(tester, 'host-tab-close-${tabB.id}');
          await tester.pumpAndSettle();
          expect(tabs.tabs, isEmpty);
          expect(aAdapter.gracefulCloses, 1);
          expect(aAdapter.cancels, 1);
          expect(bAdapter.gracefulCloses, 1);
          expect(bAdapter.cancels, 1);
          expect(stops, 0);
        }
        expect(tester.takeException(), isNull);
      } finally {
        await tester.pumpWidget(const SizedBox());
        await tester.pump();
        tabs.dispose();
        catalog.dispose();
        debugDefaultTargetPlatformOverride = previousPlatform;
        messenger.setMockMethodCallHandler(NativeNetworkIdentityStore.channel, null);
        messenger.setMockMethodCallHandler(NativeNetworkRuntime.channel, null);
      }
    });
  }
}
