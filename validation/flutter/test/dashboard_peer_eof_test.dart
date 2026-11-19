import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/host_tabs.dart';
import 'package:herdr_flutter_probe/pairing.dart';
import 'package:herdr_flutter_probe/pairing_page.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';

import 'host_catalog_test.dart' show MemoryCatalogStorage;
import 'pairing_gui_test.dart' show authorizedResponse, tapVisible;
import 'remote_test_data.dart';
import 's06_real_ssh_test.dart' show SplitDeviceKeys;

class DashboardPeer {
  DashboardPeer(this.process, this.lines, this.config);
  final Process process;
  final StreamIterator<String> lines;
  final Map<String, dynamic> config;

  static Future<DashboardPeer> start(
    String python, {
    required bool watch,
  }) async {
    final process = await Process.start(python, [
      '-u',
      'test/dashboard_peer_eof_fixture.py',
      watch ? 'watch' : 'one-shot',
    ]);
    final lines = StreamIterator(
      process.stdout.transform(utf8.decoder).transform(const LineSplitter()),
    );
    final errors = process.stderr.drain<void>();
    addTearDown(() async {
      process.kill();
      await lines.cancel();
      await errors;
      await process.exitCode;
    });
    expect(await lines.moveNext().timeout(const Duration(seconds: 5)), isTrue);
    return DashboardPeer(
      process,
      lines,
      jsonDecode(lines.current) as Map<String, dynamic>,
    );
  }

  Future<void> command(String line, String expected) async {
    process.stdin.writeln(line);
    await process.stdin.flush();
    expect(await lines.moveNext().timeout(const Duration(seconds: 5)), isTrue);
    expect(lines.current, expected);
  }

  Future<HostProfile> profile(
    SplitDeviceKeys keys,
    String session,
    String label,
  ) async {
    final handle = await keys.create();
    final target = {
      ...fixtureConfig(),
      'host': '127.0.0.1',
      'port': config['port'],
      'username': 'fixture',
      'expectedHostKey': config['key'],
      'session': session,
      'socketPath':
          '/tmp/fixture-config/herdr/sessions/' + session + '/herdr.sock',
    };
    final pending = PendingDevicePairing(
      handle: handle,
      publicKey: await keys.public(handle),
      account: 'fixture',
      hostKey: pairingFingerprint(config['key'] as String),
      device: 'EOF fixture',
      now: 1000,
    );
    pending.accept(
      jsonEncode(authorizedResponse(pending.request)),
      now: 1000,
      reviewed: true,
    );
    return HostProfile.create(label, target, pending, 1000, provider: 'direct');
  }
}

Future<void> until(
  WidgetTester tester,
  bool Function() complete, {
  int seconds = 8,
}) async {
  final deadline = DateTime.now().add(Duration(seconds: seconds));
  while (!complete() && DateTime.now().isBefore(deadline)) {
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 40)),
    );
    await tester.pump();
  }
}

Future<void> connect(WidgetTester tester, HostProfile profile) async {
  await tapVisible(tester, 'host-open-' + profile.id);
  await tester.pumpAndSettle();
  await tapVisible(tester, 'pair-connect');
  await tester.pumpAndSettle();
  await tapVisible(tester, 'remote-review');
  await tapVisible(tester, 'remote-connect');
}

void main() {
  final python = Platform.environment['HERDR_FIXTURE_PYTHON'];
  if (python != null) {
    LiveTestWidgetsFlutterBinding.ensureInitialized().framePolicy =
        LiveTestWidgetsFlutterBindingFramePolicy.onlyPumps;
  }
  setUp(PairingPage.resetMemorySession);
  tearDown(PairingPage.resetMemorySession);

  for (final dual in [false, true]) {
    testWidgets(
      dual ? 'one peer EOF leaves the other real dashboard watch updating' : 'saved mobile host retains its one-shot snapshot after authenticated peer EOF',
      (tester) async {
        final dead = await DashboardPeer.start(python!, watch: false);
        final live = dual
            ? await DashboardPeer.start(python, watch: true)
            : null;
        final keys = SplitDeviceKeys([
          dead.config['client'] as String,
          if (live != null) live.config['client'] as String,
        ]);
        final a = await dead.profile(keys, 'eof-a', 'EOF fixture');
        final b = await live?.profile(keys, 'eof-b', 'Surviving fixture');
        final catalog = HostCatalog(
          storage: MemoryCatalogStorage(),
          clock: () => 1000,
        );
        await catalog.load();
        await catalog.add(a);
        if (b != null) await catalog.add(b);
        final aAdapter = RemoteReadOnlyAdapter(),
            bAdapter = RemoteReadOnlyAdapter();
        final tabs = HostTabs();
        final tokens = (await tester.runAsync(DesignTokens.load))!;
        final size = dual ? const Size(1440, 1000) : const Size(390, 844);
        tester.view.devicePixelRatio = 1;
        tester.view.physicalSize = size;
        await tester.binding.setSurfaceSize(size);
        addTearDown(() => tester.binding.setSurfaceSize(null));
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        addTearDown(() async {
          await tester.pumpWidget(const SizedBox());
          await aAdapter.cancel();
          await bAdapter.cancel();
          tabs.dispose();
          catalog.dispose();
        });
        await tester.pumpWidget(
          MaterialApp(
            theme: tokens.theme,
            home: HostCatalogPage(
              tokens: tokens,
              catalog: catalog,
              tabs: tabs,
              keys: keys,
              adapterFactory: (profile) =>
                  profile.id == a.id ? aAdapter : bAdapter,
              offlineBuilder: (_) => const SizedBox(),
            ),
          ),
        );
        await tester.pumpAndSettle();

        String? bTab;
        if (b != null) {
          await connect(tester, b);
          await until(
            tester,
            () =>
                bAdapter.currentDashboard?.freshness ==
                DashboardFreshness.fresh,
          );
          expect(
            bAdapter.currentDashboard?.freshness,
            DashboardFreshness.fresh,
          );
          bTab = tabs.active!.id;
          await tapVisible(tester, 'hosts-board-tab');
          await tester.pumpAndSettle();
        }

        await connect(tester, a);
        final aView = find.byKey(ValueKey('host-tab-view-' + tabs.active!.id));
        final aReport = find.descendant(
          of: aView,
          matching: find.byKey(const ValueKey('remote-host-task-summary')),
        );
        String reportA() => tester.widget<Text>(aReport).data!;
        await until(
          tester,
          () => aReport.evaluate().isNotEmpty && reportA().contains('单次快照'),
        );
        expect(aAdapter.evidence.hostKeyMatched, isTrue);
        expect(aAdapter.evidence.authStarted, isTrue);
        expect(aAdapter.evidence.connectionCount, 1);
        expect(
          aAdapter.currentDashboard?.freshness,
          DashboardFreshness.unavailable,
        );
        expect(reportA(), contains('持续更新不可用（单次快照）'));
        expect(reportA(), contains('受阻 1 个'));
        final sync = find.descendant(
          of: aView,
          matching: find.byKey(const ValueKey('remote-dashboard-sync')),
        );
        final pane = find.descendant(
          of: aView,
          matching: find.byKey(const ValueKey('remote-pane-w1:p1')),
        );
        final lastSync = tester.widget<Text>(sync).data;
        expect(lastSync, contains('同步于'));
        expect(tester.widget<FilledButton>(pane).onPressed, isNotNull);
        final aGeneration = aAdapter.generation;

        if (bTab != null) {
          await tapVisible(tester, 'host-split-' + bTab);
          await tapVisible(tester, 'remote-resume');
          await until(
            tester,
            () =>
                bAdapter.currentDashboard?.freshness ==
                DashboardFreshness.fresh,
          );
          expect(
            bAdapter.currentDashboard?.freshness,
            DashboardFreshness.fresh,
          );
          expect(
            bAdapter.currentDashboard?.panes.single.agentStatus,
            'blocked',
          );
        }
        final bGeneration = bAdapter.generation;

        await dead.command('close', 'authenticated-peer-closed');
        await until(tester, () => reportA().contains('上次主机报告'), seconds: 2);
        expect(reportA(), contains('上次主机报告 · 受阻 1 个'));
        expect(tester.widget<Text>(sync).data, lastSync);
        expect(tester.widget<FilledButton>(pane).onPressed, isNull);
        expect(aAdapter.inputTarget, isNull);
        expect(aAdapter.generation, aGeneration);
        expect(aAdapter.evidence.connectionCount, 1);

        if (live != null && bTab != null) {
          await live.command('advance', 'advanced');
          await until(
            tester,
            () =>
                bAdapter.currentDashboard?.panes.single.agentStatus ==
                'working',
          );
          expect(
            bAdapter.currentDashboard?.freshness,
            DashboardFreshness.fresh,
          );
          expect(
            bAdapter.currentDashboard?.panes.single.agentStatus,
            'working',
          );
          final bView = find.byKey(ValueKey('host-tab-view-' + bTab));
          final report = find.descendant(
            of: bView,
            matching: find.byKey(const ValueKey('remote-host-task-summary')),
          );
          await until(
            tester,
            () => tester.widget<Text>(report).data!.contains('主机报告 · 受阻 0 个'),
          );
          expect(tester.widget<Text>(report).data, contains('主机报告 · 受阻 0 个'));
          expect(reportA(), contains('上次主机报告 · 受阻 1 个'));
          expect(bAdapter.generation, bGeneration);
          expect(bAdapter.evidence.connectionCount, 1);
          await live.command('close', 'authenticated-peer-closed');
          await until(
            tester,
            () => tester.widget<Text>(report).data!.contains('上次主机报告'),
            seconds: 2,
          );
          expect(tester.widget<Text>(report).data, contains('上次主机报告 · 受阻 0 个'));
          expect(bAdapter.generation, bGeneration);
        }
      },
      skip: python == null,
    );
  }
}
