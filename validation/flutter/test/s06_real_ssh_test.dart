import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;
import 'package:dartssh2/dartssh2.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart' show RenderRepaintBoundary;
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:terminal_view/terminal_view.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/config_transfer.dart';
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
    final importReplace = env['HERDR_S06_IMPORT_REPLACE'] == '1';
    final captureKey = GlobalKey();
    final keys = SplitDeviceKeys([for (final name in ['HERDR_S06_KEY_A', 'HERDR_S06_KEY_B'])
      File(env[name]!).readAsStringSync()]);
    final journals = [GuiSshMemoryInputJournal(), GuiSshMemoryInputJournal()];
    final adapters = [for (final journal in journals) RemoteReadOnlyAdapter(inputJournal: journal)];
    final catalog = HostCatalog(storage: MemoryCatalogStorage()), tabs = HostTabs();
    traceAdapters.addAll(adapters); traceTabs = tabs;
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    var theme = tokens.theme;
    if (importReplace) {
      await tester.runAsync(() async {
        const monoAsset = 'assets/shared/fonts/JetBrainsMonoNerdFontMono-Regular.ttf';
        await (FontLoader('ProbeNerd')..addFont(rootBundle.load(monoAsset))).load();
        await (FontLoader('MaterialIcons')..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'))).load();
        final cjk = env['HERDR_S06_CJK_FONT'];
        if (cjk != null) {
          await (FontLoader('S06Cjk')..addFont(File(cjk).readAsBytes().then(ByteData.sublistView))).load();
          theme = theme.copyWith(textTheme: theme.textTheme.apply(fontFamily: 'S06Cjk'),
            primaryTextTheme: theme.primaryTextTheme.apply(fontFamily: 'S06Cjk'));
        }
      });
    }
    tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(1440, 1000);
    // Live binding keeps an independent 800x600 render surface unless this is
    // set; physicalSize alone changes MediaQuery but not layout constraints.
    await tester.binding.setSurfaceSize(const Size(1440, 1000));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
    addTearDown(() async {
      Object? cleanupError;
      try {
        await tester.runAsync(() async {
          for (final adapter in adapters) {
            try { await adapter.cancel(); }
            catch (error) { cleanupError ??= error; }
          }
        });
      } finally {
        tabs.dispose(); catalog.dispose();
      }
      if (cleanupError != null) throw cleanupError!;
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
    Future<void> confirmCancelled(int side, {File? peerAck}) async {
      var settled = false;
      Object? failure;
      // Join the cancellation already started by the UI. Keep pumping until
      // its local result is known as well as the independent stock peer ACK.
      unawaited(adapters[side].cancel().then<void>((_) { settled = true; },
        onError: (Object error, StackTrace _) { failure = error; settled = true; }));
      await until(() => settled && (failure != null || (peerAck?.existsSync() ?? true)));
      if (failure != null) throw failure!;
    }
    Future<void> capture(String name) async {
      await tester.pump();
      final root = captureKey.currentContext!.findRenderObject()! as RenderRepaintBoundary;
      await tester.runAsync(() async {
        final image = await root.toImage();
        try {
          final png = (await image.toByteData(format: ui.ImageByteFormat.png))!;
          File('${exchange.path}/$name.png').writeAsBytesSync(png.buffer.asUint8List());
        } finally { image.dispose(); }
      });
    }
    stage('s06_homepage');
    await tester.pumpWidget(RepaintBoundary(key: captureKey, child: MaterialApp(theme: theme, home: HostCatalogPage(
      tokens: tokens, catalog: catalog, tabs: tabs, keys: keys,
      adapterFactory: (profile) => adapters[profile.target['session'] == configs[0]['session'] ? 0 : 1],
      offlineBuilder: (_) => const SizedBox()))));
    await tester.pumpAndSettle();
    expect(tester.getSize(find.byType(HostCatalogPage)), const Size(1440, 1000));
    final tabIds = <String>[];
    final chooser = find.byKey(const ValueKey('choose-header'));
    for (var i = 0; i < 2; i++) {
      stage('s06_pair_$i');
      expect(catalog.profiles.length, i);
      await tap('hosts-add'); await tester.pumpAndSettle();
      if (i == 0) {
        // The empty board opens a chooser. The saved board's pairing action
        // opens PairingPage directly.
        expect(chooser, findsOneWidget);
        expect(find.byType(PairingPage), findsNothing);
        await tap('choose-herdr'); await tester.pumpAndSettle();
      }
      final page = find.byType(PairingPage);
      expect(page, findsOneWidget);
      expect(ModalRoute.of(tester.element(page))?.isCurrent, isTrue);
      expect(chooser, findsNothing);
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
    if (importReplace) {
      stage('s06_import_replace');
      final oldProfile = catalog.profiles.singleWhere((p) => p.target['session'] == configs[0]['session']);
      final oldTab = tabs.find(tabIds[0])!, survivor = tabs.find(tabIds[1])!;
      final b = adapters[1], originalBGeneration = adapters[1].generation;
      final aGeneration = adapters[0].generation;
      const password = 'local M1-05 fixture archive';
      final config = catalog.exportConfig({oldProfile.id}, {}, includePreferences:false);
      final archive = (await tester.runAsync(() => encryptPortableConfig(password, config)))!;
      final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
      messenger.setMockMethodCallHandler(NativeConfigDocuments.channel, (call) async {
        expect(call.method, 'open');
        return archive;
      });
      addTearDown(() => messenger.setMockMethodCallHandler(NativeConfigDocuments.channel, null));
      for (final view in views) {
        await tester.ensureVisible(find.descendant(of: view, matching: find.byType(TerminalView)).first);
        await tester.pump();
      }
      await capture('import-before');
      await tap('home-tab-3');
      expect(survivor.visible.value, isTrue);
      expect(survivor.inputEligible.value, isFalse);
      expect(b.inputTarget, same(targets[1]));
      await tap('hosts-transfer');
      await tap('transfer-open');
      final passwordField = find.byKey(const ValueKey('transfer-password'));
      await tester.ensureVisible(passwordField);
      await tester.enterText(passwordField, password);
      await tap('transfer-decrypt');
      final choice = find.byKey(const ValueKey('transfer-choice-0'));
      await until(() => choice.evaluate().isNotEmpty);
      await tester.ensureVisible(choice);
      await tester.pump();
      await tester.tap(find.descendant(of: choice, matching: find.byIcon(Icons.arrow_drop_down)).hitTestable());
      await tester.pumpAndSettle();
      await tester.tap(find.text('替换全部冲突').hitTestable().last);
      await tester.pumpAndSettle();
      expect(find.byKey(ValueKey('transfer-affected-tab-${oldTab.id}')), findsOneWidget);
      expect(find.byKey(ValueKey('transfer-affected-tab-${survivor.id}')), findsNothing);
      await tap('transfer-review');
      await tap('transfer-apply');
      await until(() => catalog.profiles.any((p) => p.id == oldProfile.id && p.retired));
      final replacement = catalog.profiles.singleWhere((p) => p.id != oldProfile.id && p.label == oldProfile.label);
      expect(replacement.hasIdentity, isFalse);
      expect(tabs.tabs, [oldTab, survivor]);
      expect(oldTab.view.value.state, 'retired');
      expect(oldTab.inputEligible.value, isFalse);
      expect(oldTab.retainedScreen?.terminal, same(terminals[0]));
      expect(adapters[0].generation, aGeneration + 1);
      expect(adapters[0].inputTarget, isNull);
      File('${exchange.path}/focused-close-request').createSync(exclusive: true);
      await until(File('${exchange.path}/focused-close-ack').existsSync);
      final bDelta = b.evidence.deltaFrames;
      await until(() => b.evidence.deltaFrames > bDelta);
      expect(b.generation, originalBGeneration);
      expect(b.inputTarget, same(targets[1]));
      expect(b.evidence.connectionCount, 1);
      await tester.pageBack();
      await tester.pumpAndSettle();
      await tap('home-tab-1');
      await until(() => find.byKey(ValueKey('retired-host-view-${oldTab.id}')).evaluate().isNotEmpty);
      final oldTerminal = find.descendant(of: views[0], matching: find.byType(TerminalView));
      expect(tester.widget<TerminalView>(oldTerminal).readOnly, isTrue);
      expect(firstLine(0, markers[0].length), markers[0]);
      expect(terminals[0].onOutput, isNull);
      for (final key in ['pair-connect', 'remote-connect', 'remote-resume', 'remote-mode-direct', 'remote-mode-draft']) {
        expect(find.descendant(of: views[0], matching: find.byKey(ValueKey(key))), findsNothing);
      }
      expect(survivor.inputEligible.value, isTrue);
      final bTerminal = find.descendant(of: views[1], matching: find.byType(TerminalView));
      expect(tester.widget<TerminalView>(bTerminal).terminal, same(terminals[1]));
      terminals[0].textInput('retired-a');
      if (guarded) {
        await tap('remote-mode-direct', owner: views[1]);
        terminals[1].textInput('s'); await tester.pump();
        await until(() => journals[1].prepares == 2 && journals[1].clears == 2);
      }
      for (final terminal in [oldTerminal, bTerminal]) {
        await tester.ensureVisible(terminal);
        await tester.pump();
      }
      await capture('import-after');
      expect(journals[0].prepares, guarded ? 1 : 0);
      await tap('host-tab-close-${oldTab.id}');
      expect(tabs.find(oldTab.id), isNull);
      expect(adapters[0].generation, aGeneration + 1);
      expect(b.generation, originalBGeneration);
      expect(b.inputTarget, same(targets[1]));
    } else if (!guarded) {
      stage('s06_close_focused_tab');
      await tap('workspace-focus-${tabIds[0]}');
      expect(tabs.activeId, tabIds[0]);
      expect(tabs.find(tabIds[0])!.inputEligible.value, isTrue);
      expect(adapters[0].inputTarget, same(targets[0]));
      final peer = tabs.find(tabIds[1])!;
      expect(peer.visible.value, isTrue);
      expect(peer.inputEligible.value, isFalse);
      final b = adapters[1];
      final originalGeneration = b.generation;
      final originalTarget = b.inputTarget!;
      expect(originalTarget, same(targets[1]));
      final aGeneration = adapters[0].generation;
      await tap('host-tab-close-${tabIds[0]}');
      expect(adapters[0].generation, aGeneration + 1);
      expect(tabs.find(tabIds[0]), isNull);
      expect(tabs.splitId, isNull);
      expect(views[0], findsNothing);
      expect(tabs.find(tabIds[1]), same(peer));
      expect(peer.visible.value, isTrue);
      expect(peer.inputEligible.value, isFalse);
      final bTerminal = find.descendant(of: views[1], matching: find.byType(TerminalView));
      expect(tester.widget<TerminalView>(bTerminal).terminal, same(terminals[1]));
      File('${exchange.path}/focused-close-request').createSync();
      // The host acknowledges one closed A peer and the original still-open B
      // before taking a baseline for the next displayed B frame.
      await confirmCancelled(0, peerAck: File('${exchange.path}/focused-close-ack'));
      expect(adapters[0].generation, aGeneration + 1);
      final tickPattern = RegExp(r'^S06 B tick ([0-9]{6})$');
      final buffer = terminals[1].buffer;
      int? visibleTick() {
        const tickRow = 22; // The receiver writes to VT row 23 (one-based).
        if (buffer.viewHeight <= tickRow) return null;
        final row = buffer.lines[buffer.scrollBack + tickRow].getText().trimRight();
        return int.tryParse(tickPattern.firstMatch(row)?.group(1) ?? '');
      }
      await until(() => visibleTick() != null);
      final tick = visibleTick()!;
      final delta = b.evidence.deltaFrames;
      await until(() => b.evidence.deltaFrames > delta && (visibleTick() ?? -1) > tick);
      expect(tester.widget<TerminalView>(bTerminal).terminal, same(terminals[1]));
      expect(b.inputTarget, same(originalTarget));
      expect(b.generation, originalGeneration);
      expect(b.evidence.connectionCount, 1);
      expect(peer.visible.value, isTrue);
      expect(peer.inputEligible.value, isFalse);
      terminals[1].textInput('stock-after-close');
      await tester.pump();
      expect(journals.every((j) => j.prepares == 0), isTrue);
    }
    stage('s06_stop_both');
    if (guarded && !importReplace) {
      for (var side = 0; side < views.length; side++) {
        final beforeStop = adapters[side].generation;
        await tap('remote-cancel', owner: views[side]);
        expect(adapters[side].generation, beforeStop + 1);
        await confirmCancelled(side);
        expect(adapters[side].generation, beforeStop + 1);
      }
    } else {
      final beforeStop = adapters[1].generation;
      final survivor = views[1];
      await tap('remote-cancel', owner: survivor);
      expect(find.descendant(of: survivor, matching: find.byKey(const ValueKey('remote-cancel'))), findsNothing);
      expect(adapters[1].generation, beforeStop + 1);
      stage('s06_confirm_final_close');
      File('${exchange.path}/final-close-request').createSync(exclusive: true);
      await confirmCancelled(1, peerAck: File('${exchange.path}/final-close-ack'));
      expect(adapters[1].generation, beforeStop + 1);
    }
    expect(adapters.every((a) => a.evidence.connectionCount == 1), isTrue);
    expect(tester.takeException(), isNull);
    final result = <String, dynamic>{
      for (final name in ['normalHomepage', 'twoReviewedIdentities', 'samePaneDifferentTerminal',
        'bothVisible', 'independentFrames', 'bothAdvanced', 'singleInputFocus',
        'focusDoesNotRestoreInput', 'lateInputRejected', 'stoppedBoth']) name: true,
      if (!guarded && !importReplace) 'focusedTabClosedPeerAdvanced': true,
      if (!guarded && !importReplace) 'stockPeersClosedBeforeDriverExit': true,
      if (importReplace) 'replacedTabRetainedAndPeerAdvanced': true,
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
