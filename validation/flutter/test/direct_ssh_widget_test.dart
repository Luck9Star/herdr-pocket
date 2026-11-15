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

  testWidgets('returning from ordinary SSH with unsubmitted credentials disposes its listeners safely', (tester) async {
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: Builder(builder: (context) => Scaffold(
      body: FilledButton(onPressed: () => Navigator.push<void>(context, MaterialPageRoute<void>(
        builder: (_) => DirectSshPage(tokens: tokens))), child: const Text('Open ordinary SSH'))))));
    await tester.tap(find.text('Open ordinary SSH')); await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('direct-secret')), 'unsubmitted-temporary-credential');
    await tester.pump();
    await tester.tap(find.byType(BackButton)); await tester.pumpAndSettle();
    expect(find.byType(DirectSshPage), findsNothing); expect(find.text('Open ordinary SSH'), findsOneWidget);
    expect(tester.takeException(), isNull);
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
    final connect = find.byKey(const ValueKey('direct-connect'));
    expect(tester.widget<FilledButton>(connect).onPressed, isNull);
    await tester.enterText(find.byKey(const ValueKey('direct-secret')), 'temporary'); await tester.pump();
    expect(tester.widget<FilledButton>(connect).onPressed, isNotNull);
    await tester.enterText(find.byKey(const ValueKey('direct-secret')), ''); await tester.pump();
    expect(tester.widget<FilledButton>(connect).onPressed, isNull);
    await tester.ensureVisible(find.byType(SwitchListTile)); await tester.pumpAndSettle();
    await tester.tap(find.byType(SwitchListTile)); await tester.pumpAndSettle();
    expect(tester.widget<FilledButton>(connect).onPressed, isNull);
    await tester.ensureVisible(find.byType(SwitchListTile)); await tester.pumpAndSettle();
    await tester.tap(find.byType(SwitchListTile)); await tester.pumpAndSettle();
    expect(tester.widget<FilledButton>(connect).onPressed, isNull);
    await tester.enterText(find.byKey(const ValueKey('direct-secret')), 'temporary'); await tester.pump();
    await tester.ensureVisible(find.byKey(const ValueKey('direct-connect')));
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
    await tester.enterText(find.byKey(const ValueKey('direct-secret')), 'temporary'); await tester.pump();
    await tester.ensureVisible(find.byKey(const ValueKey('direct-connect')));
    await tester.pump();
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('direct-connect'))).onPressed, isNotNull);
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
    await tester.ensureVisible(find.byType(SwitchListTile)); await tester.pumpAndSettle();
    await tester.tap(find.byType(SwitchListTile)); await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('direct-secret')), key!);
    await tester.enterText(find.byKey(const ValueKey('direct-passphrase')), 'fixture-passphrase'); await tester.pump();
    await tester.ensureVisible(find.byKey(const ValueKey('direct-connect')));
    await tester.pump();
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('direct-connect'))).onPressed, isNotNull);
    await tester.tap(find.byKey(const ValueKey('direct-connect'))); await tester.pump();
    await waitFor(tester, find.byType(TerminalView));
    await tester.pumpWidget(const SizedBox());
  }, skip: Platform.environment['HERDR_DIRECT_SSH_KEY_PORT'] == null || Platform.environment['HERDR_DIRECT_SSH_KEY_PATH'] == null);

  testWidgets('ordinary SSH form constrains width and exposes named editable fields', (tester) async {
    final semantics = tester.ensureSemantics();
    tester.view.physicalSize = const Size(800, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: DirectSshPage(tokens: tokens)));
    for (final item in {'direct-host':'地址', 'direct-port':'端口', 'direct-user':'用户名', 'direct-secret':'密码（仅本次使用）'}.entries) {
      final semanticField=find.bySemanticsLabel(item.value);
      expect(semanticField, findsOneWidget);
      expect(tester.getSemantics(semanticField).flagsCollection.isTextField, isTrue);
      expect(tester.getSize(find.byKey(ValueKey(item.key))).width, lessThanOrEqualTo(560));
    }
    await tester.enterText(find.byKey(const ValueKey('direct-host')), 'fixture.example');
    await tester.enterText(find.byKey(const ValueKey('direct-user')), 'fixture');
    await tester.pump();
    final host = tester.getRect(find.byKey(const ValueKey('direct-host')));
    final port = tester.getRect(find.byKey(const ValueKey('direct-port')));
    final user = tester.getRect(find.byKey(const ValueKey('direct-user')));
    expect(port.top - host.bottom, greaterThanOrEqualTo(16));
    expect(user.top - port.bottom, greaterThanOrEqualTo(16));
    expect(find.text('fixture.example'), findsOneWidget);
    expect(tester.takeException(), isNull);
    semantics.dispose();
  });

  for (final width in [320.0, 390.0]) {
    testWidgets('ordinary SSH controls remain reachable at width $width with keyboard inset', (tester) async {
      final semantics = tester.ensureSemantics();
        tester.view.physicalSize = Size(width, 844);
      tester.view.devicePixelRatio = 1;
      tester.view.viewInsets = const FakeViewPadding(bottom: 300);
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.view.resetViewInsets);
      final tokens = (await tester.runAsync(DesignTokens.load))!;
      await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: DirectSshPage(tokens: tokens)));
      for (final id in ['direct-host','direct-port','direct-user','direct-probe','direct-secret','direct-connect']) {
        final field=find.byKey(ValueKey(id));
        await tester.ensureVisible(field);await tester.pumpAndSettle();
        expect(tester.getRect(field).intersect(Rect.fromLTWH(0, 0, width, 544)).height, greaterThan(0));
      }
      await tester.ensureVisible(find.byType(SwitchListTile));await tester.pumpAndSettle();
      await tester.tap(find.byType(SwitchListTile));await tester.pumpAndSettle();
      final phrase=find.byKey(const ValueKey('direct-passphrase'));
      await tester.ensureVisible(phrase);await tester.pumpAndSettle();
      expect(find.bySemanticsLabel('私钥口令（可选）'), findsWidgets);
      expect(tester.takeException(), isNull);
      semantics.dispose();
    });
  }

  testWidgets('probe error remains readable and fields retain accessible names', (tester) async {
    final semantics=tester.ensureSemantics();
    final socket=await tester.runAsync(()=>ServerSocket.bind(InternetAddress.loopbackIPv4, 0));
    final closedPort=socket!.port;
    await tester.runAsync(socket.close);
    final tokens=(await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: DirectSshPage(tokens: tokens)));
    await tester.enterText(find.byKey(const ValueKey('direct-host')), '127.0.0.1');
    await tester.enterText(find.byKey(const ValueKey('direct-port')), '$closedPort');
    await tester.enterText(find.byKey(const ValueKey('direct-user')), 'fixture');
    await tester.pump();await tester.tap(find.byKey(const ValueKey('direct-probe')));await tester.pump();
    await waitFor(tester, find.textContaining('探测失败或超时'));
    expect(find.bySemanticsLabel('地址'), findsOneWidget);
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('direct-connect'))).onPressed, isNull);
    semantics.dispose();
  });

}
