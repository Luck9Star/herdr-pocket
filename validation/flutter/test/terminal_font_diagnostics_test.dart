import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:terminal_view/terminal_view.dart';

import 'remote_input_widget_test.dart' as input;

Future<void> press(WidgetTester tester, String key) async {
  final opening = key == 'remote-font-diagnostics-open';
  final button = find.byKey(ValueKey(key));
  await tester.ensureVisible(button);
  // Scroll may trigger a rebuild and invalidate target/epoch-bound callbacks.
  await tester.pump();
  expect(button.hitTestable(), findsOneWidget,
      reason: '$key must be visible and receive the pointer after scrolling');
  if (opening) {
    expect(tester.widget<OutlinedButton>(button).onPressed, isNotNull,
        reason: 'diagnostics guard must allow this live observation');
  } else {
    expect(tester.widget<TextButton>(button).onPressed, isNotNull);
  }
  await tester.tap(button);
  await tester.pump();
  final panel = find.byKey(const ValueKey('terminal-font-diagnostics'));
  if (!opening) {
    expect(panel, findsNothing, reason: 'close must unmount diagnostics');
    return;
  }
  expect(panel, findsOneWidget,
      reason: 'the pointer reached the button but diagnostics did not open; check its target/epoch guard');
  // The suite loaded the asset on the engine clock. Give its queued callbacks
  // one real event turn, then paint the result on the widget test clock.
  await tester.runAsync(() => Future<void>.delayed(Duration.zero));
  await tester.pump();
  final error = find.byKey(const ValueKey('terminal-font-diagnostics-error'));
  final loading = find.byKey(const ValueKey('terminal-font-diagnostics-loading'));
  final errorText = error.evaluate().isEmpty ? null : tester.widget<Text>(error).data;
  expect(error, findsNothing, reason: 'diagnostics panel opened but fixture parsing or terminal creation failed: $errorText');
  expect(loading, findsNothing, reason: 'diagnostics panel opened but its asset future has not completed');
  expect(find.byKey(const ValueKey('terminal-font-diagnostics-view')), findsOneWidget,
      reason: 'diagnostics loaded without an error but the local terminal is absent');
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late List<Map<String, dynamic>> samples;
  setUpAll(() async {
    final fixture = jsonDecode(await rootBundle.loadString(
      'assets/shared/terminal-font-diagnostics-v1.json',
    )) as Map<String, dynamic>;
    samples = (fixture['samples'] as List).cast<Map<String, dynamic>>();
    final font = FontLoader('ProbeNerd')
      ..addFont(rootBundle.load('assets/shared/fonts/JetBrainsMonoNerdFontMono-Regular.ttf'));
    await font.load();
  });

  testWidgets(
    'opening diagnostics from direct mode retires input and closing remains observe-only',
    (tester) async {
      final adapter = input.InputFixtureAdapter();
      await input.start(tester, adapter);
      await input.mode(tester, 'direct');
      final calls = adapter.calls;
      final generation = adapter.generation;

      await press(tester, 'remote-font-diagnostics-open');
      expect(
        tester
            .widget<ChoiceChip>(
              find.byKey(const ValueKey('remote-mode-observe')),
            )
            .selected,
        isTrue,
      );
      final diagnosticView = tester.widget<TerminalView>(
        find.byKey(const ValueKey('terminal-font-diagnostics-view')),
      );
      expect(diagnosticView.readOnly, isTrue);
      expect(diagnosticView.autoResize, isFalse);
      await tester.sendKeyEvent(LogicalKeyboardKey.keyX, character: 'x');
      await tester.pump();
      expect(adapter.received, isEmpty);
      expect(adapter.calls, calls);
      expect(adapter.generation, generation);

      await press(tester, 'terminal-font-diagnostics-close');
      expect(
        tester
            .widget<ChoiceChip>(
              find.byKey(const ValueKey('remote-mode-observe')),
            )
            .selected,
        isTrue,
      );
      await tester.sendKeyEvent(LogicalKeyboardKey.keyX, character: 'x');
      await tester.pump();
      expect(adapter.received, isEmpty);
      expect(adapter.calls, calls);
      expect(adapter.generation, generation);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'stock observe connection without input capability can open diagnostics but cannot send',
    (tester) async {
      final adapter = input.InputFixtureAdapter(supported: false);
      await input.start(tester, adapter);
      final calls = adapter.calls;
      final generation = adapter.generation;

      final openButton = tester.widget<OutlinedButton>(
        find.byKey(const ValueKey('remote-font-diagnostics-open')),
      );
      expect(openButton.onPressed, isNotNull);
      expect(
        tester
            .widget<ChoiceChip>(
              find.byKey(const ValueKey('remote-mode-direct')),
            )
            .onSelected,
        isNull,
      );

      await press(tester, 'remote-font-diagnostics-open');
      expect(
        tester
            .widget<TerminalView>(
              find.byKey(const ValueKey('terminal-font-diagnostics-view')),
            )
            .readOnly,
        isTrue,
      );
      await tester.sendKeyEvent(LogicalKeyboardKey.keyX, character: 'x');
      await tester.pump();
      expect(adapter.received, isEmpty);
      expect(adapter.calls, calls);
      expect(adapter.generation, generation);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'local font diagnostics is read-only, aligned to shared samples, and preserves the draft at 320 px',
    (tester) async {
      for (final width in [320.0, 390.0]) {
        final adapter = input.InputFixtureAdapter();
        await input.start(tester, adapter, width: width);
        await input.mode(tester, 'draft');
        final draftField = find.byKey(const ValueKey('remote-input-draft'));
        await tester.ensureVisible(draftField);
        await tester.enterText(draftField, 'keep this draft');
        await tester.pump();
        final draftController = tester
            .widget<TextField>(draftField)
            .controller!;
        final calls = adapter.calls;
        final generation = adapter.generation;

        await press(tester, 'remote-font-diagnostics-open');
        expect(draftController.text, 'keep this draft');
        expect(
          tester
              .widget<ChoiceChip>(
                find.byKey(const ValueKey('remote-mode-observe')),
              )
              .selected,
          isTrue,
        );
        expect(
          find.byKey(const ValueKey('terminal-font-diagnostics')),
          findsOneWidget,
        );
        expect(
          find.byKey(const ValueKey('terminal-font-diagnostics-font')),
          findsOneWidget,
        );
        expect(
          find.textContaining('JetBrainsMono Nerd Font Mono'),
          findsOneWidget,
        );
        expect(find.textContaining('右侧竖线应落在第 15 列'), findsOneWidget);
        expect(find.textContaining('不含行号、标记竖线和补齐空格'), findsOneWidget);
        expect(find.textContaining('不能识别系统实际选用的 fallback'), findsOneWidget);
        expect(find.textContaining('无图标纯文本 prompt'), findsOneWidget);
        for (var index = 0; index < samples.length; index++) {
          final sample = samples[index];
          final label = find.byKey(ValueKey(
            'terminal-font-diagnostic-sample-${sample['id']}',
          ));
          expect(label, findsOneWidget);
          expect(tester.widget<Text>(label).data, '${index + 1}. ${sample['label']}');
          // Distinct samples can legitimately have the same cell count. Bind
          // the legend to its sample row instead of assuming page-wide text
          // uniqueness, including when glyphs repeat in the terminal preview.
          final row = find.ancestor(of: label, matching: find.byType(Wrap));
          expect(row, findsOneWidget);
          expect(
            find.descendant(of: row, matching: find.text('预期 ${sample['cells']} 列')),
            findsOneWidget,
          );
        }
        final nerd = samples.singleWhere((sample) => sample['id'] == 'nerd');
        expect(
          find.descendant(
            of: find.byKey(const ValueKey('terminal-font-diagnostics')),
            matching: find.text(nerd['text'] as String),
          ),
          findsNothing,
        );
        expect(
          find.bySemanticsLabel('独立本地只读终端样例，16 列 8 行。按字符样例对照竖线边界与预期单元格数。'),
          findsOneWidget,
        );
        final localView = tester.widget<TerminalView>(
          find.byKey(const ValueKey('terminal-font-diagnostics-view')),
        );
        expect(localView.readOnly, isTrue);
        expect(localView.autoResize, isFalse);
        expect(localView.hardwareKeyboardOnly, isTrue);
        expect(localView.textStyle.fontFamily, 'ProbeNerd');
        expect(localView.textStyle.fontSize, 14);
        final sample = localView.terminal;
        expect(sample.viewWidth, 16);
        expect(sample.viewHeight, 8);
        for (var row = 0; row < sample.viewHeight; row++) {
          final line = sample.buffer.lines[row];
          expect(line.getCodePoint(0), 0x31 + row);
          expect(line.getCodePoint(14), 0x7c, reason: 'sample row ${row + 1}');
        }
        expect(adapter.received, isEmpty);
        expect(adapter.calls, calls);
        expect(adapter.generation, generation);
        expect(tester.takeException(), isNull);

        await press(tester, 'terminal-font-diagnostics-close');
        expect(
          find.byKey(const ValueKey('terminal-font-diagnostics')),
          findsNothing,
        );
        expect(
          tester
              .widget<ChoiceChip>(
                find.byKey(const ValueKey('remote-mode-observe')),
              )
              .selected,
          isTrue,
        );
        expect(
          tester
              .widget<SelectableText>(
                find.byKey(const ValueKey('remote-unsent-text-0')),
              )
              .data,
          'keep this draft',
        );
        expect(adapter.received, isEmpty);
        expect(adapter.calls, calls);
        expect(adapter.generation, generation);
        await tester.pumpWidget(const SizedBox());
      }
    },
  );
}
