import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';
import 'package:flutter/painting.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
// Candidate-internal painter is deliberate: isolate rendering from our shell.
// ignore: implementation_imports
import 'package:terminal_view/src/ui/painter.dart';
import 'package:terminal_view/terminal_view.dart';

List<String> codepoints(String text) => text.runes
    .map((rune) => 'U+${rune.toRadixString(16).padLeft(4, '0')}').toList();

Future<Uint8List> raster(String text, String name, Directory output) async {
  final terminal = Terminal()..resize(80, 24)..write(text);
  final painter = TerminalPainter(
    theme: TerminalThemes.defaultTheme,
    textStyle: const TerminalStyle(fontFamily: 'ProbeNerd', fontSize: 14),
    textScaler: TextScaler.noScaling,
  );
  final recorder = ui.PictureRecorder();
  final canvas = ui.Canvas(recorder);
  painter.paintLine(canvas, const ui.Offset(8, 8), terminal.buffer.lines[0]);
  final picture = recorder.endRecording();
  final image = await picture.toImage(400, 48);
  final pixels = (await image.toByteData(format: ui.ImageByteFormat.rawRgba))!
      .buffer.asUint8List();
  final png = (await image.toByteData(format: ui.ImageByteFormat.png))!
      .buffer.asUint8List();
  await File('${output.path}/$name.png').writeAsBytes(png);
  image.dispose();
  picture.dispose();
  return pixels;
}

void main() {
  testWidgets('combining marks survive storage and affect actual painter pixels', (tester) async {
    await tester.runAsync(() async {
      final font = FontLoader('ProbeNerd')..addFont(rootBundle.load(
        'assets/shared/fonts/JetBrainsMonoNerdFontMono-Regular.ttf'));
      await font.load();
      const plain = 'e A n';
      const marked = 'e\u0301 A\u030a n\u0303';
      final terminal = Terminal()..resize(80, 24)..write(marked);
      final copyApiText = terminal.buffer.lines[0].getText();
      final output = Directory('probe-results')..createSync();
      final plainPixels = await raster(plain, 'ascii-base', output);
      final markedPixels = await raster(marked, 'ascii-combining', output);
      final equalPixels = listEquals(plainPixels, markedPixels);
      final report = {
        'schemaVersion': 1,
        'sourceCommit': Platform.environment['GITHUB_SHA'],
        'terminalVersion': '0.5.0',
        'scope': 'Pinned shared font; real Terminal buffer and TerminalPainter in Flutter test engine. Not native clipboard, device IME or whole GUI validation.',
        'input': marked, 'inputCodepoints': codepoints(marked),
        'copyApiText': copyApiText, 'copyApiCodepoints': codepoints(copyApiText),
        'bufferPreservesMarks': copyApiText == marked,
        'cursorX': terminal.buffer.cursorX,
        'baseAndCombiningPixelsEqual': equalPixels,
        'combiningVisibleCriterion': equalPixels ? 'failed' : 'passed',
        'images': ['ascii-base.png', 'ascii-combining.png'],
      };
      await File('${output.path}/combining-render.json')
          .writeAsString('${const JsonEncoder.withIndent('  ').convert(report)}\n');
      expect(copyApiText, marked, reason: 'Parser/storage must preserve codepoints');
      expect(terminal.buffer.cursorX, 5, reason: 'Marks must not add terminal columns');
      expect(equalPixels, isFalse,
        reason: 'Visible accents must change rendered pixels. The unpatched 0.5.0 ASCII batch path is suspected to discard combined marks. See attached report and PNGs.');
    });
  });
}
