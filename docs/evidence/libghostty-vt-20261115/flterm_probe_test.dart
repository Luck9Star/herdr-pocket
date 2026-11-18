import 'dart:convert';
import 'dart:typed_data';
import 'package:flterm/flterm.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('published flterm creates widget, consumes split UTF-8 and emits input', (tester) async {
    final output = <int>[];
    final controller = TerminalController()..onOutput = output.addAll;
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: TerminalView(controller: controller))));
    await tester.pump();
    final bytes = utf8.encode('中😀!');
    controller.write(Uint8List.fromList(bytes.sublist(0, 2)));
    controller.write(Uint8List.fromList(bytes.sublist(2)));
    await tester.pump();
    controller.selectAll();
    expect(controller.selectedText(), contains('中😀!'));
    controller.sendText('ok');
    expect(utf8.decode(output), 'ok');
    output.clear();
    controller.write(Uint8List.fromList([0x1b, 0x5b, 0x36, 0x6e]));
    expect(utf8.decode(output), startsWith('\x1b['));
    expect(find.byType(TerminalView), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
    controller.dispose();
  });
}
