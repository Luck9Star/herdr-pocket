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
  await capture('preconnect');
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
  step('disconnect_tap');
  await tester.tap(disconnect);
  step('disconnect_wait');
  await until(tester, () => find.byType(TerminalView).evaluate().isEmpty);
  step('disconnect_secret');
  final clearedSecret = find.byKey(const ValueKey('direct-secret'));
  await until(tester, () => clearedSecret.evaluate().length == 1);
  await tester.ensureVisible(clearedSecret);
  await tester.pump(const Duration(milliseconds: 200));
  expect(tester.widget<TextField>(clearedSecret).controller!.text, isEmpty);
  step('disconnect_status');
  final disconnectedStatus = find.textContaining('已断开');
  await until(tester, () => disconnectedStatus.evaluate().length == 1);
  await tester.ensureVisible(disconnectedStatus);
  await tester.pump(const Duration(milliseconds: 200));
  expect(disconnectedStatus, findsOneWidget);
  await capture('disconnected');
  step('disconnect_exception');
  expect(tester.takeException(), isNull);
  step('disconnect_complete');
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
  step('peer_confirmed');
  binding.reportData = report;
  step('report_data_set');
}

Future<void> runDirectSshRotationUi(
  WidgetTester tester, {
  required Map<String, dynamic> config,
  required String directory,
  required String platform,
  required void Function(String) step,
  required void Function(String, Object) publish,
  required Future<void> Function(String) capture,
}) async {
  Future<void> checkpoint(String phase, int stage) async {
    publish('rotation-stage.json', {'phase': phase, 'stage': stage});
    final reply = File('$directory/rotation-$phase-confirmed.json');
    await until(tester, reply.existsSync);
    expect(jsonDecode(reply.readAsStringSync()), {
      'phase': phase,
      'stage': stage,
      'serverEvidenceAccepted': true,
    });
  }

  step('rotation_home');
  await app.main();
  await until(
    tester,
    () => find.byKey(const ValueKey('hosts-direct-ssh')).evaluate().length == 1,
  );
  await tap(tester, 'hosts-direct-ssh');
  expect(find.byType(DirectSshPage), findsOneWidget);
  final dynamic state = tester.state(find.byType(DirectSshPage));
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
  step('rotation_initial_probe');
  await tap(tester, 'direct-probe');
  await until(
    tester,
    () => find.byKey(const ValueKey('direct-trust-key')).evaluate().length == 1,
  );
  expect(find.textContaining(config['fingerprint'] as String), findsOneWidget);
  await tap(tester, 'direct-trust-key');
  final secret = find.byKey(const ValueKey('direct-secret'));
  await tester.ensureVisible(secret);
  await tester.enterText(secret, config['password'] as String);
  await tester.pump();
  await tap(tester, 'direct-connect', requireEnabled: true);
  await until(
    tester,
    () =>
        find
            .byKey(const ValueKey('direct-host-key-change'))
            .evaluate()
            .length ==
        1,
  );
  step('rotation_rejected');
  expect(
    tester
        .widget<SelectableText>(
          find.byKey(const ValueKey('direct-host-key-old')),
        )
        .data,
    contains(config['fingerprint']),
  );
  expect(
    tester
        .widget<SelectableText>(
          find.byKey(const ValueKey('direct-host-key-new')),
        )
        .data,
    contains(config['rotatedFingerprint']),
  );
  expect(find.text('目标：fixture@127.0.0.1:${config['port']}'), findsOneWidget);
  expect(state.fingerprint, config['fingerprint']);
  expect(state.hostKeyReviewRequired, isTrue);
  expect(state.secret.text, isEmpty);
  expect(find.byType(TerminalView), findsNothing);
  // S10 removes the ordinary back affordance and blocks the framework's
  // platform-back route. This does not verify physical navigation hardware.
  expect(find.byType(BackButton), findsNothing);
  await tester.binding.handlePopRoute();
  await tester.pump(const Duration(milliseconds: 300));
  expect(find.byType(DirectSshPage), findsOneWidget);
  expect(find.byKey(const ValueKey('direct-host-key-change')), findsOneWidget);
  await capture('rotation-rejected');
  await checkpoint('rejected', 2);

  step('rotation_cancelled');
  await tap(tester, 'direct-host-key-cancel');
  expect(find.byKey(const ValueKey('direct-form')), findsOneWidget);
  expect(state.fingerprint, config['fingerprint']);
  expect(state.hostKeyReviewRequired, isTrue);
  expect(tester.widget<TextField>(secret).controller!.text, isEmpty);
  expect(tester.widget<TextField>(secret).enabled, isFalse);
  expect(
    tester.widget<SwitchListTile>(find.byType(SwitchListTile)).onChanged,
    isNull,
  );
  expect(
    tester
        .widget<FilledButton>(find.byKey(const ValueKey('direct-connect')))
        .onPressed,
    isNull,
  );
  expect(find.byType(TerminalView), findsNothing);
  expect(find.byType(BackButton), findsOneWidget);
  expect(state.fingerprint, config['fingerprint']);
  await checkpoint('cancelled', 2);

  step('rotation_fresh_probe');
  await tap(tester, 'direct-probe');
  await until(
    tester,
    () => find.byKey(const ValueKey('direct-trust-key')).evaluate().length == 1,
  );
  expect(
    find.textContaining(config['rotatedFingerprint'] as String),
    findsOneWidget,
  );
  expect(state.fingerprint, config['fingerprint']);
  expect(state.hostKeyReviewRequired, isTrue);
  expect(find.byType(TerminalView), findsNothing);
  await checkpoint('reprobed', 3);
  await tap(tester, 'direct-trust-key');
  expect(state.fingerprint, config['rotatedFingerprint']);
  expect(state.hostKeyReviewRequired, isFalse);
  expect(tester.widget<TextField>(secret).enabled, isTrue);
  expect(tester.widget<TextField>(secret).controller!.text, isEmpty);
  expect(
    tester
        .widget<FilledButton>(find.byKey(const ValueKey('direct-connect')))
        .onPressed,
    isNull,
  );
  expect(find.byType(TerminalView), findsNothing);

  step('rotation_authenticate');
  await tester.ensureVisible(secret);
  await tester.enterText(secret, config['password'] as String);
  await tester.pump();
  await tap(tester, 'direct-connect', requireEnabled: true);
  await until(tester, () => find.byType(TerminalView).evaluate().length == 1);
  final terminalView = find.byType(TerminalView);
  final terminal = tester.widget<TerminalView>(terminalView).terminal;
  await until(tester, () => hasMarker(terminal, 'POCKET-ANDROID-READY'));
  step('rotation_input');
  await tester.tap(terminalView);
  await tester.pump(const Duration(milliseconds: 300));
  tester.testTextInput.enterText('hp-check');
  await tester.pump();
  final enter = find.widgetWithText(TextButton, 'Enter');
  await tester.ensureVisible(enter);
  await tester.tap(enter);
  await tester.pump();
  await until(tester, () => hasMarker(terminal, 'POCKET-ANDROID-SSH-OK'));
  await capture('rotation-connected');
  step('rotation_disconnect');
  await tester.tap(find.widgetWithText(TextButton, '断开'));
  await until(tester, () => find.byType(TerminalView).evaluate().isEmpty);
  expect(state.secret.text, isEmpty);
  expect(state.fingerprint, config['rotatedFingerprint']);
  expect(state.hostKeyReviewRequired, isFalse);
  expect(tester.takeException(), isNull);
  publish('rotation-result.json', {
    'schemaVersion': 1,
    'platform': platform,
    'homepageEntry': true,
    'sameTarget': true,
    'oldFingerprintMatchedIndependentA': true,
    'changedFingerprintMatchedIndependentB': true,
    'rejectedBeforeAuthentication': true,
    'reviewNavigationBlocked': true,
    'cancelKeepsOldTrust': true,
    'credentialsLockedBeforeApproval': true,
    'noAutomaticConnection': true,
    'freshProbeMatchedIndependentB': true,
    'explicitRotatedTrustRequired': true,
    'realTerminalView': true,
    'normalTextInputCommit': true,
    'remoteEchoVisible': true,
    'disconnectUiConfirmed': true,
    'credentialsCleared': true,
    'physicalImeVerified': false,
  });
  await checkpoint('complete', 4);
  // Return only after independent approval has released the review lock, so
  // the unchanged ordinary-SSH scenario starts from the real homepage again.
  await tester.tap(find.byType(BackButton));
  await until(
    tester,
    () => find.byKey(const ValueKey('hosts-direct-ssh')).evaluate().length == 1,
  );
  step('rotation_complete');
}
