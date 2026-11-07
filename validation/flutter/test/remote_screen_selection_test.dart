import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:terminal_view/terminal_view.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'package:herdr_flutter_probe/remote_page.dart';
import 'remote_input_widget_test.dart' as input;
import 'remote_page_test.dart' as base;

const openKey = ValueKey('remote-screen-select');
const textKey = ValueKey('remote-screen-selection-text');
const copyKey = ValueKey('remote-screen-selection-copy');
const cancelKey = ValueKey('remote-screen-selection-cancel');

Future<void> openSelection(WidgetTester tester) async {
  final open = find.byKey(openKey);
  await tester.ensureVisible(open); await tester.pump();
  final inner = find.descendant(of:find.byType(TerminalView),matching:find.byType(Scrollable)).first;
  tester.state<ScrollableState>(inner).position.jumpTo(0); await tester.pump();
  await tester.tap(open); await tester.pump();
}

void main() {
  for (final width in [320.0,390.0]) {
    testWidgets('read-only selection at $width uses native text and copies only explicit selection', (tester) async {
      final copies = <String>[];
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform,(call) async {
        if (call.method == 'Clipboard.setData') copies.add((call.arguments as Map)['text'] as String);
        return null;
      });
      addTearDown(() => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform,null));
      final adapter = input.InputFixtureAdapter(supported:false);
      await input.start(tester,adapter,width:width);
      final terminal = tester.widget<TerminalView>(find.byType(TerminalView)).terminal;
      for (var row = 1; row <= 24; row++) { terminal.write('\x1b[${row};1H\x1b[2K  中e\u0301👩\u200d💻  '); }
      await tester.pump();
      final columns = terminal.viewWidth,rows = terminal.viewHeight;
      await openSelection(tester);
      final field = tester.widget<TextField>(find.byKey(textKey));
      expect(field.readOnly,isTrue); expect(field.enableInteractiveSelection,isTrue);
      expect(field.keyboardType,TextInputType.none);
      final controller = field.controller!;
      expect(controller.text,contains('中e\u0301👩\u200d💻  '));
      expect(controller.selection.isCollapsed,isTrue); expect(copies,isEmpty);
      expect(tester.widget<FilledButton>(find.byKey(copyKey)).onPressed,isNull);
      final start = controller.text.indexOf('中e\u0301');
      expect(start,greaterThanOrEqualTo(0));
      controller.selection = TextSelection(baseOffset:start,extentOffset:start + 3); await tester.pump();
      await tester.ensureVisible(find.byKey(copyKey)); await tester.tap(find.byKey(copyKey)); await tester.pump();
      expect(copies,['中e\u0301']); expect(adapter.received,isEmpty);
      expect(terminal.viewWidth,columns); expect(terminal.viewHeight,rows);
      await tester.ensureVisible(find.byKey(cancelKey)); await tester.tap(find.byKey(cancelKey)); await tester.pump();
      expect(controller.text,isEmpty); expect(find.byKey(textKey),findsNothing);
      expect(copies.length,1); expect(adapter.received,isEmpty);
      expect(tester.takeException(),isNull);
      await tester.pumpWidget(const SizedBox());
    });
  }

  testWidgets('opening from direct mode revokes old callbacks and closing never restores input', (tester) async {
    final adapter = input.InputFixtureAdapter(); await input.start(tester,adapter); await input.mode(tester,'direct');
    final view = tester.widget<TerminalView>(find.byType(TerminalView)),oldOutput = tester.widget<TerminalView>(find.byType(TerminalView)).terminal.onOutput!;
    final oldMode = tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-direct'))).onSelected!;
    await openSelection(tester); oldOutput('late IME'); oldMode(true); await tester.pump();
    expect(adapter.received,isEmpty); expect(find.byType(TerminalView),findsNothing);
    expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-observe'))).selected,isTrue);
    await tester.ensureVisible(find.byKey(cancelKey)); await tester.tap(find.byKey(cancelKey)); await tester.pump();
    expect(tester.widget<TerminalView>(find.byType(TerminalView)).readOnly,isTrue);
    expect(view.focusNode!.hasFocus,isFalse); oldOutput('late after close'); await tester.pump();
    expect(adapter.received,isEmpty); await tester.pumpWidget(const SizedBox());
  });

  testWidgets('hidden tab clears text and stale copy, does not reopen after a fresh epoch', (tester) async {
    final visible = ValueNotifier(true); addTearDown(visible.dispose);
    final copies = <String>[];
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform,(call) async {
      if (call.method == 'Clipboard.setData') copies.add((call.arguments as Map)['text'] as String);
      return null;
    });
    addTearDown(() => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform,null));
    final adapter = input.InputFixtureAdapter(); await input.start(tester,adapter,visibility:visible);
    await openSelection(tester);
    final controller = tester.widget<TextField>(find.byKey(textKey)).controller!;
    controller.selection = const TextSelection(baseOffset:0,extentOffset:3); await tester.pump();
    final oldCopy = tester.widget<FilledButton>(find.byKey(copyKey)).onPressed!;
    visible.value = false; await tester.pump(); oldCopy(); await tester.pump();
    expect(controller.text,isEmpty); expect(find.byKey(textKey),findsNothing); expect(copies,isEmpty);
    visible.value = true; await tester.pump();
    await tester.ensureVisible(base.field('resume')); await tester.tap(base.field('resume')); await tester.pump();
    adapter.frame!(adapter.generation,'w1:p1',const RemoteFrame(0,true,'NEW EPOCH',observationEpoch:1)); await tester.pump();
    expect(find.byKey(textKey),findsNothing); expect(adapter.received,isEmpty);
    expect(tester.widget<TerminalView>(find.byType(TerminalView)).readOnly,isTrue);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('delta keeps the frozen page; full replacement and observation end clear it', (tester) async {
    final adapter = input.InputFixtureAdapter(); await input.start(tester,adapter); await openSelection(tester);
    final controller = tester.widget<TextField>(find.byKey(textKey)).controller!,original = tester.widget<TextField>(find.byKey(textKey)).controller!.text;
    adapter.frame!(adapter.generation,'w1:p1',const RemoteFrame(1,false,'DELTA')); await tester.pump();
    expect(controller.text,original);
    adapter.frame!(adapter.generation,'w1:p1',const RemoteFrame(2,true,'\x1b[3;6HREPLACEMENT')); await tester.pump();
    expect(controller.text,isEmpty); expect(find.byKey(textKey),findsNothing);
    await openSelection(tester);
    expect(controller.text,contains('REPLACEMENT'));
    adapter.pending.complete(const RemoteSnapshot(1,'probe','w1:p1','IGNORED')); await tester.pump();
    expect(controller.text,isEmpty); expect(find.byKey(textKey),findsNothing); expect(adapter.received,isEmpty);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('lifecycle stop clears selectable content and invalidates a retained open callback', (tester) async {
    final adapter = input.InputFixtureAdapter(); await input.start(tester,adapter);
    final oldOpen = tester.widget<OutlinedButton>(find.byKey(openKey)).onPressed!;
    await openSelection(tester); final controller = tester.widget<TextField>(find.byKey(textKey)).controller!;
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive); await tester.pump();
    oldOpen(); await tester.pump();
    expect(controller.text,isEmpty); expect(find.byKey(textKey),findsNothing); expect(adapter.received,isEmpty);
    base.restoreResumedLifecycle(tester); await tester.pumpWidget(const SizedBox());
  });

  testWidgets('reusing the page for another requested terminal clears the old selection', (tester) async {
    final copies = <String>[];
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform,(call) async {
      if (call.method == 'Clipboard.setData') copies.add((call.arguments as Map)['text'] as String);
      return null;
    });
    addTearDown(() => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform,null));
    final adapter = input.InputFixtureAdapter(); await input.start(tester,adapter); await openSelection(tester);
    final controller = tester.widget<TextField>(find.byKey(textKey)).controller!;
    controller.selection = const TextSelection(baseOffset:0,extentOffset:3); await tester.pump();
    final staleCopy = tester.widget<FilledButton>(find.byKey(copyKey)).onPressed!;
    final page = tester.widget<RemotePage>(find.byType(RemotePage));
    await tester.pumpWidget(MaterialApp(theme:page.tokens.theme,home:RemotePage(tokens:page.tokens,
      adapter:adapter,requestedTarget:const RemotePane('w1:p2','term_1234'))));
    staleCopy(); await tester.pump();
    expect(controller.text,isEmpty); expect(find.byKey(textKey),findsNothing);
    expect(copies,isEmpty); expect(adapter.received,isEmpty);
    await tester.pumpWidget(const SizedBox());
  });
}
