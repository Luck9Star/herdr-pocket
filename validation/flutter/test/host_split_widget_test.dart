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

bool focusedWithin(WidgetTester tester, Finder finder) {
  final element = tester.element(finder);
  final focused = FocusManager.instance.primaryFocus?.context;
  if (identical(focused, element)) return true;
  var within = false;
  focused?.visitAncestorElements((ancestor) {
    within = identical(ancestor, element);
    return !within;
  });
  return within;
}

Future<void> tabTo(WidgetTester tester, Finder finder) async {
  for (var index = 0; index < 100; index++) {
    if (focusedWithin(tester, finder)) return;
    await tester.sendKeyEvent(LogicalKeyboardKey.tab);
    await tester.pump();
  }
  expect(focusedWithin(tester, finder), isTrue, reason: 'Tab must reach $finder');
}

void main() {
  testWidgets('D2 keeps the focused target and restores the original split after a width change', (tester) async {
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
      final directory = Platform.environment['HERDR_SPLIT_CAPTURE'];
      if (directory == null) return;
      final boundary=tester.renderObject<RenderRepaintBoundary>(find.byKey(const ValueKey('split-capture')));
      await tester.runAsync(() async { final image=await boundary.toImage(pixelRatio: 1);
        final bytes=await image.toByteData(format: ui.ImageByteFormat.png);
        File('$directory/herdr-s06-$name.png').writeAsBytesSync(bytes!.buffer.asUint8List()); image.dispose(); });
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
    final aObserve = find.descendant(of: aView, matching: find.byKey(const ValueKey('remote-mode-observe')));
    await tester.ensureVisible(aObserve); await tester.tap(aObserve); await tester.pump();
    final wideLeft = tester.getRect(bView).left;
    final wideRight = tester.getRect(aView).left;
    expect(wideLeft, lessThan(wideRight));
    final stashed = find.byKey(const ValueKey('workspace-split-stashed'));
    tester.view.physicalSize = const Size(1184, 900); await tester.pumpAndSettle();
    expect(aVisibleTerminal, findsOneWidget); expect(bVisibleTerminal, findsOneWidget);
    expect(find.byKey(ValueKey('host-split-$bId')).hitTestable(), findsOneWidget);
    tester.view.physicalSize = const Size(1183, 900); await tester.pumpAndSettle();
    final criticalSidebarAllowsSplit = find.byKey(ValueKey('host-split-$bId')).evaluate().isNotEmpty;
    final criticalStashed = stashed.evaluate().isNotEmpty;
    await capture('critical');
    tester.view.physicalSize = const Size(700, 900); await tester.pump(); await tester.pump();
    await capture('narrow');
    final narrowStashed = stashed.evaluate().isNotEmpty;
    expect(tabs.activeId, aId);
    expect(tabs.find(aId)!.visible.value, isTrue); expect(tabs.find(bId)!.visible.value, isFalse);
    final retained=find.descendant(of: find.byKey(ValueKey('host-tab-view-$aId')), matching: find.byType(TerminalView));
    expect(retained, findsOneWidget);
    expect(identical(tester.widget<TerminalView>(retained).terminal, aTerminal), isTrue);
    expect(aAdapter.pauses, 1); expect(bAdapter.pauses, 1);
    expect(aAdapter.config.observationCols, 80); expect(aAdapter.config.observationRows, 24);
    expect(bAdapter.config.observationCols, 80); expect(bAdapter.config.observationRows, 24);
    expect(aAdapter.calls, 1); expect(bAdapter.calls, 1);
    tester.view.physicalSize = const Size(1440, 900); await tester.pumpAndSettle();
    await capture('restored');
    expect(
      (criticalSidebarAllowsSplit, bVisibleTerminal.evaluate().isNotEmpty),
      (false, true),
      reason: '1183 cannot offer split; 1440 must restore the previous second pane',
    );
    expect(tester.getRect(bView).left, wideLeft);
    expect(tester.getRect(aView).left, wideRight);
    expect(criticalStashed, isTrue);
    expect(narrowStashed, isTrue);
    expect(stashed, findsNothing);
    expect(tabs.activeId, aId);
    expect(tabs.find(aId)!.inputEligible.value, isTrue);
    expect(tabs.find(bId)!.inputEligible.value, isFalse);
    expect(tester.widget<TerminalView>(bVisibleTerminal).terminal, same(bTerminal));
    expect(bAdapter.resumes, 0);
    expect(bAdapter.calls, 1);
    expect(bTerminal.viewWidth, 80);
    expect(bTerminal.viewHeight, 24);
    final bFocus = find.byKey(ValueKey('workspace-focus-$bId'));
    expect(find.descendant(of: bFocus, matching: find.text('B · 已暂停')), findsOneWidget);
    await tabTo(tester, bFocus);
    await tester.sendKeyDownEvent(LogicalKeyboardKey.shiftLeft);
    await tester.sendKeyEvent(LogicalKeyboardKey.tab);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.shiftLeft);
    await tester.pump();
    expect(focusedWithin(tester, bFocus), isFalse);
    await tester.sendKeyEvent(LogicalKeyboardKey.tab); await tester.pump();
    expect(focusedWithin(tester, bFocus), isTrue);
    await tester.sendKeyEvent(LogicalKeyboardKey.enter); await tester.pump();
    expect(tabs.activeId, bId);
    aTerminal.textInput('late'); await tester.pump();
    bTerminal.textInput('no automatic input'); await tester.pump();
    expect(aAdapter.writes, ['probeA:A']); expect(bAdapter.writes, ['probeB:B']);

    final resumeB = find.descendant(of: bView, matching: find.byKey(const ValueKey('remote-resume')));
    await tester.ensureVisible(resumeB);
    await tester.tap(resumeB);
    await tester.pump();
    expect(bAdapter.resumes, 1);
    bAdapter.frame!(bAdapter.generation, 'w1:p1', const RemoteFrame(0, true, 'OLD FULL'));
    await tester.pump();
    expect(tester.widget<TerminalView>(bVisibleTerminal).terminal, same(bTerminal));
    bAdapter.frame!(bAdapter.generation, 'w1:p1', const RemoteFrame(0, true, 'B RESUMED', observationEpoch: 1));
    await tester.pump();
    final bResumed = tester.widget<TerminalView>(bVisibleTerminal).terminal;
    expect(bResumed.buffer.lines[0].getCodePoint(0), 'B'.codeUnitAt(0));
    expect(bResumed, isNot(same(bTerminal)));
    await tester.ensureVisible(bDirect);
    await tester.tap(bDirect);
    await tester.pumpAndSettle();
    final directFocus = tester.widget<TerminalView>(bVisibleTerminal).focusNode;
    expect(FocusManager.instance.primaryFocus, same(directFocus));

    // The active terminal was explicitly put into direct mode before resizing.
    // Preserve its actual focus while taking the other side out of traversal.
    tester.view.physicalSize = const Size(700, 900); await tester.pumpAndSettle();
    expect(aVisibleTerminal, findsNothing);
    expect(FocusManager.instance.primaryFocus, same(directFocus));
    tester.view.physicalSize = const Size(1440, 900); await tester.pumpAndSettle();
    expect(FocusManager.instance.primaryFocus, same(directFocus));
    expect(aVisibleTerminal, findsOneWidget);
    expect(aAdapter.resumes, 1);
    expect((bResumed.viewWidth, bResumed.viewHeight), (80, 24));
    expect(tester.widget<TerminalView>(bVisibleTerminal).autoResize, isFalse);
    expect(aAdapter.writes, ['probeA:A']); expect(bAdapter.writes, ['probeB:B']);

    tester.view.physicalSize = const Size(700, 900); await tester.pumpAndSettle();
    await tapVisible(tester, 'workspace-close-split');
    expect(stashed, findsNothing);
    tester.view.physicalSize = const Size(1440, 900); await tester.pumpAndSettle();
    expect(aVisibleTerminal, findsNothing);
    expect(bVisibleTerminal, findsOneWidget);
    expect(tabs.activeId, bId);
    expect(aAdapter.calls, 1); expect(bAdapter.calls, 1);
    expect(aAdapter.writes, ['probeA:A']); expect(bAdapter.writes, ['probeB:B']);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox()); tabs.dispose(); catalog.dispose();
  });
}
