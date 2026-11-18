import 'dart:convert';
import 'dart:io';
import 'package:dartssh2/dartssh2.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:terminal_view/terminal_view.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/device_keys.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/host_tabs.dart';
import 'package:herdr_flutter_probe/pairing_page.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'package:herdr_flutter_probe/remote_input.dart';
import 'host_catalog_test.dart' show MemoryCatalogStorage;
import 'pairing_gui_test.dart' as pairing;
import 'pairing_gui_ssh_test.dart' show GuiSshMemoryInputJournal;

// Explicit temporary test signers. No native keystore, imported production
// identity, transport double, frame injection or safety override is selected.
class SplitDeviceKeys implements DeviceKeys {
  SplitDeviceKeys(List<String> pem) : keys = pem.map((p) => SSHKeyPair.fromPem(p).single).toList();
  final List<SSHKeyPair> keys;
  int creates = 0;
  final signs = [0, 0];
  int index(String handle) => int.parse(handle.substring('s06-test-'.length));
  @override Future<String> create() async => 's06-test-${creates++}';
  @override Future<String> public(String handle) async =>
    'ssh-ed25519 ${base64Encode(keys[index(handle)].toPublicKey().encode())}';
  @override Future<Uint8List> sign(String handle, Uint8List payload) async {
    final i = index(handle); signs[i]++;
    return Uint8List.fromList(keys[i].sign(payload).encode().sublist(19));
  }
  @override Future<void> delete(String handle) async {}
}

void main() {
  final env = Platform.environment;
  final enabled = env.containsKey('HERDR_S06_CONFIG');
  if (enabled) {
    LiveTestWidgetsFlutterBinding.ensureInitialized().framePolicy =
      LiveTestWidgetsFlutterBindingFramePolicy.onlyPumps;
  }
  setUp(PairingPage.resetMemorySession);
  tearDown(PairingPage.resetMemorySession);
  testWidgets('S06 two reviewed real SSH/herdr sessions keep frames and input targets independent', (tester) async {
    final traceAdapters = <RemoteReadOnlyAdapter>[];
    HostTabs? traceTabs;
    try {
    final configs = (jsonDecode(File(env['HERDR_S06_CONFIG']!).readAsStringSync()) as List)
      .cast<Map<String, dynamic>>();
    final exchange = Directory(env['HERDR_S06_DIR']!);
    final guarded = env['HERDR_S06_GUARDED'] == '1';
    final keys = SplitDeviceKeys([for (final name in ['HERDR_S06_KEY_A', 'HERDR_S06_KEY_B'])
      File(env[name]!).readAsStringSync()]);
    final journals = [GuiSshMemoryInputJournal(), GuiSshMemoryInputJournal()];
    final adapters = [for (final journal in journals) RemoteReadOnlyAdapter(inputJournal: journal)];
    final catalog = HostCatalog(storage: MemoryCatalogStorage()), tabs = HostTabs();
    traceAdapters.addAll(adapters); traceTabs = tabs;
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(1440, 1000);
    // Live binding keeps an independent 800x600 render surface unless this is
    // set; physicalSize alone changes MediaQuery but not layout constraints.
    await tester.binding.setSurfaceSize(const Size(1440, 1000));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
    addTearDown(() async {
      await tester.runAsync(() async { for (final adapter in adapters) { await adapter.cancel(); } });
      tabs.dispose(); catalog.dispose();
    });
    void stage(String value) => File('${exchange.path}/stage').writeAsStringSync(value, flush: true);
    Future<void> until(bool Function() check) async {
      final end = DateTime.now().add(const Duration(seconds: 35));
      while (!check()) {
        if (DateTime.now().isAfter(end)) fail('s06 bounded phase timeout');
        await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
        await tester.pump();
      }
    }
    Future<void> tap(String key, {Finder? owner}) async {
      final all = find.byKey(ValueKey(key));
      final control = owner == null ? all : find.descendant(of: owner, matching: all);
      await until(() => control.evaluate().isNotEmpty);
      await tester.ensureVisible(control.first); await tester.pump();
      final hit = control.hitTestable();
      expect(hit, findsOneWidget);
      await tester.tap(hit); await tester.pump();
    }
    stage('s06_homepage');
    await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: HostCatalogPage(
      tokens: tokens, catalog: catalog, tabs: tabs, keys: keys,
      adapterFactory: (profile) => adapters[profile.target['session'] == configs[0]['session'] ? 0 : 1],
      offlineBuilder: (_) => const SizedBox())));
    await tester.pumpAndSettle();
    expect(tester.getSize(find.byType(HostCatalogPage)), const Size(1440, 1000));
    final tabIds = <String>[];
    for (var i = 0; i < 2; i++) {
      stage('s06_pair_$i');
      await tap('hosts-add'); await tester.pumpAndSettle();
      await pairing.fillPairTarget(tester, configs[i]);
      await tap('pair-target-review'); await tap('pair-create');
      final request = find.byKey(const ValueKey('pair-request'));
      await until(() => request.evaluate().isNotEmpty && catalog.profiles.length == i + 1);
      final pending = File('${exchange.path}/request-$i.new');
      pending.writeAsStringSync(tester.widget<SelectableText>(request).data!, flush: true);
      pending.renameSync('${exchange.path}/request-$i.json');
      final response = File('${exchange.path}/response-$i.json');
      await until(response.existsSync);
      final profile = catalog.profiles.singleWhere((p) => p.target['session'] == configs[i]['session']);
      await tester.pageBack(); await tester.pumpAndSettle();
      await tap('host-open-${profile.id}'); await tester.pumpAndSettle();
      await pairing.acceptResponse(tester, jsonDecode(response.readAsStringSync()) as Map<String, dynamic>);
      await tap('pair-connect'); await tester.pumpAndSettle();
      stage('s06_connect_$i');
      await tap('remote-review'); await tap('remote-connect');
      await until(() => adapters[i].currentDashboard?.panes.isNotEmpty == true);
      stage('s06_select_$i');
      await until(() {
        final pane = find.byKey(ValueKey('remote-pane-${configs[i]['paneId']}'));
        return pane.evaluate().isNotEmpty && tester.widget<FilledButton>(pane.first).onPressed != null;
      });
      await tap('remote-pane-${configs[i]['paneId']}');
      stage('s06_frames_$i');
      await until(() => adapters[i].evidence.fullFrameReceived && adapters[i].evidence.deltaFrames > 0);
      expect(adapters[i].runtimeType, RemoteReadOnlyAdapter);
      expect(adapters[i].evidence.hostKeyMatched, isTrue);
      expect(adapters[i].evidence.connectionCount, 1);
      tabIds.add(tabs.active!.id);
      if (i == 0) { await tap('hosts-board-tab'); await tester.pump(); }
    }
    expect(keys.creates, 2); expect(keys.signs.every((n) => n > 0), isTrue);
    expect(configs[0]['paneId'], configs[1]['paneId']);
    expect(adapters[0].inputTarget, isNull); // Hidden A is paused, not reconnected.
    stage('s06_split_resume');
    expect(tabs.activeId, tabIds[1]);
    await tap('host-split-${tabIds[0]}'); await tester.pump();
    expect(tabs.activeId, tabIds[1]); expect(tabs.splitId, tabIds[0]);
    expect(tabs.find(tabIds[0])!.visible.value, isTrue);
    expect(tabs.find(tabIds[1])!.visible.value, isTrue);
    final views = [for (final id in tabIds) find.byKey(ValueKey('host-tab-view-$id'))];
    await tap('remote-resume', owner: views[0]);
    await until(() => adapters.every((a) => a.evidence.fullFrameReceived && a.inputTarget != null));
    final targets = adapters.map((a) => a.inputTarget!).toList();
    expect(targets[0].terminalId, isNot(targets[1].terminalId));
    expect(targets[0].session, isNot(targets[1].session));
    final terminals = [for (final view in views)
      tester.widget<TerminalView>(find.descendant(of: view, matching: find.byType(TerminalView))).terminal];
    final markers = ['herdr-pocket / same fixture v1', 'herdr-pocket / S06 peer B'];
    String firstLine(int side, int length) => String.fromCharCodes(List.generate(length,
      (i) => terminals[side].buffer.lines[0].getCodePoint(i)));
    for (var i = 0; i < 2; i++) {
      expect(firstLine(i, markers[i].length), markers[i]);
      expect(tabs.find(tabIds[i])!.visible.value, isTrue);
    }
    expect(identical(terminals[0], terminals[1]), isFalse);
    final before = adapters.map((a) => a.evidence.deltaFrames).toList();
    await until(() => adapters[0].evidence.deltaFrames > before[0] && adapters[1].evidence.deltaFrames > before[1]);
    expect(tabs.find(tabIds[0])!.inputEligible.value, isFalse);
    expect(tabs.find(tabIds[1])!.inputEligible.value, isTrue);
    stage('s06_input_eligibility');
    if (guarded) {
      await tap('remote-mode-direct', owner: views[1]);
      terminals[1].textInput('b'); await tester.pump();
      await until(() => journals[1].prepares == 1 && journals[1].clears == 1);
    } else {
      for (final view in views) {
        for (final key in ['remote-mode-direct', 'remote-mode-draft']) {
          expect(tester.widget<ChoiceChip>(find.descendant(of: view,
            matching: find.byKey(ValueKey(key)))).onSelected, isNull);
        }
      }
    }
    await tap('workspace-focus-${tabIds[0]}');
    expect(tabs.find(tabIds[0])!.inputEligible.value, isTrue);
    expect(tabs.find(tabIds[1])!.inputEligible.value, isFalse);
    terminals[1].textInput('late-b'); terminals[0].textInput('before-explicit-mode');
    await tester.pump();
    for (final view in views) {
      expect(tester.widget<ChoiceChip>(find.descendant(of: view,
        matching: find.byKey(const ValueKey('remote-mode-observe')))).selected, isTrue);
    }
    if (guarded) {
      await tap('remote-mode-draft', owner: views[0]);
      final draft = find.descendant(of: views[0], matching: find.byKey(const ValueKey('remote-input-draft')));
      await tester.ensureVisible(draft); await tester.enterText(draft, 'Pocket测'); await tester.pump();
      await tap('remote-input-draft-send', owner: views[0]);
      await tap('remote-input-confirm');
      await until(() => journals[0].prepares == 1 && journals[0].clears == 1);
      for (var i = 0; i < 2; i++) {
        final marker = RemoteInputPending.parse(journals[i].lastPrepared!);
        expect(marker.target.session, targets[i].session);
        expect(marker.target.terminalId, targets[i].terminalId);
      }
    } else {
      terminals[0].textInput('stock-a'); terminals[1].textInput('stock-b'); await tester.pump();
      expect(journals.every((j) => j.prepares == 0), isTrue);
    }
    await tap('workspace-focus-${tabIds[1]}');
    terminals[0].textInput('late-a'); terminals[1].textInput('no-auto-restore'); await tester.pump();
    expect(journals.every((j) => j.prepares == (guarded ? 1 : 0)), isTrue);
    final after = adapters.map((a) => a.evidence.deltaFrames).toList();
    await until(() => adapters[0].evidence.deltaFrames > after[0] && adapters[1].evidence.deltaFrames > after[1]);
    stage('s06_stop_both');
    for (final view in views) { await tap('remote-cancel', owner: view); }
    expect(adapters.every((a) => a.evidence.connectionCount == 1), isTrue);
    expect(tester.takeException(), isNull);
    final result = <String, dynamic>{
      for (final name in ['normalHomepage', 'twoReviewedIdentities', 'samePaneDifferentTerminal',
        'bothVisible', 'independentFrames', 'bothAdvanced', 'singleInputFocus',
        'focusDoesNotRestoreInput', 'lateInputRejected', 'stoppedBoth']) name: true,
      'sides': [for (final adapter in adapters) {'connectionCount': adapter.evidence.connectionCount,
        'frameCount': adapter.evidence.frameCount, 'deltaFrames': adapter.evidence.deltaFrames,
        'inputAccepted': guarded}],
    };
    File('${exchange.path}/result.json').writeAsStringSync(jsonEncode(result), flush: true);
    await tester.pumpWidget(const SizedBox());
    } catch (error, stack) {
      // Publish locations only, never exception messages, targets or key data.
      final locations = RegExp(r's06_real_ssh_test\.dart:\d+:\d+').allMatches(stack.toString())
        .map((m) => m.group(0)!).take(4).toList();
      const knownErrors = {'channel_cleanup_timeout', 'observe_ended', 'cancelled',
        'watch_retry_exhausted', 'connection_failed', 'session_mismatch', 'resume_target_changed', 'timeout'};
      File('${env['HERDR_S06_DIR']!}/failure.json').writeAsStringSync(jsonEncode({
        'kind': error.runtimeType.toString(), 'locations': locations,
        'splitActive': traceTabs?.splitId != null,
        'visibleTabs': traceTabs?.tabs.where((t) => t.visible.value).length ?? 0,
        'resumeOnstage': find.byKey(const ValueKey('remote-resume')).evaluate().length,
        'resumeAnywhere': find.byKey(const ValueKey('remote-resume'), skipOffstage: false).evaluate().length,
        'peers': [for (final a in traceAdapters) {'connectionCount': a.evidence.connectionCount,
          'frameCount': a.evidence.frameCount, 'deltaFrames': a.evidence.deltaFrames,
          'phase': a.evidence.observationPhase,
          'error': a.evidence.errorCode == null ? 'none' : knownErrors.contains(a.evidence.errorCode)
            ? a.evidence.errorCode : 'other_public_failure',
          'observationCloseFailed': a.evidence.channelRetireFailures.contains('observation')}],
      }), flush: true);
      rethrow;
    }
  }, skip: !enabled, timeout: const Timeout(Duration(minutes: 4)));
}
