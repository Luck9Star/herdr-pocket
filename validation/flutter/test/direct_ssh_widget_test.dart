import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/direct_ssh_page.dart';
import 'package:terminal_view/terminal_view.dart';

Future<void> waitFor(WidgetTester tester, Finder finder) async {
  for (var i = 0; i < 120 && finder.evaluate().isEmpty; i++) {
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
    await tester.pump();
  }
  expect(finder, findsOneWidget);
}

void main() {
  testWidgets('ordinary SSH requires explicit fingerprint confirmation', (tester) async {
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: DirectSshPage(tokens: tokens)));
    expect(tester.widget<OutlinedButton>(find.byKey(const ValueKey('direct-probe'))).onPressed, isNull);
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('direct-connect'))).onPressed, isNull);
    await tester.enterText(find.byKey(const ValueKey('direct-host')), '127.0.0.1');
    await tester.enterText(find.byKey(const ValueKey('direct-user')), 'fixture');
    await tester.pump();
    expect(tester.widget<OutlinedButton>(find.byKey(const ValueKey('direct-probe'))).onPressed, isNotNull);
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('direct-connect'))).onPressed, isNull);
  });

  testWidgets('loopback probe, confirm, password, PTY and background disconnect', (tester) async {
    final fixturePort = Platform.environment['HERDR_DIRECT_SSH_FIXTURE_PORT'];
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: DirectSshPage(tokens: tokens)));
    await tester.enterText(find.byKey(const ValueKey('direct-host')), '127.0.0.1');
    await tester.enterText(find.byKey(const ValueKey('direct-port')), fixturePort!);
    await tester.enterText(find.byKey(const ValueKey('direct-user')), 'fixture');
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('direct-probe'))); await tester.pump();
    await waitFor(tester, find.byKey(const ValueKey('direct-trust-key')));
    expect(find.textContaining('SHA256:'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('direct-trust-key'))); await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('direct-secret')), 'temporary');
    await tester.scrollUntilVisible(find.byKey(const ValueKey('direct-connect')), 200, scrollable: find.descendant(of: find.byKey(const ValueKey('direct-form')), matching: find.byType(Scrollable)).first);
    await tester.tap(find.byKey(const ValueKey('direct-connect'))); await tester.pump();
    await waitFor(tester, find.byType(TerminalView));
    final terminal = tester.widget<TerminalView>(find.byType(TerminalView)).terminal;
    terminal.textInput('你好\n');
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 150)));
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive); await tester.pump();
    expect(find.textContaining('应用进入后台'), findsOneWidget);
    expect(find.byType(TerminalView), findsNothing);
    await tester.pumpWidget(const SizedBox());
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
  }, skip: Platform.environment['HERDR_DIRECT_SSH_FIXTURE_PORT'] == null);
  testWidgets('changed host key blocks the second connection before authentication', (tester) async {
    final fixturePort = Platform.environment['HERDR_DIRECT_SSH_ROTATE_PORT']!;
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: DirectSshPage(tokens: tokens)));
    await tester.enterText(find.byKey(const ValueKey('direct-host')), '127.0.0.1');
    await tester.enterText(find.byKey(const ValueKey('direct-port')), fixturePort);
    await tester.enterText(find.byKey(const ValueKey('direct-user')), 'fixture'); await tester.pump();
    await tester.tap(find.byKey(const ValueKey('direct-probe'))); await tester.pump();
    await waitFor(tester, find.byKey(const ValueKey('direct-trust-key')));
    await tester.tap(find.byKey(const ValueKey('direct-trust-key'))); await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('direct-secret')), 'temporary');
    await tester.scrollUntilVisible(find.byKey(const ValueKey('direct-connect')), 200, scrollable: find.descendant(of: find.byKey(const ValueKey('direct-form')), matching: find.byType(Scrollable)).first);
    await tester.tap(find.byKey(const ValueKey('direct-connect'))); await tester.pump();
    await waitFor(tester, find.textContaining('主机密钥不符'));
    expect(find.byType(TerminalView), findsNothing);
    expect(tester.widget<TextField>(find.byKey(const ValueKey('direct-secret'))).controller!.text, isEmpty);
  }, skip: Platform.environment['HERDR_DIRECT_SSH_ROTATE_PORT'] == null);

  testWidgets('encrypted private key authenticates to the isolated shell', (tester) async {
    final fixturePort = Platform.environment['HERDR_DIRECT_SSH_KEY_PORT']!;
    final keyPath = Platform.environment['HERDR_DIRECT_SSH_KEY_PATH']!;
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    final key = await tester.runAsync(() => File(keyPath).readAsString());
    await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: DirectSshPage(tokens: tokens)));
    await tester.enterText(find.byKey(const ValueKey('direct-host')), '127.0.0.1');
    await tester.enterText(find.byKey(const ValueKey('direct-port')), fixturePort);
    await tester.enterText(find.byKey(const ValueKey('direct-user')), 'fixture'); await tester.pump();
    await tester.tap(find.byKey(const ValueKey('direct-probe'))); await tester.pump();
    await waitFor(tester, find.byKey(const ValueKey('direct-trust-key')));
    await tester.tap(find.byKey(const ValueKey('direct-trust-key'))); await tester.pumpAndSettle();
    await tester.tap(find.byType(SwitchListTile)); await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('direct-secret')), key!);
    await tester.enterText(find.byKey(const ValueKey('direct-passphrase')), 'fixture-passphrase');
    await tester.scrollUntilVisible(find.byKey(const ValueKey('direct-connect')), 200, scrollable: find.descendant(of: find.byKey(const ValueKey('direct-form')), matching: find.byType(Scrollable)).first);
    await tester.tap(find.byKey(const ValueKey('direct-connect'))); await tester.pump();
    await waitFor(tester, find.byType(TerminalView));
    await tester.pumpWidget(const SizedBox());
  }, skip: Platform.environment['HERDR_DIRECT_SSH_KEY_PORT'] == null || Platform.environment['HERDR_DIRECT_SSH_KEY_PATH'] == null);

}
