import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
// Deliberate candidate regression: exercise its real painter, not a mock.
// ignore: implementation_imports
import 'package:terminal_view/src/ui/painter.dart';
import 'package:terminal_view/terminal_view.dart';

const style = TerminalStyle(fontFamily: 'ProbeNerd', fontSize: 14);
final reports = <Map<String, Object?>>[];
final output = Directory('probe-results/regression');

bool pixelsEqual(List<int> a, List<int> b) {
  if (a.length != b.length) return false;
  for (var i = 0; i < a.length; i++) {
    if (a[i] != b[i]) return false;
  }
  return true;
}

int countPixels(List<int> pixels, bool Function(int, int, int, int) matches) {
  var count = 0;
  for (var i = 0; i < pixels.length; i += 4) {
    if (matches(pixels[i], pixels[i + 1], pixels[i + 2], pixels[i + 3])) count++;
  }
  return count;
}

Future<void> loadFont() async {
  final font = FontLoader('ProbeNerd')..addFont(rootBundle.load(
    'assets/shared/fonts/JetBrainsMonoNerdFontMono-Regular.ttf'));
  await font.load();
}

Future<List<int>> saveImage(ui.Image image, String name) async {
  final rgba = (await image.toByteData(format: ui.ImageByteFormat.rawRgba))!
      .buffer.asUint8List();
  final png = (await image.toByteData(format: ui.ImageByteFormat.png))!
      .buffer.asUint8List();
  output.createSync(recursive: true);
  await File('${output.path}/$name.png').writeAsBytes(png);
  image.dispose();
  return rgba;
}

TerminalPainter painter() => TerminalPainter(
  theme: TerminalThemes.defaultTheme, textStyle: style,
  textScaler: TextScaler.noScaling,
);

Future<List<int>> paintLine(Terminal terminal, String name,
    {TerminalPainter? reuse}) async {
  final recorder = ui.PictureRecorder();
  (reuse ?? painter()).paintLine(ui.Canvas(recorder), const Offset(8, 8),
    terminal.buffer.lines[0]);
  final picture = recorder.endRecording();
  final result = await saveImage(await picture.toImage(400, 48), name);
  picture.dispose();
  return result;
}

void recordPair(String id, List<int> actual, List<int> reference,
    Terminal terminal, String expectedText, int columns) {
  final equal = pixelsEqual(actual, reference);
  final visible = countPixels(actual, (r, g, b, a) => a > 0);
  reports.add({
    'id': id, 'matchesReferencePixels': equal,
    'bufferCodepoints': terminal.buffer.lines[0].getText().runes.toList(),
    'expectedCodepoints': expectedText.runes.toList(),
    'cursorX': terminal.buffer.cursorX, 'expectedColumns': columns,
    'nontransparentPixels': visible,
  });
  expect(visible, greaterThan(0), reason: 'An empty image is not a valid glyph comparison');
  expect(terminal.buffer.lines[0].getText(), expectedText);
  expect(terminal.buffer.cursorX, columns);
  expect(equal, isTrue, reason: '$id must match the reference glyphs and placement');
}

TerminalTheme overlayTheme() {
  final base = TerminalThemes.defaultTheme;
  return TerminalTheme(
    cursor: Colors.white, cursorAccent: Colors.black,
    selection: Colors.white, selectionForeground: Colors.black,
    foreground: base.foreground, background: base.background,
    black: base.black, white: base.white, red: base.red, green: base.green,
    yellow: base.yellow, blue: base.blue, magenta: base.magenta, cyan: base.cyan,
    brightBlack: base.brightBlack, brightRed: base.brightRed,
    brightGreen: base.brightGreen, brightYellow: base.brightYellow,
    brightBlue: base.brightBlue, brightMagenta: base.brightMagenta,
    brightCyan: base.brightCyan, brightWhite: base.brightWhite,
    searchHitBackground: base.searchHitBackground,
    searchHitBackgroundCurrent: base.searchHitBackgroundCurrent,
    searchHitForeground: base.searchHitForeground,
  );
}

Future<List<int>> widgetRaster(WidgetTester tester, String text, String name,
    {required bool selection}) async {
  final terminal = Terminal()..resize(80, 24)..write(text);
  terminal.write(selection ? '\x1b[?25l' : '\x1b[1G');
  final controller = TerminalController();
  final focus = FocusNode();
  final boundaryKey = GlobalKey();
  if (selection) {
    controller.setSelection(terminal.buffer.createAnchor(0, 0),
      terminal.buffer.createAnchor(1, 0));
  }
  await tester.pumpWidget(MaterialApp(home: Align(alignment: Alignment.topLeft,
    child: RepaintBoundary(key: boundaryKey, child: SizedBox(width: 720, height: 480,
      child: TerminalView(terminal, controller: controller, focusNode: focus,
        autoResize: false, readOnly: true, padding: EdgeInsets.zero,
        textStyle: style, textScaler: TextScaler.noScaling, theme: overlayTheme()))))));
  if (!selection) focus.requestFocus();
  await tester.pump();
  await tester.pump();
  expect(terminal.viewWidth, 80);
  expect(terminal.viewHeight, 24);
  final boundary = boundaryKey.currentContext!.findRenderObject()! as RenderRepaintBoundary;
  final result = await tester.runAsync(() async =>
    saveImage(await boundary.toImage(pixelRatio: 1), name));
  if (selection) {
    expect(terminal.buffer.getText(controller.selection!), text);
  } else {
    expect(focus.hasFocus, isTrue);
    expect(terminal.buffer.cursorX, 0);
  }
  await tester.pumpWidget(const SizedBox());
  controller.dispose();
  focus.dispose();
  return result!;
}

void main() {
  tearDownAll(() async {
    output.createSync(recursive: true);
    await File('${output.path}/results.json').writeAsString(
      '${const JsonEncoder.withIndent('  ').convert({
        'sourceCommit': Platform.environment['GITHUB_SHA'],
        'scope': 'Flutter test engine, pinned font; NFC is only a reference, input remains decomposed. Not whole Unicode, device IME or native clipboard validation.',
        'comparisons': reports,
      })}\n');
  });

  final cases = [
        ('three-accents', 'e\u0301 A\u030a n\u0303', 'é Å ñ', 'e\u0301 A\u030a n\u0303', 5),
        ('ascii-neighbors', 'ABe\u0301CD', 'ABéCD', 'ABe\u0301CD', 5),
        ('wide-neighbors', '中e\u0301文n\u0303Z', '中é文ñZ', '中e\u0301文n\u0303Z', 7),
        ('sgr-bold-red', '\x1b[1;31mAe\u0301B\x1b[0m中n\u0303Z',
          '\x1b[1;31mAéB\x1b[0m中ñZ', 'Ae\u0301B中n\u0303Z', 7),
        ('sgr-inverse', '\x1b[7;34mA\u030a\x1b[0mZ', '\x1b[7;34mÅ\x1b[0mZ', 'A\u030aZ', 2),
  ];
  for (final (id, input, reference, expected, columns) in cases) {
    testWidgets('$id matches reference glyphs and placement', (tester) async {
      await tester.runAsync(() async {
        await loadFont();
        final actual = Terminal()..resize(80, 24)..write(input);
        final oracle = Terminal()..resize(80, 24)..write(reference);
        recordPair(id, await paintLine(actual, '$id-actual'),
          await paintLine(oracle, '$id-nfc-reference'), actual, expected, columns);
      });
    });
  }

  testWidgets('ordinary ASCII matches independent Flutter TextPainter', (tester) async {
    await tester.runAsync(() async {
      await loadFont();
      const text = 'ABC xyz 0123';
      final terminal = Terminal()..resize(80, 24)..write(text);
      final recorder = ui.PictureRecorder();
      final reference = TextPainter(
        text: TextSpan(text: text, style: style.toTextStyle(color: TerminalThemes.defaultTheme.foreground)),
        textDirection: TextDirection.ltr, strutStyle: style.toStrutStyle(),
        textScaler: TextScaler.noScaling,
      )..layout();
      reference.paint(ui.Canvas(recorder), const Offset(8, 8));
      final picture = recorder.endRecording();
      final expected = await saveImage(await picture.toImage(400, 48), 'ascii-textpainter-reference');
      picture.dispose(); reference.dispose();
      recordPair('ordinary-ascii', await paintLine(terminal, 'ascii-actual'),
        expected, terminal, text, 12);
    });
  });

  testWidgets('line picture cache invalidates after a separately arriving mark', (tester) async {
    await tester.runAsync(() async {
      await loadFont();
      final terminal = Terminal()..resize(80, 24)..write('e');
      final reuse = painter();
      await paintLine(terminal, 'cache-base-first', reuse: reuse);
      await paintLine(terminal, 'cache-base-recorded', reuse: reuse);
      terminal.write('\u0301');
      final expected = Terminal()..resize(80, 24)..write('é');
      final oracle = await paintLine(expected, 'cache-nfc-reference');
      recordPair('cache-after-suffix', await paintLine(terminal, 'cache-updated', reuse: reuse),
        oracle, terminal, 'e\u0301', 1);
      recordPair('cache-repeated', await paintLine(terminal, 'cache-repeated', reuse: reuse),
        oracle, terminal, 'e\u0301', 1);
    });
  });

  for (final selection in [false, true]) {
    final name = selection ? 'selection-foreground' : 'focused-block-cursor';
    testWidgets('$name preserves the full grapheme', (tester) async {
      await tester.runAsync(loadFont);
      final actual = await widgetRaster(tester, 'e\u0301', '$name-actual', selection: selection);
      final expected = await widgetRaster(tester, 'é', '$name-nfc-reference', selection: selection);
      final equal = pixelsEqual(actual, expected);
      final white = countPixels(actual, (r, g, b, a) => r == 255 && g == 255 && b == 255 && a == 255);
      final black = countPixels(actual, (r, g, b, a) => r == 0 && g == 0 && b == 0 && a == 255);
      reports.add({'id': name, 'matchesReferencePixels': equal,
        'whiteBackgroundPixels': white, 'blackForegroundPixels': black});
      expect(white, greaterThan(0), reason: 'Expected cursor/selection background to be drawn');
      expect(black, greaterThan(0), reason: 'Expected actual black accent glyphs, not only a blank background');
      expect(equal, isTrue, reason: '$name must redraw the accent as well as the base');
    });
  }
}
