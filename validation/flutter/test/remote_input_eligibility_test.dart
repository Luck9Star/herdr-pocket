import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:terminal_view/terminal_view.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'package:herdr_flutter_probe/remote_page.dart';
import 'package:herdr_flutter_probe/remote_input.dart';
import 'remote_input_widget_test.dart' as input;
import 'remote_page_test.dart' as base;

Future<void> start(
  WidgetTester tester,
  input.InputFixtureAdapter adapter,
  ValueNotifier<bool> eligible,
) async {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = const Size(600, 844);
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(tester.view.resetPhysicalSize);
  final tokens = (await tester.runAsync(DesignTokens.load))!;
  await tester.pumpWidget(
    MaterialApp(
      theme: tokens.theme,
      home: RemotePage(
        tokens: tokens,
        adapter: adapter,
        inputEligible: eligible,
      ),
    ),
  );
  await base.fillRemoteFixture(tester);
  for (final name in ['review', 'connect']) {
    await tester.ensureVisible(base.field(name));
    await tester.tap(base.field(name));
    await tester.pump();
  }
  adapter.publish();
  await tester.pump();
  final pane = find.byKey(const ValueKey('remote-pane-w1:p1'));
  await tester.ensureVisible(pane);
  await tester.tap(pane);
  await tester.pump();
  adapter.frame!(
    adapter.generation,
    'w1:p1',
    const RemoteFrame(0, true, 'LIVE'),
  );
  await tester.pump();
}

Future<void> press(WidgetTester tester, String key) async {
  final widget = find.byKey(ValueKey(key));
  await tester.ensureVisible(widget);
  await tester.tap(widget);
  await tester.pump();
}

void main() {
  testWidgets(
    'losing eligibility retires retained callbacks but keeps observing and never restores input automatically',
    (tester) async {
      final eligible = ValueNotifier(true);
      addTearDown(eligible.dispose);
      final adapter = input.InputFixtureAdapter();
      await start(tester, adapter, eligible);
      await input.mode(tester, 'direct');
      final view = tester.widget<TerminalView>(find.byType(TerminalView));
      final oldOutput = view.terminal.onOutput!;
      final oldMode = tester
          .widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-direct')))
          .onSelected!;
      final oldKey = tester
          .widget<OutlinedButton>(find.byKey(const ValueKey('remote-key-Esc')))
          .onPressed!;
      final cancels = adapter.cancels;
      eligible.value = false;
      await tester.pump();
      oldOutput('late IME');
      oldMode(true);
      oldKey();
      await tester.pump();
      expect(adapter.received, isEmpty);
      expect(view.focusNode!.hasFocus, isFalse);
      expect(
        tester.widget<TerminalView>(find.byType(TerminalView)).readOnly,
        isTrue,
      );
      expect(
        find.byKey(const ValueKey('remote-input-ineligible')),
        findsOneWidget,
      );
      adapter.frame!(
        adapter.generation,
        'w1:p1',
        const RemoteFrame(1, false, '\x1b[1;1HLIVE-NONOWNER'),
      );
      await tester.pump();
      expect(view.terminal.buffer.lines[0].getCodePoint(5), 'N'.codeUnitAt(0));
      expect(adapter.calls, 1);
      expect(adapter.cancels, cancels);
      expect(adapter.pauses, 0);
      eligible.value = true;
      await tester.pump();
      oldMode(true);
      oldOutput('after restoration');
      await tester.pump();
      expect(
        tester
            .widget<ChoiceChip>(
              find.byKey(const ValueKey('remote-mode-observe')),
            )
            .selected,
        isTrue,
      );
      expect(adapter.received, isEmpty);
      await input.mode(tester, 'direct');
      tester.widget<TerminalView>(find.byType(TerminalView)).terminal.onOutput!(
        'explicit',
      );
      await tester.pump();
      expect(adapter.received.map(utf8.decode).toList(), ['explicit']);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );
  testWidgets(
    'eligibility loss discards queued bytes while retaining an already accepted write result',
    (tester) async {
      final eligible = ValueNotifier(true);
      addTearDown(eligible.dispose);
      final adapter = input.InputFixtureAdapter()
        ..delayedResult = Completer<RemoteInputResult>();
      await start(tester, adapter, eligible);
      await input.mode(tester, 'direct');
      final output = tester
          .widget<TerminalView>(find.byType(TerminalView))
          .terminal
          .onOutput!;
      output('accepted-before-switch');
      output('queued-must-not-send');
      await tester.pump();
      expect(adapter.received.map(utf8.decode).toList(), [
        'accepted-before-switch',
      ]);
      eligible.value = false;
      await tester.pump();
      adapter.delayedResult!.complete(const RemoteInputResult.accepted());
      await tester.pump();
      eligible.value = true;
      await tester.pump();
      expect(adapter.received.map(utf8.decode).toList(), [
        'accepted-before-switch',
      ]);
      expect(
        tester
            .widget<ChoiceChip>(
              find.byKey(const ValueKey('remote-mode-observe')),
            )
            .selected,
        isTrue,
      );
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );
  testWidgets(
    'losing eligibility removes only its send preview and preserves the local draft',
    (tester) async {
      final eligible = ValueNotifier(true);
      addTearDown(eligible.dispose);
      final adapter = input.InputFixtureAdapter();
      await start(tester, adapter, eligible);
      await input.mode(tester, 'draft');
      final field = find.byKey(const ValueKey('remote-input-draft'));
      await tester.ensureVisible(field);
      await tester.enterText(field, 'do-not-send\nsecond line');
      await tester.pump();
      final controller = tester.widget<TextField>(field).controller!;
      await press(tester, 'remote-input-draft-send');
      final oldConfirm = tester
          .widget<FilledButton>(
            find.byKey(const ValueKey('remote-input-confirm')),
          )
          .onPressed!;
      eligible.value = false;
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('remote-input-confirm')), findsNothing);
      expect(controller.text, 'do-not-send\nsecond line');
      expect(adapter.received, isEmpty);
      eligible.value = true;
      await tester.pump();
      oldConfirm();
      await tester.pump();
      expect(adapter.received, isEmpty);
      await input.mode(tester, 'draft');
      await press(tester, 'remote-input-draft-send');
      oldConfirm();
      await tester.pump();
      expect(
        find.byKey(const ValueKey('remote-input-confirm')),
        findsOneWidget,
      );
      await tester.tap(find.text('取消').last);
      await tester.pumpAndSettle();
      expect(controller.text, 'do-not-send\nsecond line');
      expect(adapter.received, isEmpty);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );
  testWidgets(
    'a pending clipboard result cannot reopen a review after input ownership changes',
    (tester) async {
      final eligible = ValueNotifier(true);
      addTearDown(eligible.dispose);
      final pending = Completer<Object?>();
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform,
        (call) async =>
            call.method == 'Clipboard.getData' ? pending.future : null,
      );
      addTearDown(
        () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
          SystemChannels.platform,
          null,
        ),
      );
      final adapter = input.InputFixtureAdapter();
      await start(tester, adapter, eligible);
      await input.mode(tester, 'direct');
      await press(tester, 'remote-input-paste');
      eligible.value = false;
      await tester.pump();
      eligible.value = true;
      pending.complete({'text': 'late clipboard'});
      await tester.pumpAndSettle();
      expect(
        find.byKey(const ValueKey('remote-paste-review-text')),
        findsNothing,
      );
      expect(adapter.received, isEmpty);
      expect(
        tester
            .widget<ChoiceChip>(
              find.byKey(const ValueKey('remote-mode-observe')),
            )
            .selected,
        isTrue,
      );
      expect(adapter.calls, 1);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );
}
