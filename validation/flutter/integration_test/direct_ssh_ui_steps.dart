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

Future<void> tap(
  WidgetTester tester,
  String key, {
  void Function()? beforeTap,
  bool requireEnabled = false,
  Duration timeout = const Duration(seconds: 45),
}) async {
  final finder = find.byKey(ValueKey(key));
  final deadline = DateTime.now().add(timeout);
  Rect? lastRect;
  var stable = 0;
  while (DateTime.now().isBefore(deadline)) {
    if (finder.evaluate().length == 1) {
      await tester.ensureVisible(finder);
      await tester.pump(const Duration(milliseconds: 100));
      final enabled =
          !requireEnabled ||
          tester.widget<FilledButton>(finder).onPressed != null;
      final hit = finder.hitTestable().evaluate().length == 1;
      final rect = tester.getRect(finder);
      stable = enabled && hit ? (lastRect == rect ? stable + 1 : 1) : 0;
      lastRect = rect;
      if (stable >= 2) break;
    } else {
      stable = 0;
      lastRect = null;
      await tester.pump(const Duration(milliseconds: 100));
    }
  }
  beforeTap?.call();
  if (stable < 2) fail('direct_ssh_control_not_ready_$key');
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
  step('secret_entry');
  final secret = find.byKey(const ValueKey('direct-secret'));
  await tester.ensureVisible(secret);
  await tester.enterText(secret, config['password'] as String);
  await tester.pump();
  step('connect_tap');
  await tap(
    tester,
    'direct-connect',
    requireEnabled: true,
    beforeTap: () {
      final connect = find.byKey(const ValueKey('direct-connect'));
      final exists = connect.evaluate().length == 1;
      final status = find.byKey(const ValueKey('direct-status'));
      final statusText = status.evaluate().length == 1
          ? tester.widget<Text>(status).data
          : null;
      publish('connect-diagnostic.json', {
        'connectExists': exists,
        'connectEnabled': exists
            ? tester.widget<FilledButton>(connect).onPressed != null
            : null,
        'connectHitTestable': exists
            ? connect.hitTestable().evaluate().length == 1
            : null,
        'statusCode': statusText == '已确认本次主机密钥；连接时将重新核对。'
            ? 'fingerprint_confirmed'
            : statusText == '应用进入后台，连接已关闭；返回后需重新连接，不会重放输入。'
            ? 'background_closed'
            : 'other',
      });
      step('connect_preflight');
    },
  );
  final afterStatus = find.byKey(const ValueKey('direct-status'));
  final afterText = afterStatus.evaluate().length == 1
      ? tester.widget<Text>(afterStatus).data
      : null;
  publish('connect-post.json', {
    'terminalVisible': find.byType(TerminalView).evaluate().length == 1,
    'statusCode': afterText == '正在重新核对主机密钥并连接…'
        ? 'connecting'
        : afterText == '已确认本次主机密钥；连接时将重新核对。'
        ? 'fingerprint_confirmed'
        : afterText == '应用进入后台，连接已关闭；返回后需重新连接，不会重放输入。'
        ? 'background_closed'
        : afterText == '连接失败或超时，请检查网络、密钥与目标。'
        ? 'connect_failed'
        : 'other',
  });
  step('await_terminal');
  await until(tester, () => find.byType(TerminalView).evaluate().length == 1);
  final terminalView = find.byType(TerminalView);
  final terminal = tester.widget<TerminalView>(terminalView).terminal;
  step('await_welcome');
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
