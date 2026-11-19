import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/direct_ssh_page.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:terminal_view/terminal_view.dart';

import 'direct_ssh_widget_test.dart' show tapAndWaitForOrdinaryDisconnect, waitFor;
import 'host_catalog_test.dart' show MemoryCatalogStorage;

Finder control(String id) => find.byKey(ValueKey(id));

Future<void> tapControl(WidgetTester tester, Finder control) async {
  await tester.ensureVisible(control);
  await tester.pumpAndSettle();
  expect(control.hitTestable(), findsOneWidget);
  await tester.tap(control);
  await tester.pumpAndSettle();
}

void main() {
  final port = Platform.environment['HERDR_DIRECT_SSH_FIXTURE_PORT'];
  for (final initialWidth in [390.0, 700.0, 980.0]) {
    testWidgets('ordinary SSH keeps its shell across navigation from width $initialWidth', (tester) async {
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = Size(initialWidth, 900);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.view.resetPhysicalSize);
      final tokens = (await tester.runAsync(DesignTokens.load))!;
      final catalog = HostCatalog(storage: MemoryCatalogStorage(), clock: () => 1000);
      await catalog.load();
      await tester.pumpWidget(MaterialApp(
        theme: tokens.theme.copyWith(platform: TargetPlatform.iOS),
        home: HostCatalogPage(tokens: tokens, catalog: catalog, offlineBuilder: (_) => const SizedBox()),
      ));
      await tester.pumpAndSettle();

      final openSsh = control('hosts-direct-ssh');
      if (initialWidth >= 700) {
        await tapControl(tester, openSsh);
        await tester.binding.handlePopRoute();
        await tester.pumpAndSettle();
        expect(openSsh.hitTestable(), findsOneWidget);
        expect(find.byType(DirectSshPage, skipOffstage: false), findsNothing);
        expect(control('home-ssh-closed'), findsNothing);
      }

      await tapControl(tester, openSsh);
      await tester.enterText(control('direct-host'), '127.0.0.1');
      await tester.enterText(control('direct-port'), port!);
      await tester.enterText(control('direct-user'), 'fixture');
      await tapControl(tester, control('direct-probe'));
      await waitFor(tester, control('direct-trust-key'));
      await tapControl(tester, control('direct-trust-key'));
      await tester.enterText(control('direct-secret'), 'temporary');
      await tapControl(tester, control('direct-connect'));
      final terminal = find.byType(TerminalView).hitTestable();
      await waitFor(tester, terminal);
      final page = tester.state(find.byType(DirectSshPage));
      final shell = tester.widget<TerminalView>(terminal).terminal;

      tester.view.physicalSize = const Size(390, 844);
      await tester.pumpAndSettle();
      await tapControl(tester, control('direct-tab-board'));
      expect(openSsh.hitTestable(), findsOneWidget);
      expect(terminal, findsNothing);
      await tapControl(tester, control('home-tab-1'));
      expect(tester.widget<TerminalView>(terminal).terminal, same(shell));

      await tapControl(tester, control('direct-tab-network'));
      expect(find.text('网络配置'), findsOneWidget);
      expect(terminal, findsNothing);
      tester.view.physicalSize = Size(initialWidth == 980 ? 980 : 700, 900);
      await tester.pumpAndSettle();
      await tapControl(tester, control('ssh-flow-nav-1').hitTestable());
      expect(tester.state(find.byType(DirectSshPage)), same(page));
      expect(tester.widget<TerminalView>(terminal).terminal, same(shell));

      if (initialWidth == 980) {
        await tester.binding.handlePopRoute();
        await tester.pumpAndSettle();
        expect(tester.widget<TerminalView>(terminal).terminal, same(shell));
        await tapControl(tester, control('ssh-flow-nav-3').hitTestable());
        expect(terminal, findsNothing);
        await tester.binding.handlePopRoute();
        await tester.pumpAndSettle();
        expect(tester.widget<TerminalView>(terminal).terminal, same(shell));
      }
      await tapAndWaitForOrdinaryDisconnect(tester);
      await tapControl(tester, control('direct-return-home'));
      expect(control('home-ssh-closed').hitTestable(), findsOneWidget);
      expect(find.byType(DirectSshPage, skipOffstage: false), findsNothing);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      catalog.dispose();
    }, variant: TargetPlatformVariant.only(TargetPlatform.iOS), skip: port == null);
  }
}
