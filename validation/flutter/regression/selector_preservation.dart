import 'dart:convert';
import 'dart:io';
import 'package:terminal_view/core.dart';
import 'package:herdr_flutter_probe/remote_screen_text.dart';

void requireSelectorCheck(bool condition,String name) {
  if (!condition) throw StateError('selector_preservation: $name');
}

/// Pure-Dart characterization/regression of the real pinned terminal core.
/// Widths are observed for external baseline comparison, never inferred from
/// grapheme length, Unicode names, or a platform's emoji presentation.
Map<String,Object?> runSelectorPreservationChecks({bool expectPreserved = true}) {
  final samples = <({String name,List<String> chunks,String copy,int columns,int rows})>[
    (name:'woman-technologist',chunks:['👩‍💻!'],copy:'👩‍💻!',columns:80,rows:1),
    (name:'family-man-woman-girl-boy',chunks:['👨‍👩‍👧‍👦!'],copy:'👨‍👩‍👧‍👦!',columns:80,rows:1),
    (name:'flag-china',chunks:['🇨🇳!'],copy:'🇨🇳!',columns:80,rows:1),
    (name:'heart-emoji-presentation',chunks:['❤️!'],copy:'❤️!',columns:80,rows:1),
    (name:'sun-text-presentation',chunks:['☀︎!'],copy:'☀︎!',columns:80,rows:1),
    (name:'cjk-middle',chunks:['中!'],copy:'中!',columns:80,rows:1),
    (name:'grinning-face',chunks:['😀!'],copy:'😀!',columns:80,rows:1),
    (name:'e-combining-acute',chunks:['e\u0301!'],copy:'e\u0301!',columns:80,rows:1),
    (name:'powerline-right-hard-divider',chunks:['\uE0B0!'],copy:'\uE0B0!',columns:80,rows:1),
    (name:'middle-dot',chunks:['·!'],copy:'·!',columns:80,rows:1),
    (name:'ordered-combining-and-selectors',chunks:['e\u0301','\uFE0F','\u0300','\uFE0E!'],copy:'e\u0301\uFE0F\u0300\uFE0E!',columns:80,rows:1),
    (name:'repeated-selectors',chunks:['❤\uFE0F\uFE0F\uFE0E\uFE0E!'],copy:'❤\uFE0F\uFE0F\uFE0E\uFE0E!',columns:80,rows:1),
    (name:'zwj-heart-sequence',chunks:['👩\u200D❤️\u200D👩!'],copy:'👩\u200D❤️\u200D👩!',columns:80,rows:1),
    (name:'fragmented-zwj-selector',chunks:['👩','\u200D','💻','\uFE0F','!'],copy:'👩\u200D💻\uFE0F!',columns:80,rows:1),
    (name:'selector-after-pending-joiner',chunks:['A\u200D','\uFE0F!'],copy:'A\u200D\uFE0F!',columns:80,rows:1),
    (name:'selector-after-cjk',chunks:['中\uFE0F!'],copy:'中\uFE0F!',columns:80,rows:1),
    (name:'standalone-vs15',chunks:['\uFE0E!'],copy:'!',columns:80,rows:1),
    (name:'standalone-vs16',chunks:['\uFE0F!'],copy:'!',columns:80,rows:1),
    (name:'standalone-repeated-selectors',chunks:['\uFE0E\uFE0F\uFE0F!'],copy:'!',columns:80,rows:1),
    (name:'selector-after-unwritten-gap',chunks:['A\x1b[5G\uFE0F!'],copy:'A   !',columns:80,rows:1),
    (name:'last-column-narrow-base',chunks:['abc❤\uFE0F!'],copy:'abc❤\uFE0F!',columns:4,rows:2),
    (name:'last-column-wide-base',chunks:['ab中\uFE0F!'],copy:'ab中\uFE0F!',columns:4,rows:2),
    (name:'selectors-after-written-space',chunks:[' \uFE0F\uFE0E!'],copy:' \uFE0F\uFE0E!',columns:80,rows:1),
  ];
  final results = <Map<String,Object?>>[];
  for (final sample in samples) {
    final terminal = Terminal(maxLines:24,reflowEnabled:false)..resize(sample.columns,24);
    final generated = <String>[]; terminal.onOutput = generated.add;
    for (final chunk in sample.chunks) { terminal.write(chunk); }
    final copy = captureRemoteScreenText(terminal,RemoteScreenCells(0,sample.rows,0,sample.columns));
    final upstream = terminal.buffer.getText(BufferRangeLine(const CellOffset(0,0),CellOffset(sample.columns,sample.rows - 1)));
    requireSelectorCheck(copy == upstream,'${sample.name}: production copy vs pinned getText');
    if (expectPreserved) requireSelectorCheck(copy == sample.copy,'${sample.name}: ordered input suffix');
    requireSelectorCheck(generated.isEmpty,'${sample.name}: no terminal-generated output');
    requireSelectorCheck(terminal.viewWidth == sample.columns && terminal.viewHeight == 24,'${sample.name}: no resize');
    final layout = <List<List<int>>>[],combined = <Map<String,Object?>>[],markers = <List<int>>[];
    for (var row = 0; row < terminal.buffer.height; row++) {
      final line = terminal.buffer.lines[row],rowLayout = <List<int>>[];
      for (var column = 0; column < sample.columns; column++) {
        final codePoint = line.getCodePoint(column),suffix = line.getCombined(column);
        rowLayout.add([codePoint,line.getWidth(column),line.getForeground(column),line.getBackground(column),line.getAttributes(column)]);
        if (suffix != null) combined.add({'row':row,'column':column,'scalars':suffix.runes.toList()});
        if (codePoint == 0x21) markers.add([row,column]);
      }
      layout.add(rowLayout);
    }
    requireSelectorCheck(markers.length == 1,'${sample.name}: unique observed marker');
    results.add({'name':sample.name,'input':sample.chunks.join(),'copy':copy,'expectedPreservedCopy':sample.copy,
      'copyPreserved':copy == sample.copy,'copyMatchesPinnedGetText':copy == upstream,'markers':markers,
      'cursor':[terminal.buffer.cursorX,terminal.buffer.cursorY],'layout':layout,'combined':combined});
    terminal.dispose();
  }
  final sharedFile = [File('assets/shared/terminal-selection-v1.json'),File('../../validation/shared/terminal-selection-v1.json'),
    File('validation/shared/terminal-selection-v1.json')].firstWhere((file) => file.existsSync());
  final fixture = jsonDecode(sharedFile.readAsStringSync()) as Map<String,dynamic>;
  final fixtureTerminal = Terminal(maxLines:24,reflowEnabled:false)..resize(fixture['columns'] as int,fixture['rows'] as int);
  fixtureTerminal.write(fixture['write'] as String);
  final shared = <Map<String,Object?>>[];
  for (final item in fixture['cases'] as List) {
    final text = captureRemoteScreenText(fixtureTerminal,RemoteScreenCells(item['top'] as int,item['bottom'] as int,item['left'] as int,item['right'] as int));
    requireSelectorCheck(text == item['text'],'shared fixture: ${item['name']}');
    shared.add({'name':item['name'],'text':text,'status':'passed'});
  }
  fixtureTerminal.dispose();
  return {'mode':expectPreserved ? 'candidate-regression' : 'baseline-characterization','samples':results,
    'sharedFixtureCases':shared,'scope':'Pure Dart terminal buffer/copy and characterized cell layout. No Flutter painting, device, IME, clipboard or SSH validation.'};
}

void main(List<String> args) {
  print(jsonEncode(runSelectorPreservationChecks(expectPreserved:!args.contains('--characterize'))));
}
