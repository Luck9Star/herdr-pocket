import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/material.dart';
import 'package:terminal_view/terminal_view.dart';
import 'package:herdr_flutter_probe/remote_screen_text.dart';
import 'package:herdr_flutter_probe/remote_screen_viewport.dart';

void main() {
  test('screen page preserves Unicode, written spaces, cursor gaps and terminal soft-wrap copy semantics', () {
    final terminal = Terminal(maxLines:24,reflowEnabled:false)..resize(80,24);
    addTearDown(terminal.dispose);
    const unicode = '  中e\u0301👩\u200d💻  ';
    terminal.write('$unicode\r\nA\x1b[9GB  \r\n${'x' * 81}');
    final text = captureRemoteScreenText(terminal,const RemoteScreenCells(0,4,0,80))!;
    expect(text,'$unicode\nA       B  \n${'x' * 81}');
    expect(text,terminal.buffer.getText(BufferRangeLine(const CellOffset(0,0),const CellOffset(80,3))));
    expect(terminal.buffer.lines[3].isWrapped,isTrue);
  });

  test('shared 6x3 Unicode fixture agrees with both terminal engines for every half-open range', () {
    final file = [File('assets/shared/terminal-selection-v1.json'),File('../../validation/shared/terminal-selection-v1.json'),
      File('validation/shared/terminal-selection-v1.json')].firstWhere((file) => file.existsSync());
    final fixture = jsonDecode(file.readAsStringSync()) as Map<String,dynamic>;
    final terminal = Terminal(maxLines:24,reflowEnabled:false)..resize(fixture['columns'] as int,fixture['rows'] as int);
    addTearDown(terminal.dispose); terminal.write(fixture['write'] as String);
    for (final item in fixture['cases'] as List) {
      final cells = RemoteScreenCells(item['top'] as int,item['bottom'] as int,item['left'] as int,item['right'] as int);
      expect(captureRemoteScreenText(terminal,cells),item['text'],reason:item['name'] as String);
    }
  });

  test('only the active page is captured, excluding scrollback and inactive alternate buffer', () {
    final terminal = Terminal(maxLines:100,reflowEnabled:false)..resize(80,24);
    addTearDown(terminal.dispose);
    for (var row = 0; row < 30; row++) { terminal.write('HISTORY-$row\r\n'); }
    expect(terminal.buffer.scrollBack,greaterThan(0));
    final text = captureRemoteScreenText(terminal,RemoteScreenCells(terminal.buffer.scrollBack,terminal.buffer.height,0,80))!;
    expect(text,contains('HISTORY-29'));
    expect(text, isNot(contains('HISTORY-0')));
    terminal.write('\x1b[?1049hALT');
    final alternate = captureRemoteScreenText(terminal,const RemoteScreenCells(0,24,0,80))!;
    expect(alternate,startsWith('ALT\n'));
    expect(alternate,isNot(contains('HISTORY')));
  });

  test('oversize combined suffix and unexpected dimensions reject without partial capture or output', () {
    final terminal = Terminal(maxLines:24,reflowEnabled:false)..resize(80,24);
    addTearDown(terminal.dispose);
    final output = <String>[]; terminal.onOutput = output.add;
    terminal.write('e');
    terminal.buffer.lines[0].setCombined(0,'\u0301' * remoteScreenTextByteLimit);
    expect(captureRemoteScreenText(terminal,const RemoteScreenCells(0,24,0,80)),isNull);
    expect(output,isEmpty);
    expect(terminal.viewWidth,80); expect(terminal.viewHeight,24);
    terminal.resize(81,24);
    expect(captureRemoteScreenText(terminal,const RemoteScreenCells(0,24,0,81)),isNull);
    expect(output,isEmpty);
  });

  testWidgets('actual renderer scroll position determines rows and clipped columns never leak', (tester) async {
    final terminal = Terminal(maxLines:100,reflowEnabled:false)..resize(80,24),scroll = ScrollController();
    addTearDown(terminal.dispose); addTearDown(scroll.dispose);
    for (var row = 0; row < 24; row++) { terminal.write('\x1b[${row + 1};1HROW-$row\x1b[${row + 1};75HHIDDEN'); }
    await tester.pumpWidget(MaterialApp(home:Scaffold(body:Align(alignment:Alignment.topLeft,
      child:SizedBox(width:180,height:100,child:ClipRect(child:TerminalView(terminal,
        scrollController:scroll,autoResize:false,readOnly:true,hardwareKeyboardOnly:true)))))));
    await tester.pump();
    final render = tester.state<TerminalViewState>(find.byType(TerminalView)).renderTerminal;
    scroll.jumpTo(render.lineHeight * 5); await tester.pump();
    final cells = visibleRemoteScreenCells(terminal,render,Offset.zero & tester.view.physicalSize)!;
    expect(cells.firstRow,5); expect(cells.endRow,lessThan(24)); expect(cells.endColumn,lessThan(74));
    final text = captureRemoteScreenText(terminal,cells)!;
    expect(text,startsWith('ROW-5')); expect(text,isNot(contains('ROW-4'))); expect(text,isNot(contains('HIDDEN')));
    expect(terminal.viewWidth,80); expect(terminal.viewHeight,24);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('outer paint clip and partially exposed cells restrict capture to fully visible content', (tester) async {
    final terminal = Terminal(maxLines:24,reflowEnabled:false)..resize(80,24),scroll = ScrollController();
    addTearDown(terminal.dispose); addTearDown(scroll.dispose);
    await tester.pumpWidget(MaterialApp(home:Scaffold(body:Align(alignment:Alignment.topLeft,
      child:SizedBox(width:180,height:90,child:ClipRect(child:OverflowBox(alignment:Alignment.topLeft,
        minHeight:180,maxHeight:180,child:TerminalView(terminal,scrollController:scroll,autoResize:false,
          readOnly:true,hardwareKeyboardOnly:true))))))));
    await tester.pump(); scroll.jumpTo(0); await tester.pump();
    final render = tester.state<TerminalViewState>(find.byType(TerminalView)).renderTerminal;
    final origin = render.localToGlobal(Offset.zero),cellWidth = render.getOffset(const CellOffset(1,0)).dx - render.getOffset(const CellOffset(0,0)).dx;
    final cells = visibleRemoteScreenCells(terminal,render,Rect.fromLTRB(origin.dx + cellWidth * 2.4,
      origin.dy + render.lineHeight * 0.4,origin.dx + 180,origin.dy + 180))!;
    expect(render.size.height,180); expect(cells.firstRow,1); expect(cells.firstColumn,3);
    expect(cells.endRow * render.lineHeight,lessThanOrEqualTo(90));
    await tester.pumpWidget(const SizedBox());
  });
}
