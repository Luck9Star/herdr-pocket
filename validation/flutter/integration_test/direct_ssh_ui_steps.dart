import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:terminal_view/terminal_view.dart';
import 'package:herdr_flutter_probe/main.dart' as app;
import 'package:herdr_flutter_probe/direct_ssh_page.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';

Future<void> until(WidgetTester tester, bool Function() ready) async {
  final deadline = DateTime.now().add(const Duration(seconds: 45));
  while (!ready()) {
    if (DateTime.now().isAfter(deadline)) fail('direct_ssh_android_ui_timeout');
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<void> tap(WidgetTester tester, String key) async {
  final finder = find.byKey(ValueKey(key));
  await until(tester, () => finder.evaluate().length == 1);
  await tester.ensureVisible(finder);
  await tester.pump(const Duration(milliseconds: 200));
  expect(finder.hitTestable(), findsOneWidget);
  await tester.tap(finder);
  await tester.pump(const Duration(milliseconds: 200));
}

bool hasMarker(Terminal terminal, String marker) {
  final bytes = marker.codeUnits;
  for (var y = 0; y < terminal.viewHeight; y++) {
    final line = terminal.buffer.lines[y];
    for (var x = 0; x + bytes.length <= terminal.viewWidth; x++) {
      if (List.generate(
            bytes.length,
            (i) => line.getCodePoint(x + i),
          ).join(',') ==
          bytes.join(','))
        return true;
    }
  }
  return false;
}

Future<void> runDirectSshUi(
  WidgetTester tester, {
  required IntegrationTestWidgetsFlutterBinding binding,
  required Map<String, dynamic> config,
  required String directory,
  required String platform,
  required void Function(String) step,
  required void Function(String, Object) publish,
  required Future<void> Function(String) capture,
}) async {
  step('home');
  await app.main();
  await until(
    tester,
    () =>
        find.byType(HostCatalogPage).evaluate().length == 1 &&
        find.byKey(const ValueKey('hosts-direct-ssh')).evaluate().isNotEmpty,
  );
  final home = tester.widget<HostCatalogPage>(find.byType(HostCatalogPage));
  expect(home.catalog, isNull);
  expect(home.adapterFactory, isNull);
  expect(home.keys, isNull);
  await capture('home');
  await tap(tester, 'hosts-direct-ssh');
  expect(find.byType(DirectSshPage), findsOneWidget);
  step('target');
  for (final entry in {
    'direct-host': '127.0.0.1',
    'direct-port': '${config['port']}',
    'direct-user': 'fixture',
  }.entries) {
    final field = find.byKey(ValueKey(entry.key));
    await tester.ensureVisible(field);
    await tester.enterText(field, entry.value);
    await tester.pump();
  }
  expect(
    tester
        .widget<FilledButton>(find.byKey(const ValueKey('direct-connect')))
        .onPressed,
    isNull,
  );
  step('probe');
  await tap(tester, 'direct-probe');
  await until(
    tester,
    () => find.byKey(const ValueKey('direct-trust-key')).evaluate().length == 1,
  );
  expect(find.textContaining(config['fingerprint'] as String), findsOneWidget);
  await tap(tester, 'direct-trust-key');
  step('authenticate');
  final secret = find.byKey(const ValueKey('direct-secret'));
  await tester.ensureVisible(secret);
  await tester.enterText(secret, config['password'] as String);
  await tester.pump();
  await tap(tester, 'direct-connect');
  await until(tester, () => find.byType(TerminalView).evaluate().length == 1);
  final terminalView = find.byType(TerminalView);
  final terminal = tester.widget<TerminalView>(terminalView).terminal;
  await until(tester, () => hasMarker(terminal, 'POCKET-ANDROID-READY'));
  step('input');
  await tester.tap(terminalView);
  await tester.pump(const Duration(milliseconds: 300));
  // Normal TerminalView debug-client commit, not terminal.onOutput injection
  // and not evidence of physical IME touch/composition.
  tester.testTextInput.enterText('hp-check');
  await tester.pump();
  final enter = find.widgetWithText(TextButton, 'Enter');
  await tester.ensureVisible(enter);
  await tester.tap(enter);
  await tester.pump();
  await until(tester, () => hasMarker(terminal, 'POCKET-ANDROID-SSH-OK'));
  await capture('connected');
  step('disconnect');
  final disconnect = find.widgetWithText(TextButton, '断开');
  expect(disconnect, findsOneWidget);
  await tester.tap(disconnect);
  await until(tester, () => find.byType(TerminalView).evaluate().isEmpty);
  expect(
    tester
        .widget<TextField>(find.byKey(const ValueKey('direct-secret')))
        .controller!
        .text,
    isEmpty,
  );
  expect(find.textContaining('已断开'), findsOneWidget);
  await capture('disconnected');
  expect(tester.takeException(), isNull);
  final report = {
    'schemaVersion': 1,
    'platform': platform,
    'homepageEntry': true,
    'fingerprintMatched': true,
    'explicitTrustRequired': true,
    'realTerminalView': true,
    'normalTextInputCommit': true,
    'remoteEchoVisible': true,
    'disconnectUiConfirmed': true,
    'credentialsCleared': true,
    'physicalImeVerified': false,
  };
  publish('result.json', report);
  // Keep the driver alive until the runner independently confirms that
  // the UI closed the peer, rather than count driver shutdown as close.
  final confirmation = File('$directory/peer-confirmed.json');
  await until(tester, () => confirmation.existsSync());
  expect(jsonDecode(confirmation.readAsStringSync()), {
    'protocolAccepted': true,
    'peerClosedBeforeDriverExit': true,
  });
  binding.reportData = report;
}
