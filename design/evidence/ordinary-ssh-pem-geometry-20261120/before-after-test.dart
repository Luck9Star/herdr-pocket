import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'direct_ssh_host_key_change_widget_test.dart' show RotationPeer, fillTarget;
import 'direct_ssh_widget_test.dart' show waitFor;
import 'host_catalog_test.dart' show MemoryCatalogStorage;

void main() {
  testWidgets('ordinary SSH before or after blur', (tester) async {
    final before = Platform.environment['HERDR_PEM_BASELINE'] == 'before';
    final semantics = tester.ensureSemantics();
    final peer = (await tester.runAsync(RotationPeer.start))!;
    addTearDown(() => tester.runAsync(peer.stop));
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(390, 844);
    tester.view.padding = const FakeViewPadding(top: 47, bottom: 34);
    tester.view.viewPadding = const FakeViewPadding(top: 47, bottom: 34);
    addTearDown(tester.view.reset);
    final catalog = HostCatalog(storage: MemoryCatalogStorage(), clock: () => 1000);
    addTearDown(catalog.dispose);
    await catalog.load();
    final tokens = (await tester.runAsync(() async {
      final fontPath = Platform.environment['HERDR_PEM_FONT_PATH'];
      if (fontPath != null) {
        final font = FontLoader('EvidenceChinese');
        font.addFont(File(fontPath).readAsBytes().then(ByteData.sublistView));
        await font.load();
      }
      final iconsPath = Platform.environment['HERDR_PEM_ICON_FONT_PATH'];
      if (iconsPath != null) {
        final icons = FontLoader('MaterialIcons');
        icons.addFont(File(iconsPath).readAsBytes().then(ByteData.sublistView));
        await icons.load();
      }
      final mono = FontLoader('ProbeNerd');
      mono.addFont(rootBundle.load('assets/shared/fonts/JetBrainsMonoNerdFontMono-Regular.ttf'));
      await mono.load();
      return DesignTokens.load();
    }))!;
    final theme = tokens.theme.copyWith(
      appBarTheme: tokens.theme.appBarTheme.copyWith(titleTextStyle: tokens.theme.appBarTheme.titleTextStyle!.copyWith(fontFamily: 'EvidenceChinese')),
      textTheme: tokens.theme.textTheme.apply(fontFamily: 'EvidenceChinese'),
      primaryTextTheme: tokens.theme.primaryTextTheme.apply(fontFamily: 'EvidenceChinese'),
    );
    final boundary = GlobalKey();
    await tester.pumpWidget(RepaintBoundary(key: boundary, child: MaterialApp(theme: theme, debugShowCheckedModeBanner: false,
      home: HostCatalogPage(tokens: tokens, catalog: catalog, offlineBuilder: (_) => const SizedBox()))));
    await tester.pumpAndSettle();
    Finder k(String id) => find.byKey(ValueKey(id));
    Future<void> tap(String id) async {
      await tester.ensureVisible(k(id)); await tester.pumpAndSettle();
      expect(k(id).hitTestable(), findsOneWidget);
      await tester.tap(k(id)); await tester.pumpAndSettle();
    }
    await tap('hosts-direct-ssh');
    await fillTarget(tester, peer.port);
    await tap('direct-probe');
    await waitFor(tester, k('direct-trust-key'));
    await tap('direct-trust-key');
    await tap('direct-auth-key');
    final list = tester.state<ScrollableState>(find.descendant(of: k('direct-form'), matching: find.byType(Scrollable)).first);
    list.position.jumpTo(0); await tester.pumpAndSettle();
    await tap('direct-secret');
    await tester.enterText(k('direct-secret'), '示例一\n示例二');
    await tester.pumpAndSettle();
    await tap('direct-passphrase');
    list.position.jumpTo(0); await tester.pumpAndSettle();
    final secretPresent = k('direct-secret').evaluate().isNotEmpty;
    final summaryPresent = k('direct-edit-pem').evaluate().isNotEmpty;
    expect(secretPresent, before);
    expect(summaryPresent, !before);
    final phraseEditor = tester.widget<EditableText>(find.descendant(of: k('direct-passphrase'), matching: find.byType(EditableText)));
    expect(phraseEditor.focusNode.hasFocus, isTrue);
    var readable = false;
    if (before) {
      final editor = tester.widget<TextField>(k('direct-secret'));
      readable = !editor.obscureText && editor.controller!.text == '示例一\n示例二';
    }
    expect(readable, before);
    // The test view owns a child pipeline.
    // ignore: deprecated_member_use
    final root = tester.binding.pipelineOwner.semanticsOwner!.rootSemanticsNode!;
    var semanticsReadable = false;
    void visit(SemanticsNode node) {
      final data = node.getSemanticsData();
      if (data.value.contains('示例一') || data.label.contains('示例一')) semanticsReadable = true;
      node.visitChildren((child) { visit(child); return true; });
    }
    visit(root);
    expect(semanticsReadable, before);
    final credential = k(before ? 'direct-secret' : 'direct-edit-pem');
    final rect = tester.getRect(credential);
    debugPrint('PEM_COMPARISON ${jsonEncode({'baseline': before ? 'before' : 'after', 'rect': [rect.left, rect.top, rect.width, rect.height], 'editableReadable': readable, 'semanticsReadable': semanticsReadable, 'summaryPresent': summaryPresent, 'passphraseFocused': phraseEditor.focusNode.hasFocus})}');
    final dir = Platform.environment['HERDR_PEM_PIXEL_DIR']!;
    await tester.runAsync(() async {
      final image = await (boundary.currentContext!.findRenderObject()! as RenderRepaintBoundary).toImage();
      final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
      await File('$dir/${before ? 'before-blur' : 'after-blur'}.png').writeAsBytes(bytes!.buffer.asUint8List());
      image.dispose();
    });
    semantics.dispose();
    await tester.pumpWidget(const SizedBox()); await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  }, variant: TargetPlatformVariant.only(TargetPlatform.iOS));
}
