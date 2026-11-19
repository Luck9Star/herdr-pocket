import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:terminal_view/terminal_view.dart';
import 'direct_ssh_widget_test.dart' show waitFor;
import 'host_catalog_test.dart' show MemoryCatalogStorage;

void main() {
  for (final size in [const Size(1440, 900), const Size(980, 780), const Size(700, 900)]) {
    for (final chooser in [false, true]) {
      testWidgets('desktop ordinary SSH return ${size.width} chooser=$chooser', (tester) async {
        tester.view.devicePixelRatio = 1; tester.view.physicalSize = size;
        addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
        final tokens = (await tester.runAsync(DesignTokens.load))!;
        final catalog = HostCatalog(storage: MemoryCatalogStorage(), clock: () => 1000); await catalog.load();
        await tester.pumpWidget(MaterialApp(theme: tokens.theme.copyWith(platform: TargetPlatform.macOS), home: HostCatalogPage(tokens: tokens, catalog: catalog, offlineBuilder: (_) => const SizedBox())));
        await tester.pumpAndSettle();
        Finder key(String value) => find.byKey(ValueKey(value));
        if (chooser) { await tester.ensureVisible(key('hosts-add')); await tester.tap(key('hosts-add')); await tester.pumpAndSettle(); await tester.tap(key('choose-ssh')); }
        else { await tester.ensureVisible(key('hosts-direct-ssh')); await tester.tap(key('hosts-direct-ssh')); }
        await tester.pumpAndSettle();
        await tester.enterText(key('direct-host'), '127.0.0.1'); await tester.enterText(key('direct-port'), Platform.environment['HERDR_DIRECT_SSH_FIXTURE_PORT']!);
        await tester.enterText(key('direct-user'), 'fixture'); await tester.pump();
        await tester.tap(key('direct-probe')); await tester.pump(); await waitFor(tester, key('direct-trust-key'));
        await tester.tap(key('direct-trust-key')); await tester.pumpAndSettle();
        await tester.enterText(key('direct-secret'), 'temporary'); await tester.pump(); await tester.ensureVisible(key('direct-connect')); await tester.tap(key('direct-connect')); await tester.pump();
        await waitFor(tester, find.byType(TerminalView));
        await tester.tap(find.widgetWithText(TextButton, '断开')); await tester.pump();
        final confirmed = Platform.environment['HERDR_DIRECT_SSH_EXPECT_EXIT'] == '1';
        await waitFor(tester, find.text('本机已断开'));
        expect(find.text(confirmed ? '远端已报告结束，凭据已清空。重连时请重新填写。' : '凭据已清空，重连时请重新填写。'), findsOneWidget);
        expect(key('direct-closed-feedback').hitTestable(), findsOneWidget);
        expect(key('direct-return-home').hitTestable(), findsOneWidget);
        print('DESKTOP_GEOMETRY ${size.width} feedback=${tester.getRect(key('direct-closed-feedback'))} return=${tester.getRect(key('direct-return-home'))}');
        await tester.tap(key('direct-return-home')); await tester.pumpAndSettle();
        expect(key('home-ssh-closed'), findsOneWidget);
        expect(find.text('本机已断开'), findsOneWidget);
        print('DESKTOP_GEOMETRY ${size.width} home=${tester.getRect(key('home-ssh-closed'))}');
        expect(tester.takeException(), isNull); await tester.pumpWidget(const SizedBox()); catalog.dispose();
      }, variant: TargetPlatformVariant.only(TargetPlatform.linux), skip: Platform.environment['HERDR_DIRECT_SSH_FIXTURE_PORT'] == null || (chooser && size.width >= 960));
    }
  }
}
