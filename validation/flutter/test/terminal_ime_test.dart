import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/main.dart';
import 'package:herdr_flutter_probe/probe_gate.dart';

void main() {
  testWidgets('terminal_view composing stays local; committed UTF-8 reaches sink once', (tester) async {
    final p = ProbePane('fixture/session/pane');
    p.gate.select(true);
    p.gate.enqueue(Frame(p.gate.ticket, 'full', full: true));
    p.gate.consume();
    p.gate.setMode(InputMode.direct);
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: TerminalPane(
      pane: p, full: 'fixture', scrollback: 2000, enabled: true,
      onPaste: () {}, onSent: () {},
    ))));
    p.focusNode.requestFocus();
    await tester.pump();
    expect(tester.testTextInput.isRegistered, isTrue);
    tester.testTextInput.updateEditingValue(const TextEditingValue(
      text: '中文', selection: TextSelection.collapsed(offset: 2),
      composing: TextRange(start: 0, end: 2),
    ));
    await tester.pump();
    expect(p.gate.inputCount, 0);
    tester.testTextInput.updateEditingValue(const TextEditingValue(
      text: '中文', selection: TextSelection.collapsed(offset: 2),
      composing: TextRange.empty,
    ));
    await tester.pump();
    expect(p.gate.inputCount, 1);
    expect(p.gate.inputHex.single, 'e4b8ade69687');
    p.gate.select(false);
    tester.testTextInput.updateEditingValue(const TextEditingValue(
      text: 'late', selection: TextSelection.collapsed(offset: 4),
    ));
    await tester.pump();
    expect(p.gate.inputCount, 1);
    await tester.pumpWidget(const SizedBox());
    p.selection.dispose(); p.draft.dispose(); p.focusNode.dispose();
  });
}
