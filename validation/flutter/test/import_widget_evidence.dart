import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart' show RenderRepaintBoundary;
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

Future<ThemeData> loadImportEvidenceFonts(ThemeData theme, String? cjkFont) async {
  const mono = 'assets/shared/fonts/JetBrainsMonoNerdFontMono-Regular.ttf';
  await (FontLoader('ProbeNerd')..addFont(rootBundle.load(mono))).load();
  await (FontLoader('MaterialIcons')..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'))).load();
  if (cjkFont == null) return theme;
  await (FontLoader('ImportEvidenceCjk')..addFont(File(cjkFont).readAsBytes().then(ByteData.sublistView))).load();
  const family = 'ImportEvidenceCjk';
  return theme.copyWith(
    textTheme: theme.textTheme.apply(fontFamily: family),
    primaryTextTheme: theme.primaryTextTheme.apply(fontFamily: family),
    appBarTheme: theme.appBarTheme.copyWith(titleTextStyle: theme.appBarTheme.titleTextStyle?.copyWith(fontFamily: family)),
  );
}

Future<void> captureImportEvidence(WidgetTester tester, GlobalKey key, File destination) async {
  await tester.pump();
  final root = key.currentContext!.findRenderObject()! as RenderRepaintBoundary;
  await tester.runAsync(() async {
    final image = await root.toImage();
    try {
      final png = (await image.toByteData(format: ui.ImageByteFormat.png))!;
      destination.writeAsBytesSync(png.buffer.asUint8List());
    } finally { image.dispose(); }
  });
}
