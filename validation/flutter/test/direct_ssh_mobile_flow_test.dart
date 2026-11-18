import 'dart:io';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/direct_ssh_page.dart';
import 'package:terminal_view/terminal_view.dart';
import 'direct_ssh_widget_test.dart' show waitFor;

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
      await tester.tap(find.text('断开')); await tester.pumpAndSettle();
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
      await tester.tap(find.text('断开')); await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    }, variant: TargetPlatformVariant.only(TargetPlatform.iOS),
      skip: Platform.environment['HERDR_MOBILE_${mode}_PORT'] == null || Platform.environment['HERDR_MOBILE_${mode}_KEY'] == null);
  }

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
