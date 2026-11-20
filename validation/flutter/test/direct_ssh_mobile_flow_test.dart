import 'dart:io';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/direct_ssh_page.dart';
import 'package:herdr_flutter_probe/main.dart' as app;
import 'package:terminal_view/terminal_view.dart';
import 'direct_ssh_widget_test.dart' show tapAndWaitForOrdinaryDisconnect, mockClipboard, waitFor;

void main() {
  for (final width in [320.0, 390.0]) {
    testWidgets('mobile target, explicit review and credential clearing at $width', (tester) async {
      final port = Platform.environment['HERDR_DIRECT_SSH_FIXTURE_PORT']!;
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = Size(width, width == 320 ? 640 : 844);
      final inset = width == 320 ? const FakeViewPadding(top: 24, bottom: 24) : const FakeViewPadding(top: 47, bottom: 34);
      tester.view.padding = inset; tester.view.viewPadding = inset;
      addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetPadding); addTearDown(tester.view.resetViewPadding);
      final tokens = (await tester.runAsync(DesignTokens.load))!;
      await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: Builder(builder: (context) => Scaffold(
        body: TextButton(onPressed: () => Navigator.push<void>(context, MaterialPageRoute(builder: (_) => DirectSshPage(tokens: tokens))),
          child: const Text('打开'))))));
      await tester.tap(find.text('打开')); await tester.pumpAndSettle();
      Finder key(String value) => find.byKey(ValueKey(value));
      expect(key('direct-secret'), findsNothing);
      expect(tester.widget<FilledButton>(key('direct-probe')).onPressed, isNull);
      await tester.enterText(key('direct-host'), '127.0.0.1');
      await tester.enterText(key('direct-port'), port);
      await tester.enterText(key('direct-user'), 'fixture'); await tester.pump();
      await tester.tap(key('direct-probe')); await tester.pump(); await waitFor(tester, key('direct-trust-key')); await tester.pumpAndSettle();
      expect(key('direct-secret'), findsNothing);
      expect(tester.widget<SelectableText>(key('direct-target-value')).data, 'fixture@127.0.0.1:$port');
      expect(tester.widget<SelectableText>(key('direct-key-algorithm')).data, isNotEmpty);
      expect(tester.widget<SelectableText>(key('direct-key-fingerprint')).data, startsWith('SHA256:'));
      await tester.tap(key('direct-trust-cancel')); await tester.pumpAndSettle();
      expect(key('direct-secret'), findsNothing);
      final dynamic state = tester.state(find.byType(DirectSshPage));
      expect(state.fingerprint, isNull);
      await tester.tap(key('direct-probe')); await tester.pump(); await waitFor(tester, key('direct-trust-key')); await tester.pumpAndSettle();
      await tester.tap(key('direct-trust-key')); await tester.pumpAndSettle();
      expect(key('direct-secret'), findsOneWidget);
      expect(tester.widget<FilledButton>(key('direct-connect')).onPressed, isNull);
      await tester.enterText(key('direct-secret'), '   '); await tester.pump();
      expect(tester.widget<TextField>(key('direct-secret')).controller!.text, '   ');
      expect(tester.widget<FilledButton>(key('direct-connect')).onPressed, isNotNull);
      // Do not submit the whitespace credential to the fixture.
      await tester.enterText(key('direct-secret'), 'temporary'); await tester.pump();
      expect(tester.widget<FilledButton>(key('direct-connect')).onPressed, isNotNull);
      await tester.tap(key('direct-auth-key')); await tester.pumpAndSettle();
      expect(tester.widget<TextField>(key('direct-secret')).controller!.text, isEmpty);
      await tester.tap(key('direct-secret')); await tester.pumpAndSettle();
      await tester.enterText(key('direct-secret'), 'synthetic-key'); await tester.pump();
      expect(tester.widget<FilledButton>(key('direct-connect')).onPressed, isNull);
      await tester.enterText(key('direct-secret'), '-----BEGIN PRIVATE KEY-----\n${base64Encode(List.filled(48, 65))}\n-----END PRIVATE KEY-----'); await tester.pump();
      expect(tester.widget<FilledButton>(key('direct-connect')).onPressed, isNotNull);
      await tester.ensureVisible(key('direct-passphrase'));
      await tester.enterText(key('direct-passphrase'), 'synthetic-phrase');
      await tester.tap(key('direct-auth-password')); await tester.pumpAndSettle();
      expect(state.secret.text, isEmpty); expect(state.passphrase.text, isEmpty);
      await tester.enterText(key('direct-secret'), 'temporary');
      await tester.tap(find.byType(BackButton)); await tester.pumpAndSettle();
      expect(key('direct-secret'), findsNothing); expect(state.secret.text, isEmpty);
      await tester.tap(key('direct-probe')); await tester.pump(); await waitFor(tester, key('direct-trust-key')); await tester.pumpAndSettle();
      await tester.tap(key('direct-trust-key')); await tester.pumpAndSettle();
      await tester.enterText(key('direct-secret'), 'temporary'); await tester.pump();
      await tester.ensureVisible(key('direct-connect')); await tester.tap(key('direct-connect')); await tester.pump();
      await waitFor(tester, find.byType(TerminalView));
      expect(state.secret.text, isEmpty); expect(state.passphrase.text, isEmpty);
      await tapAndWaitForOrdinaryDisconnect(tester);
      expect(key('direct-secret'), findsNothing); expect(state.secret.text, isEmpty);
      await tester.enterText(key('direct-host'), 'changed.invalid'); await tester.pump();
      expect(state.fingerprint, isNull); expect(state.checkedTarget, isNull);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    }, variant: TargetPlatformVariant.only(TargetPlatform.iOS),
      skip: Platform.environment['HERDR_DIRECT_SSH_FIXTURE_PORT'] == null);
  }
  for (final mode in ['PLAIN', 'ENCRYPTED']) {
    testWidgets('mobile $mode key authenticates to isolated shell', (tester) async {
      final port = Platform.environment['HERDR_MOBILE_${mode}_PORT']!;
      final keyPath = Platform.environment['HERDR_MOBILE_${mode}_KEY']!;
      tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(390, 844);
      addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
      final tokens = (await tester.runAsync(DesignTokens.load))!;
      await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: DirectSshPage(tokens: tokens)));
      Finder key(String id) => find.byKey(ValueKey(id));
      await tester.enterText(key('direct-host'), '127.0.0.1');
      await tester.enterText(key('direct-port'), port); await tester.enterText(key('direct-user'), 'fixture'); await tester.pump();
      await tester.tap(key('direct-probe')); await tester.pump(); await waitFor(tester, key('direct-trust-key'));
      await tester.pumpAndSettle(); await tester.tap(key('direct-trust-key')); await tester.pumpAndSettle();
      await tester.tap(key('direct-auth-key')); await tester.pumpAndSettle();
      await tester.enterText(key('direct-secret'), File(keyPath).readAsStringSync());
      if (mode == 'ENCRYPTED') {
        await tester.pump(); expect(tester.widget<FilledButton>(key('direct-connect')).onPressed, isNull);
        await tester.enterText(key('direct-passphrase'), 'wrong-passphrase'); await tester.pump();
        await tester.ensureVisible(key('direct-connect')); await tester.tap(key('direct-connect')); await tester.pumpAndSettle();
        final dynamic state = tester.state(find.byType(DirectSshPage));
        expect(state.connectFailure, DirectSshConnectFailure.keyParse);
        expect(state.secret.text, isEmpty); expect(state.passphrase.text, isEmpty);
        expect(find.textContaining('私钥无法解析或解密'), findsOneWidget);
        await tester.enterText(key('direct-secret'), File(keyPath).readAsStringSync());
        await tester.enterText(key('direct-passphrase'), 'fixture-passphrase');
      }
      await tester.pump(); expect(tester.widget<FilledButton>(key('direct-connect')).onPressed, isNotNull);
      await tester.ensureVisible(key('direct-connect')); await tester.tap(key('direct-connect')); await tester.pump();
      await waitFor(tester, find.byType(TerminalView));
      final dynamic state = tester.state(find.byType(DirectSshPage));
      expect(state.secret.text, isEmpty); expect(state.passphrase.text, isEmpty);
      await tapAndWaitForOrdinaryDisconnect(tester);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    }, variant: TargetPlatformVariant.only(TargetPlatform.iOS),
      skip: Platform.environment['HERDR_MOBILE_${mode}_PORT'] == null || Platform.environment['HERDR_MOBILE_${mode}_KEY'] == null);
  }

  testWidgets('Android encrypted retry retains the credential and connect elements after paste notice clears', (tester) async {
    final port = Platform.environment['HERDR_MOBILE_ENCRYPTED_PORT']!;
    final privateKey = File(Platform.environment['HERDR_MOBILE_ENCRYPTED_KEY']!).readAsStringSync();
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(393, 851);
    tester.view.padding = const FakeViewPadding(top: 24, bottom: 24);
    tester.view.viewPadding = const FakeViewPadding(top: 24, bottom: 24);
    addTearDown(tester.view.reset);
    mockClipboard(tester, () async => {'text': privateKey});
    Finder key(String name) => find.byKey(ValueKey(name));
    Future<void> tap(String name) async {
      await tester.ensureVisible(key(name));
      await tester.tap(key(name));
      await tester.pumpAndSettle();
    }

    await tester.runAsync(app.main);
    await tester.pumpAndSettle();
    await tap('hosts-direct-ssh');
    for (final field in {'direct-host': '127.0.0.1', 'direct-user': 'fixture', 'direct-port': port}.entries) {
      await tester.enterText(key(field.key), field.value);
      await tester.pump();
    }
    await tap('direct-probe');
    await waitFor(tester, key('direct-trust-key'));
    final fingerprint = tester.widget<SelectableText>(key('direct-key-fingerprint')).data;
    expect(fingerprint, startsWith('SHA256:'));
    await tap('direct-trust-key');
    await tap('direct-auth-key');
    await tap('direct-paste-key');
    final passphrase = key('direct-passphrase');
    final connect = key('direct-connect');
    await tester.ensureVisible(passphrase);
    await tester.enterText(passphrase, 'wrong-passphrase');
    await tester.pump();
    await tap('direct-connect');
    final dynamic state = tester.state(find.byType(DirectSshPage));
    expect(state.connectFailure, DirectSshConnectFailure.keyParse);
    expect(state.secret.text.isEmpty && state.passphrase.text.isEmpty, isTrue);

    await tap('direct-paste-key');
    expect(key('direct-paste-status'), findsOneWidget);
    await tester.ensureVisible(passphrase);
    final editing = tester.element(passphrase);
    final button = tester.element(connect);
    final withNotice = tester.getTopLeft(connect).dy;
    await tester.enterText(passphrase, 'fixture-passphrase');
    await tester.pump();
    expect(tester.view.viewInsets.bottom, 0);
    expect(key('direct-paste-status'), findsNothing);
    expect(tester.element(connect), same(button));
    expect(tester.element(passphrase), same(editing));
    expect(tester.widget<EditableText>(find.descendant(of: passphrase, matching: find.byType(EditableText))).focusNode.hasFocus, isTrue);
    expect(tester.getTopLeft(connect).dy, lessThan(withNotice));
    expect(tester.widget<FilledButton>(connect).onPressed, isNotNull);
    final target = 'fixture@127.0.0.1:$port';
    expect(state.checkedTarget, target);
    expect(state.fingerprint, fingerprint);
    await tester.tap(connect);
    await tester.pump();
    await waitFor(tester, find.byType(TerminalView));
    expect(state.activeTarget, target);
    expect(state.connectHostKeyMatched, isTrue);
    expect(state.secret.text.isEmpty && state.passphrase.text.isEmpty, isTrue);
    await tapAndWaitForOrdinaryDisconnect(tester);
    expect(tester.takeException(), isNull);
  }, variant: TargetPlatformVariant.only(TargetPlatform.android),
    skip: Platform.environment['HERDR_MOBILE_ENCRYPTED_PORT'] == null || Platform.environment['HERDR_MOBILE_ENCRYPTED_KEY'] == null);

  testWidgets('mobile changed-key view keeps distinct algorithms and locks credentials', (tester) async {
    tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(390, 844);
    addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: DirectSshPage(tokens: tokens)));
    final dynamic state = tester.state(find.byType(DirectSshPage));
    const oldKey = 'SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';
    const newKey = 'SHA256:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB';
    state.setState(() { state.host.text = 'example.test'; state.user.text = 'demo';
      state.fingerprint = oldKey; state.algorithm = 'ssh-rsa'; state.checkedTarget = state.target; });
    state.showHostKeyChange('ssh-rsa', oldKey, 'ssh-ed25519', newKey, state.target);
    await tester.pumpAndSettle();
    expect(find.textContaining('ssh-rsa'), findsOneWidget);
    expect(find.textContaining('ssh-ed25519'), findsOneWidget);
    expect(tester.widget<SelectableText>(find.byKey(const ValueKey('direct-host-key-old'))).data, oldKey);
    expect(tester.widget<SelectableText>(find.byKey(const ValueKey('direct-host-key-new'))).data, newKey);
    expect(find.byType(BackButton), findsNothing);
    await tester.ensureVisible(find.byKey(const ValueKey('direct-host-key-cancel')));
    await tester.tap(find.byKey(const ValueKey('direct-host-key-cancel'))); await tester.pumpAndSettle();
    expect(state.fingerprint, oldKey); expect(state.hostKeyReviewRequired, isTrue);
    expect(find.byKey(const ValueKey('direct-secret')), findsNothing);
    expect(find.byKey(const ValueKey('direct-connect')), findsNothing);
    expect(find.byKey(const ValueKey('direct-probe')), findsOneWidget);
    expect(tester.takeException(), isNull);
  }, variant: TargetPlatformVariant.only(TargetPlatform.iOS));

}
