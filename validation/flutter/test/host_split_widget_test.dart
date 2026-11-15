import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:terminal_view/terminal_view.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/host_tabs.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'package:herdr_flutter_probe/remote_input.dart';
import 'host_catalog_test.dart' show MemoryCatalogStorage;
import 'host_tabs_widget_test.dart' show TabFixtureAdapter, tabProfile, connectTab;
import 'pairing_gui_test.dart' show TestDeviceKeys, tapVisible;
import 'remote_test_data.dart';

class SplitAdapter extends TabFixtureAdapter {
  final writes = <String>[];
  @override
  Future<RemoteInputResult> sendInput(RemoteInputTarget target, Uint8List bytes,
      {bool Function()? stillCurrent}) async {
    if (stillCurrent?.call() != true || !identical(target, inputTarget)) {
      return const RemoteInputResult.rejected('input_cancelled_before_write');
    }
    writes.add('${target.session}:${String.fromCharCodes(bytes)}');
    return const RemoteInputResult.accepted();
  }
}

void main() {
  testWidgets('two saved targets observe independently; focus and narrow layout revoke only the other side', (tester) async {
    tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(1440, 900);
    addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
    final catalog = HostCatalog(storage: MemoryCatalogStorage(), clock: () => 1000); await catalog.load();
    final a = tabProfile('A', 'probeA', '127.0.0.1', 'direct', 'fixture-a');
    final b = tabProfile('B', 'probeB', '127.0.0.2', 'direct', 'fixture-b');
    await catalog.add(a); await catalog.add(b);
    final tabs = HostTabs(), adapters = <String, SplitAdapter>{};
    final tokens = (await tester.runAsync(() async {
      final fontFile=File('/System/Library/Fonts/Supplemental/Arial Unicode.ttf');
      if (fontFile.existsSync()) { final font=FontLoader('SplitChinese')..addFont(fontFile.readAsBytes().then((bytes) => ByteData.view(bytes.buffer))); await font.load(); }
      final terminalFont=FontLoader('ProbeNerd')..addFont(rootBundle.load('assets/shared/fonts/JetBrainsMonoNerdFontMono-Regular.ttf')); await terminalFont.load();
      final icons=FontLoader('MaterialIcons')..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf')); await icons.load();
      return DesignTokens.load();
    }))!;
    final keys = TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
    await tester.pumpWidget(RepaintBoundary(key: const ValueKey('split-capture'), child: MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: tokens.theme.copyWith(textTheme: tokens.theme.textTheme.apply(fontFamily: 'SplitChinese'),
        appBarTheme: tokens.theme.appBarTheme.copyWith(titleTextStyle: tokens.theme.appBarTheme.titleTextStyle?.copyWith(fontFamily: 'SplitChinese')),
        chipTheme: tokens.theme.chipTheme.copyWith(labelStyle: TextStyle(fontFamily: 'SplitChinese', color: tokens.color('textPrimary')))),
      home: HostCatalogPage(tokens: tokens, catalog: catalog, tabs: tabs,
      keys: keys, adapterFactory: (p) => adapters[p.id] = SplitAdapter(), offlineBuilder: (_) => const SizedBox()))));
    Future<void> capture(String name) async {
      if (!Platform.environment.containsKey('HERDR_SPLIT_CAPTURE')) return;
      final boundary=tester.renderObject<RenderRepaintBoundary>(find.byKey(const ValueKey('split-capture')));
      await tester.runAsync(() async { final image=await boundary.toImage(pixelRatio: 1);
        final bytes=await image.toByteData(format: ui.ImageByteFormat.png);
        File('/tmp/herdr-s06-$name.png').writeAsBytesSync(bytes!.buffer.asUint8List()); image.dispose(); });
    }
    await tester.pumpAndSettle();
    await tapVisible(tester, 'host-open-${a.id}'); await tester.pumpAndSettle();
    final aId = tabs.active!.id, aAdapter = adapters[a.id]!;
    await tapVisible(tester, 'pair-connect'); await tester.pumpAndSettle(); await connectTab(tester, aAdapter);
    await tapVisible(tester, 'hosts-board-tab');
    await tapVisible(tester, 'host-open-${b.id}'); await tester.pumpAndSettle();
    final bId = tabs.active!.id, bAdapter = adapters[b.id]!;
    await tapVisible(tester, 'pair-connect'); await tester.pumpAndSettle(); await connectTab(tester, bAdapter);
    expect(aAdapter.pauses, 1);
    await tapVisible(tester, 'host-split-$aId'); await tester.pumpAndSettle();
    final aView = find.byKey(ValueKey('host-tab-view-$aId'));
    final bView = find.byKey(ValueKey('host-tab-view-$bId'));
    expect(find.descendant(of: aView, matching: find.byType(TerminalView)), findsOneWidget);
    expect(find.descendant(of: bView, matching: find.byType(TerminalView)), findsOneWidget);
    expect(tabs.find(aId)!.visible.value, isTrue); expect(tabs.find(bId)!.visible.value, isTrue);
    expect(tabs.find(aId)!.inputEligible.value, isFalse); expect(tabs.find(bId)!.inputEligible.value, isTrue);
    Color frameColor(String id) => ((tester.widget<DecoratedBox>(find.byKey(ValueKey('workspace-frame-$id'))).decoration as BoxDecoration).border! as Border).top.color;
    expect(frameColor(bId), tokens.color('brand')); expect(frameColor(aId), Colors.transparent);
    final resumeA = find.descendant(of: aView, matching: find.byKey(const ValueKey('remote-resume')));
    await tester.ensureVisible(resumeA); await tester.tap(resumeA); await tester.pump();
    expect(aAdapter.resumes, 1);
    aAdapter.frame!(aAdapter.generation, 'w1:p1', const RemoteFrame(0, true, 'A NEW FULL\r\n\$ git status --short\r\n M src/main.rs\r\n\$ cargo check\r\n    Finished dev profile', observationEpoch: 1));
    bAdapter.frame!(bAdapter.generation, 'w1:p1', const RemoteFrame(1, false, 'B LIVE\r\n\$ cargo test\r\ntest result: ok. 42 passed\r\n\$ git status\r\nworking tree clean'));
    await tester.pump();
    final aTerminal = tester.widget<TerminalView>(find.descendant(of: aView, matching: find.byType(TerminalView))).terminal;
    final bTerminal = tester.widget<TerminalView>(find.descendant(of: bView, matching: find.byType(TerminalView))).terminal;
    expect(aTerminal.buffer.lines[0].getCodePoint(0), 'A'.codeUnitAt(0));
    expect(bTerminal.buffer.lines[0].getCodePoint(0), 'S'.codeUnitAt(0));
    final aVisibleTerminal = find.descendant(of: aView, matching: find.byType(TerminalView));
    final bVisibleTerminal = find.descendant(of: bView, matching: find.byType(TerminalView));
    for (final view in [aView, bView]) {
      final slider=find.descendant(of: view, matching: find.byKey(const ValueKey('remote-vertical-slider')));
      tester.widget<Slider>(slider).onChanged?.call(0);
    }
    await tester.ensureVisible(aVisibleTerminal); await tester.ensureVisible(bVisibleTerminal); await tester.pump();
    expect(aVisibleTerminal.hitTestable(), findsOneWidget); expect(bVisibleTerminal.hitTestable(), findsOneWidget);
    await capture('wide');
    final bDirect=find.descendant(of: bView, matching: find.byKey(const ValueKey('remote-mode-direct')));
    await tester.ensureVisible(bDirect); await tester.tap(bDirect); await tester.pump();
    bTerminal.textInput('B'); await tester.pump(); await tester.pump();
    expect(bAdapter.writes, ['probeB:B']); expect(aAdapter.writes, isEmpty);
    final aFocus = find.byKey(ValueKey('workspace-focus-$aId'));
    await tester.ensureVisible(aFocus); await tester.tap(aFocus); await tester.pump();
    expect(tabs.find(aId)!.inputEligible.value, isTrue); expect(tabs.find(bId)!.inputEligible.value, isFalse);
    expect(frameColor(aId), tokens.color('brand')); expect(frameColor(bId), Colors.transparent);
    bTerminal.textInput('late'); await tester.pump();
    expect(bAdapter.writes, ['probeB:B']); expect(aAdapter.writes, isEmpty);
    final aDirect=find.descendant(of: aView, matching: find.byKey(const ValueKey('remote-mode-direct')));
    await tester.ensureVisible(aDirect); await tester.tap(aDirect); await tester.pump();
    aTerminal.textInput('A'); await tester.pump(); await tester.pump();
    expect(aAdapter.writes, ['probeA:A']); expect(bAdapter.writes, ['probeB:B']);
    expect(aAdapter.pauses, 1); expect(bAdapter.pauses, 0);
    final bFocus = find.byKey(ValueKey('workspace-focus-$bId'));
    final focusChild = find.descendant(of: bFocus, matching: find.byType(Text)).first;
    Focus.of(tester.element(focusChild)).requestFocus(); await tester.pump();
    await tester.sendKeyEvent(LogicalKeyboardKey.enter); await tester.pump();
    expect(tabs.activeId, bId);
    aTerminal.textInput('late'); await tester.pump();
    expect(aAdapter.writes, ['probeA:A']); expect(bAdapter.writes, ['probeB:B']);
    await tester.tap(aFocus); await tester.pump();
    tester.view.physicalSize = const Size(700, 900); await tester.pump(); await tester.pump();
    await capture('narrow');
    expect(tabs.activeId, aId); expect(tabs.splitId, isNull);
    expect(tabs.find(aId)!.visible.value, isTrue); expect(tabs.find(bId)!.visible.value, isFalse);
    final retained=find.descendant(of: find.byKey(ValueKey('host-tab-view-$aId')), matching: find.byType(TerminalView));
    expect(retained, findsOneWidget);
    expect(identical(tester.widget<TerminalView>(retained).terminal, aTerminal), isTrue);
    expect(aAdapter.pauses, 1); expect(bAdapter.pauses, 1);
    expect(aAdapter.config.observationCols, 80); expect(aAdapter.config.observationRows, 24);
    expect(bAdapter.config.observationCols, 80); expect(bAdapter.config.observationRows, 24);
    expect(aAdapter.calls, 1); expect(bAdapter.calls, 1);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox()); tabs.dispose(); catalog.dispose();
  });
}
