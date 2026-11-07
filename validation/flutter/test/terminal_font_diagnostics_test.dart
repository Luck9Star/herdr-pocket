import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:terminal_view/terminal_view.dart';

import 'remote_input_widget_test.dart' as input;

Future<void> press(WidgetTester tester, String key) async {
  final button = find.byKey(ValueKey(key));
  await tester.ensureVisible(button);
  await tester.tap(button);
  await tester.pumpAndSettle();
}

void main() {
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
      final font = FontLoader('ProbeNerd')
        ..addFont(
          rootBundle.load(
            'assets/shared/fonts/JetBrainsMonoNerdFontMono-Regular.ttf',
          ),
        );
      await font.load();

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
        expect(
          find.byKey(const ValueKey('terminal-font-diagnostic-sample-nerd')),
          findsOneWidget,
        );
        expect(find.text('预期 3 列'), findsOneWidget);
        expect(find.text('󰟀'), findsNothing);
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
