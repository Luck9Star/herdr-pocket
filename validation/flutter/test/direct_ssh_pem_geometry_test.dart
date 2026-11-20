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
  for (final isMobile in [true, false]) {
    testWidgets('PEM geometry ${isMobile ? "mobile" : "desktop"}', (tester) async {
      final peer = (await tester.runAsync(RotationPeer.start))!;
      addTearDown(() => tester.runAsync(peer.stop));
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = isMobile ? const Size(390, 844) : const Size(980, 780);
      if (isMobile) {
        tester.view.padding = const FakeViewPadding(top: 47, bottom: 34);
        tester.view.viewPadding = const FakeViewPadding(top: 47, bottom: 34);
      }
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
      Future<void> capture(String phase) async {
        final dir = Platform.environment['HERDR_PEM_PIXEL_DIR'];
        if (dir == null) return;
        await tester.runAsync(() async {
          final image = await (boundary.currentContext!.findRenderObject()! as RenderRepaintBoundary).toImage();
          final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
          await File('$dir/${isMobile ? "mobile" : "desktop"}-$phase.png').writeAsBytes(bytes!.buffer.asUint8List());
          image.dispose();
        });
      }
      void measure(String phase, String id) {
        final rect = tester.getRect(k(id));
        final hits = <bool>[
          for (final point in [Alignment.center, const Alignment(-0.9, 0), const Alignment(0.9, 0), const Alignment(0, -0.9), const Alignment(0, 0.9)])
            k(id).hitTestable(at: point).evaluate().isNotEmpty,
        ];
        final expectedY = isMobile ? {'direct-secret': 351.0, 'direct-edit-pem': 351.0, 'direct-paste-key': 445.0, 'direct-passphrase': 527.0, 'direct-connect': 589.0}
            : {'direct-secret': 304.0, 'direct-edit-pem': 304.0, 'direct-paste-key': 398.0, 'direct-passphrase': 480.0, 'direct-connect': 542.0};
        if (phase != 'keyboard-open-scrolled') {
          final expected = [isMobile ? 24.0 : 264.0, expectedY[id]!, isMobile ? 342.0 : 560.0, (id == 'direct-secret' || id == 'direct-edit-pem') ? 84.0 : 48.0];
          final actual = [rect.left, rect.top, rect.width, rect.height];
          for (var i = 0; i < actual.length; i++) { expect((actual[i] - expected[i]).abs(), lessThanOrEqualTo(2), reason: '$phase $id coordinate $i'); }
          expect(hits.every((hit) => hit), isTrue, reason: '$phase $id hit bounds');
        }
        debugPrint('PEM_GEOMETRY ${jsonEncode({'platform': isMobile ? 'mobile' : 'desktop', 'phase': phase, 'id': id, 'rect': [rect.left,rect.top,rect.width,rect.height], 'sampleHits': hits})}');
      }
      for (final id in ['direct-secret','direct-paste-key','direct-passphrase','direct-connect']) measure('editor-empty', id);
      await capture('editor-empty');
      await tap('direct-secret');
      await tester.enterText(k('direct-secret'), 'synthetic first line\nsynthetic second line\nsynthetic third line');
      await tester.pumpAndSettle();
      for (final id in ['direct-secret','direct-paste-key','direct-passphrase','direct-connect']) measure('editor-focused', id);
      await capture('editor-focused');
      expect(tester.widget<FilledButton>(k('direct-connect')).onPressed, isNull);
      await tap('direct-passphrase');
      expect(tester.widget<EditableText>(find.descendant(of: k('direct-passphrase'), matching: find.byType(EditableText))).focusNode.hasFocus, isTrue);
      expect(k('direct-secret'), findsNothing);
      list.position.jumpTo(0); await tester.pumpAndSettle();
      for (final id in ['direct-edit-pem','direct-paste-key','direct-passphrase','direct-connect']) measure('collapsed', id);
      await capture('collapsed');
      await tap('direct-edit-pem');
      expect(tester.widget<TextField>(k('direct-secret')).controller!.text == 'synthetic first line\nsynthetic second line\nsynthetic third line', isTrue);
      await tap('direct-passphrase');
      expect(find.byKey(const ValueKey('direct-edit-pem')), findsOneWidget);
      if (isMobile) {
        tester.view.viewInsets = const FakeViewPadding(bottom: 291);
        await tester.pumpAndSettle();
        await tester.ensureVisible(k('direct-passphrase')); await tester.pumpAndSettle();
        measure('keyboard-open-scrolled', 'direct-passphrase');
        await capture('keyboard-open-scrolled');
        expect(k('direct-passphrase').hitTestable(), findsOneWidget);
        tester.view.viewInsets = FakeViewPadding.zero;
        await tester.pumpAndSettle();
      }
      await tester.pumpWidget(const SizedBox()); await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    }, variant: TargetPlatformVariant.only(isMobile ? TargetPlatform.iOS : TargetPlatform.linux),
      skip: Platform.environment['HERDR_FIXTURE_PYTHON'] == null);
  }
}
