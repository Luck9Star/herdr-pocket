import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/main.dart';
import 'package:terminal_view/terminal_view.dart';

const captureKey = ValueKey('v2-capture');

Future<void> mount(WidgetTester tester, Size size, {double keyboard = 0, double scale = 1}) async {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = size;
  tester.view.viewInsets = FakeViewPadding(bottom: keyboard);
  // Font loading crosses the real engine/asset I/O boundary; it must run
  // outside testWidgets' fake clock, as in the existing painter regressions.
  final (tokens, fixture, load) = (await tester.runAsync(() async {
    final font = FontLoader('ProbeNerd')..addFont(rootBundle.load(
      'assets/shared/fonts/JetBrainsMonoNerdFontMono-Regular.ttf'));
    await font.load();
    final tokens = await DesignTokens.load();
    final fixture = jsonDecode(await rootBundle.loadString('assets/shared/fixture.json')) as Map<String, dynamic>;
    final load = await rootBundle.loadString('assets/shared/load-chunk.txt');
    return (tokens, fixture, load);
  }))!;
  await tester.pumpWidget(RepaintBoundary(key: captureKey, child: MaterialApp(
    debugShowCheckedModeBanner: false, theme: tokens.theme,
    builder: (context, child) => MediaQuery(data: MediaQuery.of(context).copyWith(
      textScaler: TextScaler.linear(scale)), child: child!),
    home: ProbePage(fixture: fixture, load: load, tokens: tokens),
  )));
  await tester.pumpAndSettle();
}

Future<void> saveView(WidgetTester tester, String name) async {
  final boundary = tester.renderObject<RenderRepaintBoundary>(find.byKey(captureKey));
  await tester.runAsync(() async {
    final image = await boundary.toImage(pixelRatio: 1);
    final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
    final directory = Directory('probe-results/ui-v2')..createSync(recursive: true);
    File('${directory.path}/$name.png').writeAsBytesSync(bytes!.buffer.asUint8List());
    image.dispose();
  });
}

Finder keyed(String key) => find.byKey(ValueKey(key));
ChoiceChip mode(WidgetTester tester, String name) => tester.widget<ChoiceChip>(keyed('mode-$name'));
String count(WidgetTester tester) => tester.widget<Text>(keyed('input-count')).data!;

void main() {
  testWidgets('unknown result keeps input locked after refresh until explicit acknowledgement', (tester) async {
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetViewInsets);
    await mount(tester, const Size(390, 844));
    await tester.tap(keyed('mode-direct')); await tester.pumpAndSettle();
    await tester.tap(find.text('Esc')); await tester.pump();
    expect(count(tester), contains('本地接收 1'));
    await tester.tap(keyed('diagnostics')); await tester.pumpAndSettle();
    await tester.tap(keyed('inject-unknown')); await tester.pumpAndSettle();
    expect(mode(tester, 'direct').onSelected, isNull);
    expect(mode(tester, 'draft').onSelected, isNull);
    await saveView(tester, 'mobile-unknown');
    await tester.tap(keyed('restore-full')); await tester.pumpAndSettle();
    expect(mode(tester, 'direct').onSelected, isNull);
    expect(count(tester), contains('本地接收 1'));
    await tester.tap(keyed('acknowledge-unknown')); await tester.pumpAndSettle();
    expect(mode(tester, 'observe').selected, isTrue);
    expect(count(tester), contains('本地接收 1'));
    await tester.tap(keyed('mode-direct')); await tester.pumpAndSettle();
    await tester.tap(find.text('Esc')); await tester.pump();
    expect(count(tester), contains('本地接收 2'));
    expect(tester.takeException(), isNull);
  });

  testWidgets('hidden mobile tab requires a new full; narrow layout keeps one visible target', (tester) async {
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetViewInsets);
    await mount(tester, const Size(1440, 900));
    await tester.tap(keyed('split-toggle')); await tester.pumpAndSettle();
    expect(find.byType(TerminalPane), findsNWidgets(2));
    await saveView(tester, 'desktop-split');
    tester.view.physicalSize = const Size(390, 844);
    await tester.pumpAndSettle();
    expect(find.byType(TerminalPane), findsOneWidget);
    await tester.tap(keyed('tab-1')); await tester.pumpAndSettle();
    expect(mode(tester, 'direct').onSelected, isNull);
    await tester.tap(keyed('restore-full')); await tester.pumpAndSettle();
    await tester.tap(keyed('mode-direct')); await tester.pumpAndSettle();
    await tester.tap(find.text('Esc')); await tester.pump();
    expect(count(tester), contains('本地接收 1'));
    await tester.tap(keyed('tab-0')); await tester.pumpAndSettle();
    expect(mode(tester, 'direct').onSelected, isNull);
    expect(count(tester), contains('本地接收 0'));
    expect(tester.takeException(), isNull);
  });

  testWidgets('small mobile keyboard and enlarged UI do not overflow or resize terminal', (tester) async {
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetViewInsets);
    await mount(tester, const Size(320, 640), keyboard: 260, scale: 1.3);
    await tester.tap(keyed('mode-draft')); await tester.pumpAndSettle();
    final terminals = tester.widgetList<TerminalPane>(find.byType(TerminalPane));
    expect(terminals.length, 1);
    final view = tester.widget<TerminalView>(find.byType(TerminalView));
    expect(view.autoResize, isFalse);
    expect(view.terminal.viewWidth, 80);
    expect(view.terminal.viewHeight, 24);
    await tester.ensureVisible(find.text('预览发送'));
    await tester.pumpAndSettle();
    expect(find.text('预览发送').hitTestable(), findsOneWidget);
    expect(tester.takeException(), isNull);
    await saveView(tester, 'small-mobile-keyboard-draft');
  });

  testWidgets('v2 mobile observation screenshot uses the shared fixture and font', (tester) async {
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetViewInsets);
    await mount(tester, const Size(390, 844));
    await saveView(tester, 'mobile-observe');
    expect(tester.takeException(), isNull);
  });
}
