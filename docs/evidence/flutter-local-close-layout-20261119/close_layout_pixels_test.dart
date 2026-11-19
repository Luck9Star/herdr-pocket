import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:terminal_view/terminal_view.dart';

import 'direct_ssh_widget_test.dart' show tapAndWaitForOrdinaryDisconnect, waitFor;
import 'host_catalog_test.dart' show MemoryCatalogStorage;

const _screens = [
  (Size(1440, 900), 264.0, 560.0, 0.0, 62.0),
  (Size(980, 780), 264.0, 560.0, 0.0, 62.0),
  (Size(700, 900), 104.0, 556.0, 0.0, 62.0),
  (Size(390, 844), 24.0, 342.0, 47.0, 119.0),
  (Size(320, 640), 16.0, 288.0, 24.0, 96.0),
];

void main() {
  final port = Platform.environment['HERDR_DIRECT_SSH_FIXTURE_PORT'];
  final output = Platform.environment['HERDR_OUTCOME_PIXELS'];
  for (final (size, left, width, topInset, returnedTop) in _screens) {
    final mobile = size.width < 600;
    testWidgets('ordinary SSH close layout at ${size.width.toInt()}px', (tester) async {
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = size;
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.view.resetPhysicalSize);
      if (mobile) {
        final insets = FakeViewPadding(top: topInset, bottom: size.width == 390 ? 34 : 24);
        tester.view.padding = insets;
        tester.view.viewPadding = insets;
        addTearDown(tester.view.resetPadding);
        addTearDown(tester.view.resetViewPadding);
      }
      const family = 'Snapshot Chinese';
      final tokens = (await tester.runAsync(() async {
        final bytes = await File('/System/Library/Fonts/Supplemental/Arial Unicode.ttf').readAsBytes();
        await (FontLoader(family)..addFont(Future.value(bytes.buffer.asByteData()))).load();
        for (final entry in {
          'MaterialIcons': 'fonts/MaterialIcons-Regular.otf',
          'ProbeNerd': 'assets/shared/fonts/JetBrainsMonoNerdFontMono-Regular.ttf',
        }.entries) {
          await (FontLoader(entry.key)..addFont(rootBundle.load(entry.value))).load();
        }
        return DesignTokens.load();
      }))!;
      final theme = tokens.theme.copyWith(
        platform: mobile ? TargetPlatform.iOS : TargetPlatform.macOS,
        textTheme: tokens.theme.textTheme.apply(fontFamily: family),
        appBarTheme: tokens.theme.appBarTheme.copyWith(
          titleTextStyle: tokens.theme.appBarTheme.titleTextStyle?.copyWith(fontFamily: family),
        ),
      );
      final catalog = HostCatalog(storage: MemoryCatalogStorage(), clock: () => 1000);
      await catalog.load();
      Finder key(String id) => find.byKey(ValueKey(id));
      Future<void> tap(String id) async {
        final control = key(id);
        await tester.ensureVisible(control);
        await tester.pumpAndSettle();
        expect(control.hitTestable(), findsOneWidget);
        await tester.tap(control);
        await tester.pumpAndSettle();
      }

      Future<void> capture(String phase) async {
        await tester.pump();
        final box = tester.renderObject<RenderRepaintBoundary>(key('capture'));
        await tester.runAsync(() async {
          final image = await box.toImage(pixelRatio: 1);
          try {
            final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
            await File('$output/${size.width.toInt()}-$phase.png').writeAsBytes(bytes!.buffer.asUint8List());
          } finally {
            image.dispose();
          }
        });
      }

      void anchor(String id, Rect expected) {
        expect(key(id).hitTestable(), findsOneWidget);
        final actual = tester.getRect(key(id));
        final measurements = [actual.left, actual.top, actual.width, actual.height];
        print('ANCHOR ${size.width.toInt()} $id $measurements');
        final target = [expected.left, expected.top, expected.width, expected.height];
        for (var index = 0; index < target.length; index++) {
          expect(measurements[index], closeTo(target[index], 2), reason: '$id $actual vs $expected');
        }
      }

      await tester.pumpWidget(MaterialApp(
        theme: theme,
        builder: (_, child) => RepaintBoundary(key: const ValueKey('capture'), child: child!),
        home: HostCatalogPage(tokens: tokens, catalog: catalog, offlineBuilder: (_) => const SizedBox()),
      ));
      await tester.pumpAndSettle();
      await tap('hosts-direct-ssh');
      await tester.enterText(key('direct-host'), '127.0.0.1');
      await tester.enterText(key('direct-port'), port!);
      await tester.enterText(key('direct-user'), 'fixture');
      await tap('direct-probe');
      await waitFor(tester, key('direct-trust-key'));
      await tap('direct-trust-key');
      await tester.enterText(key('direct-secret'), 'temporary');
      await tap('direct-connect');
      await waitFor(tester, find.byType(TerminalView));
      await tester.pumpAndSettle();
      await capture('active');

      await tapAndWaitForOrdinaryDisconnect(tester);
      expect(find.text('本机已断开'), findsOneWidget);
      expect(find.text('凭据已清空，重连时请重新填写。'), findsOneWidget);
      anchor('direct-closed-feedback', Rect.fromLTWH(left, topInset + 76, width, 66));
      anchor('direct-return-home', Rect.fromLTWH(left, topInset + 452, width, 48));
      await capture('result');

      await tap('direct-return-home');
      expect(find.text('本机已断开'), findsOneWidget);
      anchor('home-ssh-closed', Rect.fromLTWH(left, returnedTop, width, 44));
      if (!mobile) {
        anchor('home-empty-card', Rect.fromLTWH(left, 122, width, 268));
        final sidebarWidth = size.width == 700 ? 64.0 : 224.0;
        expect(tester.getSize(key('app-sidebar')).width, sidebarWidth);
        print('SIDEBAR ${size.width.toInt()} $sidebarWidth');
      }
      await capture('home');
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      catalog.dispose();
    }, variant: TargetPlatformVariant.only(mobile ? TargetPlatform.iOS : TargetPlatform.linux),
      skip: port == null || output == null);
  }
}
