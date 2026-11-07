import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:terminal_view/terminal_view.dart';
import 'package:herdr_flutter_probe/remote_input.dart' as remoteInput;
import 'remote_input_widget_test.dart' as input;

Future<void> press(WidgetTester tester, String key) async {
  final button = find.byKey(ValueKey(key));
  await tester.ensureVisible(button);
  await tester.tap(button);
  await tester.pumpAndSettle();
}

void main() {
  testWidgets(
    'keyboard controls stay within explicit direct mode and suppress commits while hidden',
    (tester) async {
      final adapter = input.InputFixtureAdapter();
      await input.start(tester, adapter);
      final show = find.byKey(const ValueKey('remote-keyboard-show'));
      final hide = find.byKey(const ValueKey('remote-keyboard-hide'));
      expect(tester.widget<OutlinedButton>(show).onPressed, isNull);
      expect(tester.widget<OutlinedButton>(hide).onPressed, isNull);
      expect(adapter.received, isEmpty);

      await input.mode(tester, 'direct');
      final terminal = tester.widget<TerminalView>(find.byType(TerminalView));
      final focus = terminal.focusNode!;
      expect(focus.hasFocus, isTrue);
      expect(tester.widget<OutlinedButton>(show).onPressed, isNotNull);
      expect(tester.widget<OutlinedButton>(hide).onPressed, isNotNull);
      await press(tester, 'remote-keyboard-show');
      expect(tester.testTextInput.isVisible, isTrue);
      tester.view.viewInsets = const FakeViewPadding(bottom: 300);
      await tester.pump();

      await press(tester, 'remote-keyboard-hide');
      expect(tester.testTextInput.isVisible, isFalse);
      expect(focus.hasFocus, isTrue);
      expect(
        tester
            .widget<ChoiceChip>(
              find.byKey(const ValueKey('remote-mode-observe')),
            )
            .selected,
        isTrue,
      );
      expect(tester.widget<OutlinedButton>(show).onPressed, isNull);
      tester.view.viewInsets = const FakeViewPadding(bottom: 0);
      await tester.pump();
      expect(adapter.received, isEmpty);

      await input.mode(tester, 'direct');
      expect(tester.widget<OutlinedButton>(show).onPressed, isNotNull);
      await press(tester, 'remote-keyboard-show');
      expect(tester.testTextInput.isVisible, isTrue);
      tester.view.viewInsets = const FakeViewPadding(bottom: 300);
      await tester.pump();
      tester.testTextInput.updateEditingValue(
        const TextEditingValue(
          text: 'k',
          selection: TextSelection.collapsed(offset: 1),
          composing: TextRange.empty,
        ),
      );
      await tester.pump();
      expect(adapter.received.map((bytes) => utf8.decode(bytes)), ['k']);
      expect(terminal.autoResize, isFalse);
      tester.view.viewInsets = const FakeViewPadding(bottom: 0);
      await tester.pumpAndSettle();
      expect(
        tester
            .widget<ChoiceChip>(
              find.byKey(const ValueKey('remote-mode-observe')),
            )
            .selected,
        isTrue,
      );
      expect(tester.widget<OutlinedButton>(show).onPressed, isNull);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets('draft keyboard controls preserve local text and never send it', (
    tester,
  ) async {
    final adapter = input.InputFixtureAdapter();
    await input.start(tester, adapter);
    await input.mode(tester, 'draft');
    final field = find.byKey(const ValueKey('remote-input-draft'));
    await tester.ensureVisible(field);
    await tester.enterText(field, 'local draft');
    await tester.pump();
    final controller = tester.widget<TextField>(field).controller!;

    await press(tester, 'remote-keyboard-show');
    expect(tester.testTextInput.isVisible, isTrue);
    await press(tester, 'remote-keyboard-hide');
    expect(tester.testTextInput.isVisible, isFalse);
    expect(controller.text, 'local draft');
    expect(adapter.received, isEmpty);
    expect(
      tester
          .widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-observe')))
          .selected,
      isTrue,
    );
    expect(
      tester
          .widget<OutlinedButton>(
            find.byKey(const ValueKey('remote-keyboard-show')),
          )
          .onPressed,
      isNull,
    );
    expect(
      tester.widget<TerminalView>(find.byType(TerminalView)).autoResize,
      isFalse,
    );
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets(
    'a stale keyboard callback cannot dismiss the next editor connection',
    (tester) async {
      final adapter = input.InputFixtureAdapter();
      await input.start(tester, adapter);
      await input.mode(tester, 'direct');
      final oldHide = tester
          .widget<OutlinedButton>(
            find.byKey(const ValueKey('remote-keyboard-hide')),
          )
          .onPressed!;

      await input.mode(tester, 'draft');
      final field = find.byKey(const ValueKey('remote-input-draft'));
      await tester.ensureVisible(field);
      await tester.showKeyboard(field);
      await tester.pump();
      expect(tester.testTextInput.isVisible, isTrue);
      oldHide();
      await tester.pumpAndSettle();
      expect(tester.testTextInput.isVisible, isTrue);
      expect(adapter.received, isEmpty);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'hiding direct input retires the queued lease before an explicit reopen',
    (tester) async {
      final adapter = input.InputFixtureAdapter()
        ..delayedResult = Completer<remoteInput.RemoteInputResult>();
      await input.start(tester, adapter);
      await input.mode(tester, 'direct');
      tester.view.viewInsets = const FakeViewPadding(bottom: 300);
      await tester.pump();

      tester.testTextInput.updateEditingValue(
        const TextEditingValue(
          text: 'a',
          selection: TextSelection.collapsed(offset: 1),
          composing: TextRange.empty,
        ),
      );
      await tester.pump();
      tester.testTextInput.updateEditingValue(
        const TextEditingValue(
          text: 'ab',
          selection: TextSelection.collapsed(offset: 2),
          composing: TextRange.empty,
        ),
      );
      await tester.pump();
      expect(adapter.received.map((bytes) => utf8.decode(bytes)), ['a']);

      await press(tester, 'remote-keyboard-hide');
      expect(
        tester
            .widget<ChoiceChip>(
              find.byKey(const ValueKey('remote-mode-observe')),
            )
            .selected,
        isTrue,
      );
      tester.view.viewInsets = const FakeViewPadding(bottom: 0);
      await tester.pump();
      adapter.delayedResult!.complete(
        const remoteInput.RemoteInputResult.accepted(),
      );
      await tester.pumpAndSettle();
      expect(adapter.received.map((bytes) => utf8.decode(bytes)), ['a']);

      await input.mode(tester, 'direct');
      await press(tester, 'remote-keyboard-show');
      tester.view.viewInsets = const FakeViewPadding(bottom: 300);
      await tester.pump();
      tester.testTextInput.updateEditingValue(
        const TextEditingValue(
          text: 'k',
          selection: TextSelection.collapsed(offset: 1),
          composing: TextRange.empty,
        ),
      );
      await tester.pump();
      expect(adapter.received.map((bytes) => utf8.decode(bytes)), ['a', 'k']);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );
}
