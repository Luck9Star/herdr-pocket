import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/macos_secure_credential_field.dart';
import 'package:terminal_view/terminal_view.dart';

import 'direct_ssh_host_key_change_widget_test.dart' show RotationPeer, fillTarget;
import 'direct_ssh_widget_test.dart' show mockSecureFields, tapAndWaitForOrdinaryDisconnect, waitFor;
import 'host_catalog_test.dart' show MemoryCatalogStorage;

final environment = Platform.environment;
Finder control(String id) => find.byKey(ValueKey(id));

Future<void> tapControl(WidgetTester tester, String id) async {
  final finder = control(id);
  await tester.ensureVisible(finder);
  await tester.pumpAndSettle();
  expect(finder.hitTestable(), findsOneWidget);
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

Future<void> openDesktopEntry(WidgetTester tester, int port) async {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = const Size(980, 780);
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(tester.view.resetPhysicalSize);
  final catalog = HostCatalog(storage: MemoryCatalogStorage(), clock: () => 1000);
  addTearDown(catalog.dispose);
  await catalog.load();
  final tokens = (await tester.runAsync(DesignTokens.load))!;
  await tester.pumpWidget(MaterialApp(
    theme: tokens.theme,
    home: HostCatalogPage(tokens: tokens, catalog: catalog, offlineBuilder: (_) => const SizedBox()),
  ));
  await tester.pumpAndSettle();
  await tapControl(tester, 'hosts-direct-ssh');
  expect(control('direct-secret'), findsNothing);
  await fillTarget(tester, port);
  await tapControl(tester, 'direct-probe');
  await waitFor(tester, control('direct-trust-key'));
  await tapControl(tester, 'direct-trust-key');
}

void main() {
  testWidgets('desktop uses the AppKit bridge for the password and passphrase only', (tester) async {
    mockSecureFields(tester);
    await openDesktopEntry(tester, int.parse(environment['HERDR_DIRECT_SSH_FIXTURE_PORT']!));
    final nativeField = find.byType(MacosSecureCredentialField);
    final platformView = find.byType(AppKitView);
    expect(nativeField, findsOneWidget);
    expect(platformView, findsOneWidget);
    expect(tester.widget<MacosSecureCredentialField>(nativeField).identifier, 'direct-secret');
    expect(tester.getSize(nativeField).height, 48);
    final writable = find.byWidgetPredicate((widget) => widget is EditableText && !widget.readOnly);
    expect(writable.hitTestable(), findsNothing);

    await tapControl(tester, 'direct-auth-key');
    expect(tester.widget<TextField>(control('direct-secret')).maxLines, 2);
    expect(tester.widget<MacosSecureCredentialField>(nativeField).identifier, 'direct-passphrase');
    expect(tester.getSize(nativeField).height, 48);
    expect(tester.getSize(platformView).height, 40);
    expect(find.descendant(of: nativeField, matching: find.byType(EditableText)), findsNothing);
    expect(tester.widget<FilledButton>(control('direct-connect')).onPressed, isNull);
    await tester.pumpWidget(const SizedBox());
    expect(tester.takeException(), isNull);
  }, variant: TargetPlatformVariant.only(TargetPlatform.macOS),
    skip: environment['HERDR_DIRECT_SSH_FIXTURE_PORT'] == null);

  testWidgets('desktop encrypted private key requires the PEM and passphrase before connecting', (tester) async {
    await openDesktopEntry(tester, int.parse(environment['HERDR_DIRECT_SSH_KEY_PORT']!));
    await tapControl(tester, 'direct-auth-key');
    final pem = File(environment['HERDR_DIRECT_SSH_KEY_PATH']!).readAsStringSync();
    await tester.enterText(control('direct-secret'), pem);
    await tester.pumpAndSettle();
    expect(tester.widget<FilledButton>(control('direct-connect')).onPressed, isNull);
    await tester.enterText(control('direct-passphrase'), 'fixture-passphrase');
    await tester.pumpAndSettle();
    await tapControl(tester, 'direct-connect');
    await waitFor(tester, find.byType(TerminalView));
    await tapAndWaitForOrdinaryDisconnect(tester);
    await tapControl(tester, 'direct-return-home');
    expect(control('home-ssh-closed').hitTestable(), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    expect(tester.takeException(), isNull);
  }, variant: TargetPlatformVariant.only(TargetPlatform.linux),
    skip: environment['HERDR_DIRECT_SSH_KEY_PORT'] == null || environment['HERDR_DIRECT_SSH_KEY_PATH'] == null);

  testWidgets('desktop rejects a changed key and preserves the old trust if review is cancelled', (tester) async {
    final peer = (await tester.runAsync(() => RotationPeer.start()))!;
    addTearDown(() => tester.runAsync(peer.stop));
    await openDesktopEntry(tester, peer.port);
    await tester.enterText(control('direct-secret'), 'temporary');
    await tester.pumpAndSettle();
    await tapControl(tester, 'direct-connect');
    await waitFor(tester, control('direct-host-key-change'));
    final before = tester.widget<SelectableText>(control('direct-host-key-old')).data;
    final presented = tester.widget<SelectableText>(control('direct-host-key-new')).data;
    expect(before, startsWith('SHA256:'));
    expect(presented, startsWith('SHA256:'));
    expect(presented, isNot(before));
    expect(find.byType(TerminalView), findsNothing);
    expect(control('direct-secret'), findsNothing);
    await tapControl(tester, 'direct-host-key-review');
    await waitFor(tester, control('direct-trust-key'));
    expect(find.text(presented!), findsOneWidget);
    await tapControl(tester, 'direct-trust-cancel');
    expect(control('direct-trust-preserved').hitTestable(), findsOneWidget);
    expect(control('direct-secret'), findsNothing);
    expect(control('direct-connect'), findsNothing);
    expect(peer.sawAuthentication, isFalse);
    await tester.pumpWidget(const SizedBox());
    expect(tester.takeException(), isNull);
  }, variant: TargetPlatformVariant.only(TargetPlatform.linux),
    skip: environment['HERDR_FIXTURE_PYTHON'] == null);
}
