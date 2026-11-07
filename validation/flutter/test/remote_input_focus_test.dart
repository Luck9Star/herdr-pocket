import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:terminal_view/terminal_view.dart';
import 'remote_input_widget_test.dart' as input;

void main() {
  for (final width in [320.0,390.0]) {
    testWidgets('reselecting active draft mode preserves the composing editor and focus at ${width}px',(tester) async {
      final adapter = input.InputFixtureAdapter(); await input.start(tester,adapter,width:width);
      await input.mode(tester,'draft');
      final field = find.byKey(const ValueKey('remote-input-draft'));
      await tester.ensureVisible(field); await tester.showKeyboard(field);
      const composing = TextEditingValue(text:'中文',selection:TextSelection.collapsed(offset:2),
        composing:TextRange(start:0,end:2));
      tester.testTextInput.updateEditingValue(composing); await tester.pump();
      final originalEditor = tester.element(field);
      final controller = tester.widget<TextField>(field).controller!;
      final editable = find.descendant(of:field,matching:find.byType(EditableText));
      final focus = tester.widget<EditableText>(editable).focusNode;
      expect(focus.hasFocus,isTrue); expect(controller.value,composing);

      // Use the real selected chip, whose onSelected receives false. A second
      // tap must not create a new input epoch or replace the editing client.
      await input.mode(tester,'draft');
      expect(identical(tester.element(field),originalEditor),isTrue);
      expect(focus.hasFocus,isTrue); expect(controller.value,composing);
      expect(tester.testTextInput.isRegistered,isTrue);
      tester.testTextInput.updateEditingValue(composing.copyWith(composing:TextRange.empty)); await tester.pump();
      expect(controller.text,'中文'); expect(adapter.received,isEmpty);

      // A genuine mode change still closes editing and exposes only the local
      // original-target draft; it cannot send or replay the composed text.
      await input.mode(tester,'observe');
      expect(find.byKey(const ValueKey('remote-input-draft')),findsNothing);
      expect(tester.widget<SelectableText>(find.byKey(const ValueKey('remote-unsent-text-0'))).data,'中文');
      expect(adapter.received,isEmpty); expect(tester.takeException(),isNull);
      await tester.pumpWidget(const SizedBox());
    });
  }
  testWidgets('reselecting active direct mode keeps composing client and commits Unicode exactly once',(tester) async {
    final adapter = input.InputFixtureAdapter(); await input.start(tester,adapter); await input.mode(tester,'direct');
    final terminal = find.byType(TerminalView),originalTerminal = tester.element(find.byType(TerminalView));
    final focus = tester.widget<TerminalView>(terminal).focusNode!;
    const composing = TextEditingValue(text:'中文',selection:TextSelection.collapsed(offset:2),
      composing:TextRange(start:0,end:2));
    tester.testTextInput.updateEditingValue(composing); await tester.pump();
    expect(adapter.received,isEmpty);
    await input.mode(tester,'direct');
    expect(identical(tester.element(terminal),originalTerminal),isTrue);
    expect(focus.hasFocus,isTrue); expect(tester.testTextInput.isRegistered,isTrue);
    tester.testTextInput.updateEditingValue(composing.copyWith(composing:TextRange.empty)); await tester.pump();
    expect(adapter.received.map((bytes) => utf8.decode(bytes)),['中文']);
    await input.mode(tester,'observe');
    expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-observe'))).selected,isTrue);
    expect(adapter.received.length,1); expect(tester.takeException(),isNull);
    await tester.pumpWidget(const SizedBox());
  });
}
