import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:terminal_view/terminal_view.dart';
import 'direct_ssh_widget_test.dart' show tapAndWaitForOrdinaryDisconnect, waitFor;
import 'host_catalog_test.dart' show MemoryCatalogStorage;
import 'host_tabs_widget_test.dart' show tabProfile;

void main() {
  for (final saved in [false, true]) {
    testWidgets('only a user-disconnected shell reports once on ${saved ? 'saved-host' : 'empty'} board', (tester) async {
      final port = Platform.environment['HERDR_DIRECT_SSH_FIXTURE_PORT']!;
      tester.view.devicePixelRatio = 1; tester.view.physicalSize = saved ? const Size(390, 844) : const Size(320, 640);
      final inset = saved ? const FakeViewPadding(top: 47, bottom: 34) : const FakeViewPadding(top: 24, bottom: 24);
      tester.view.padding = inset; tester.view.viewPadding = inset;
      addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetPadding); addTearDown(tester.view.resetViewPadding);
      final tokens = (await tester.runAsync(DesignTokens.load))!;
      final catalog = HostCatalog(storage: MemoryCatalogStorage(), clock: () => 1000);
      await catalog.load();
      if (saved) await catalog.add(tabProfile('Saved host', 'session', '127.0.0.1', 'direct', 'fixture'));
      await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: HostCatalogPage(
        tokens: tokens, catalog: catalog, offlineBuilder: (_) => const SizedBox())));
      await tester.pumpAndSettle();
      Finder key(String id) => find.byKey(ValueKey(id));
      Future<void> open() async { await tester.ensureVisible(key('hosts-direct-ssh')); await tester.pumpAndSettle();
        await tester.tap(key('hosts-direct-ssh')); await tester.pumpAndSettle(); }
      await open();
      // Back before any connection is not a disconnect notification.
      await tester.tap(find.byType(BackButton)); await tester.pumpAndSettle();
      expect(key('home-ssh-closed'), findsNothing);
      await open();
      await tester.enterText(key('direct-host'), '127.0.0.1'); await tester.enterText(key('direct-port'), port);
      await tester.enterText(key('direct-user'), 'fixture'); await tester.pump();
      await tester.tap(key('direct-probe')); await tester.pump(); await waitFor(tester, key('direct-trust-key')); await tester.pumpAndSettle();
      // Refusing the probe also cannot create a disconnect notification.
      await tester.tap(key('direct-trust-cancel')); await tester.pumpAndSettle();
      await tester.tap(find.byType(BackButton)); await tester.pumpAndSettle();
      expect(key('home-ssh-closed'), findsNothing);
      await open();
      await tester.enterText(key('direct-host'), '127.0.0.1'); await tester.enterText(key('direct-port'), port);
      await tester.enterText(key('direct-user'), 'fixture'); await tester.pump();
      await tester.tap(key('direct-probe')); await tester.pump(); await waitFor(tester, key('direct-trust-key')); await tester.pumpAndSettle();
      await tester.tap(key('direct-trust-key')); await tester.pumpAndSettle();
      await tester.enterText(key('direct-secret'), 'wrong-password'); await tester.pump();
      await tester.ensureVisible(key('direct-connect')); await tester.tap(key('direct-connect')); await tester.pump();
      await waitFor(tester, find.text('认证失败，请检查凭据。'));
      await tester.tap(find.byType(BackButton)); await tester.pumpAndSettle();
      await tester.tap(find.byType(BackButton)); await tester.pumpAndSettle();
      expect(key('home-ssh-closed'), findsNothing);
      await open();
      await tester.enterText(key('direct-host'), '127.0.0.1'); await tester.enterText(key('direct-port'), port);
      await tester.enterText(key('direct-user'), 'fixture'); await tester.pump();
      await tester.tap(key('direct-probe')); await tester.pump(); await waitFor(tester, key('direct-trust-key')); await tester.pumpAndSettle();
      await tester.tap(key('direct-trust-key')); await tester.pumpAndSettle();
      await tester.enterText(key('direct-secret'), 'temporary'); await tester.pump();
      await tester.ensureVisible(key('direct-connect')); await tester.tap(key('direct-connect')); await tester.pump();
      await waitFor(tester, find.byType(TerminalView));
      await tapAndWaitForOrdinaryDisconnect(tester);
      expect(key('direct-closed-feedback'), findsOneWidget); expect(key('direct-secret'), findsNothing);
      expect(tester.widget<TextField>(key('direct-host')).controller!.text, '127.0.0.1');
      expect(tester.widget<TextField>(key('direct-user')).controller!.text, 'fixture');
      expect(tester.widget<TextField>(key('direct-port')).controller!.text, port);
      if (saved) {
        // A new probe supersedes the earlier disconnect; cancelling it must not report that old event.
        await tester.ensureVisible(key('direct-probe')); await tester.tap(key('direct-probe')); await tester.pump();
        await waitFor(tester, key('direct-trust-key')); await tester.pumpAndSettle();
        await tester.tap(key('direct-trust-cancel')); await tester.pumpAndSettle();
        await tester.tap(find.byType(BackButton)); await tester.pumpAndSettle();
        expect(key('home-ssh-closed'), findsNothing);
        await open();
        await tester.enterText(key('direct-host'), '127.0.0.1'); await tester.enterText(key('direct-port'), port);
        await tester.enterText(key('direct-user'), 'fixture'); await tester.pump();
        await tester.tap(key('direct-probe')); await tester.pump(); await waitFor(tester, key('direct-trust-key')); await tester.pumpAndSettle();
        await tester.tap(key('direct-trust-key')); await tester.pumpAndSettle();
        await tester.enterText(key('direct-secret'), 'temporary'); await tester.pump();
        await tester.ensureVisible(key('direct-connect')); await tester.tap(key('direct-connect')); await tester.pump();
        await waitFor(tester, find.byType(TerminalView));
        await tapAndWaitForOrdinaryDisconnect(tester);
      }
      await tester.ensureVisible(key('direct-return-home')); await tester.pumpAndSettle();
      expect(key('direct-return-home').hitTestable(), findsOneWidget);
      if (saved) { await tester.binding.handlePopRoute(); } else { await tester.tap(key('direct-return-home')); }
      await tester.pumpAndSettle();
      expect(key('home-ssh-closed'), findsOneWidget);
      expect(find.text('本机已断开'), findsOneWidget);
      expect(find.text('本机连接关闭失败'), findsNothing);
      if (saved) {
        expect(find.text('Saved host'), findsOneWidget);
        await tester.ensureVisible(key('hosts-add')); await tester.tap(key('hosts-add')); await tester.pumpAndSettle();
        expect(find.text('设备配对'), findsOneWidget);
        await tester.pageBack(); await tester.pumpAndSettle();
      } else {
        await tester.tap(find.text('设置').last); await tester.pumpAndSettle();
        await tester.tap(find.text('看板').last); await tester.pumpAndSettle();
      }
      expect(key('home-ssh-closed'), findsNothing);
      expect(tester.takeException(), isNull); await tester.pumpWidget(const SizedBox()); catalog.dispose();
    }, variant: TargetPlatformVariant({TargetPlatform.iOS, TargetPlatform.android}),
      skip: Platform.environment['HERDR_DIRECT_SSH_FIXTURE_PORT'] == null);
  }
  for (final saved in [false, true]) {
    testWidgets('iOS edge swipe commits disconnect only when completed from ${saved ? 'saved board' : 'connection chooser'}', (tester) async {
      final port = Platform.environment['HERDR_DIRECT_SSH_FIXTURE_PORT']!;
      tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(390, 844);
      tester.view.padding = const FakeViewPadding(top: 47, bottom: 34);
      tester.view.viewPadding = const FakeViewPadding(top: 47, bottom: 34);
      addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetPadding); addTearDown(tester.view.resetViewPadding);
      final tokens = (await tester.runAsync(DesignTokens.load))!;
      final catalog = HostCatalog(storage: MemoryCatalogStorage(), clock: () => 1000);
      await catalog.load();
      if (saved) await catalog.add(tabProfile('Saved host', 'session', '127.0.0.1', 'direct', 'fixture'));
      await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: HostCatalogPage(
        tokens: tokens, catalog: catalog, offlineBuilder: (_) => const SizedBox())));
      await tester.pumpAndSettle();
      Finder key(String id) => find.byKey(ValueKey(id));
      Future<void> open() async {
        if (saved) {
          await tester.ensureVisible(key('hosts-direct-ssh')); await tester.pumpAndSettle();
          await tester.tap(key('hosts-direct-ssh'));
        } else {
          await tester.tap(key('hosts-add')); await tester.pumpAndSettle();
          await tester.tap(key('choose-ssh'));
        }
        await tester.pumpAndSettle();
      }
      Future<void> edgeDrag(double distance) async {
        final gesture = await tester.startGesture(const Offset(1, 350));
        await tester.pump(); await gesture.moveBy(const Offset(20, 0)); await tester.pump();
        expect(Navigator.of(tester.element(key('direct-form'))).userGestureInProgress, isTrue);
        await gesture.moveBy(Offset(distance - 20, 0));
        await tester.pump(const Duration(milliseconds: 300));
        await gesture.up(); await tester.pumpAndSettle();
      }
      final dynamic homeState = tester.state(find.byType(HostCatalogPage, skipOffstage: false));
      // A completed edge swipe before connecting must not report a disconnect.
      await open(); await edgeDrag(320);
      expect(key('direct-form'), findsNothing); expect(key('home-ssh-closed'), findsNothing);
      expect(homeState.sshClosedNotice, isFalse);
      await open();
      await tester.enterText(key('direct-host'), '127.0.0.1'); await tester.enterText(key('direct-port'), port);
      await tester.enterText(key('direct-user'), 'fixture'); await tester.pump();
      await tester.tap(key('direct-probe')); await tester.pump(); await waitFor(tester, key('direct-trust-key')); await tester.pumpAndSettle();
      await tester.tap(key('direct-trust-key')); await tester.pumpAndSettle();
      await tester.enterText(key('direct-secret'), 'temporary'); await tester.pump();
      await tester.ensureVisible(key('direct-connect')); await tester.tap(key('direct-connect')); await tester.pump();
      await waitFor(tester, find.byType(TerminalView));
      await tapAndWaitForOrdinaryDisconnect(tester);
      expect(key('direct-closed-feedback'), findsOneWidget);
      // A short drag is cancelled: the route remains and the home notice is not emitted.
      await edgeDrag(35);
      expect(key('direct-closed-feedback'), findsOneWidget);
      expect(key('home-ssh-closed'), findsNothing); expect(homeState.sshClosedNotice, isFalse);
      await edgeDrag(320);
      expect(key('direct-form'), findsNothing); expect(key('home-ssh-closed'), findsOneWidget);
      expect(homeState.sshClosedNotice, isTrue); expect(homeState.sshClosedSucceeded, isTrue);
      expect(find.text('本机已断开'), findsOneWidget);
      if (saved) expect(find.text('Saved host'), findsOneWidget);
      await tester.tap(find.text('设置').last); await tester.pumpAndSettle();
      await tester.tap(find.text('看板').last); await tester.pumpAndSettle();
      expect(key('home-ssh-closed'), findsNothing);
      expect(tester.takeException(), isNull); await tester.pumpWidget(const SizedBox()); catalog.dispose();
    }, variant: TargetPlatformVariant.only(TargetPlatform.iOS),
      skip: Platform.environment['HERDR_DIRECT_SSH_FIXTURE_PORT'] == null);
  }
  testWidgets('a failed local disconnect keeps its failure on the home board', (tester) async {
    tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(390, 844);
    addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    final catalog = HostCatalog(storage: MemoryCatalogStorage(), clock: () => 1000); await catalog.load();
    await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: HostCatalogPage(
      tokens: tokens, catalog: catalog, offlineBuilder: (_) => const SizedBox())));
    await tester.pumpAndSettle();
    final dynamic homeState = tester.state(find.byType(HostCatalogPage));
    homeState.setState(() { homeState.sshClosedNotice = true; homeState.sshClosedSucceeded = false; });
    await tester.pumpAndSettle();
    expect(find.text('本机连接关闭失败'), findsOneWidget);
    expect(find.text('会话可能仍在。'), findsOneWidget);
    expect(find.text('会话可能仍在。可返回首页。'), findsNothing);
    expect(find.text('本机已断开'), findsNothing);
    expect(tester.takeException(), isNull); await tester.pumpWidget(const SizedBox()); catalog.dispose();
  }, variant: TargetPlatformVariant({TargetPlatform.iOS, TargetPlatform.android}));
}
