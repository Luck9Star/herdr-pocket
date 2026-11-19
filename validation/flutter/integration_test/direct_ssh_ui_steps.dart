import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:terminal_view/terminal_view.dart';
import 'package:herdr_flutter_probe/main.dart' as app;
import 'package:herdr_flutter_probe/direct_ssh_page.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';

Future<void> until(
  WidgetTester tester,
  bool Function() ready, {
  String timeoutReason = 'direct_ssh_android_ui_timeout',
}) async {
  final deadline = DateTime.now().add(const Duration(seconds: 45));
  while (!ready()) {
    if (DateTime.now().isAfter(deadline)) fail(timeoutReason);
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Finder control(String key) => find.byKey(ValueKey(key));

Future<void> tap(
  WidgetTester tester,
  String key, {
  void Function()? beforeTap,
  bool requireEnabled = false,
  Duration timeout = const Duration(seconds: 45),
}) => tapControl(
  tester,
  control(key),
  key,
  beforeTap: beforeTap,
  requireEnabled: requireEnabled,
  timeout: timeout,
);

Future<void> tapControl(
  WidgetTester tester,
  Finder finder,
  String name, {
  void Function()? beforeTap,
  bool requireEnabled = false,
  bool reveal = true,
  Duration timeout = const Duration(seconds: 45),
}) async {
  final deadline = DateTime.now().add(timeout);
  Rect? lastRect;
  var stable = 0;
  while (DateTime.now().isBefore(deadline)) {
    if (finder.evaluate().length == 1) {
      if (reveal) await tester.ensureVisible(finder);
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
  if (stable < 2) fail('direct_ssh_control_not_ready_$name');
  expect(finder.hitTestable(), findsOneWidget);
  await tester.tap(finder);
  await tester.pump(const Duration(milliseconds: 200));
}

Future<void> openDirectSshFromHome(WidgetTester tester) async {
  final page = find.byType(DirectSshPage);
  final form = find.descendant(
    of: page,
    matching: find.byKey(const ValueKey('direct-form')),
  );
  await tap(tester, 'hosts-direct-ssh');
  // The entry tap is performed once. Wait for the real route and form to
  // finish appearing before interacting with any fields.
  await until(tester, () {
    if (page.evaluate().length != 1 || form.evaluate().length != 1) {
      return false;
    }
    final route = ModalRoute.of(tester.element(page));
    return route?.isCurrent == true &&
        route?.animation?.status == AnimationStatus.completed;
  }, timeoutReason: 'direct_ssh_home_route_timeout');
}

bool hasMarker(Terminal terminal, String marker) {
  final expected = marker.codeUnits;
  if (expected.isEmpty) return false;
  final candidate = <int>[];
  for (var y = 0; y < terminal.viewHeight; y++) {
    final line = terminal.buffer.lines[y];
    // Only a terminal soft wrap continues the previous line. Hard newlines
    // must not combine unrelated output into a successful marker.
    if (!line.isWrapped) candidate.clear();
    for (var x = 0; x < terminal.viewWidth; x++) {
      candidate.add(line.getCodePoint(x));
      if (candidate.length > expected.length) candidate.removeAt(0);
      if (candidate.length == expected.length &&
          List.generate(
            expected.length,
            (i) => candidate[i] == expected[i],
          ).every((match) => match)) {
        return true;
      }
    }
  }
  return false;
}

Future<void> waitForEncryptedIdleTerminal(
  WidgetTester tester,
  Terminal terminal, {
  required double Function() keyboardInset,
  required void Function() observe,
}) async {
  final view = find.byType(TerminalView);
  await until(tester, () {
    observe();
    return view.hitTestable().evaluate().length == 1 &&
        control('direct-disconnect').hitTestable().evaluate().length == 1 &&
        identical(tester.widget<TerminalView>(view).terminal, terminal) &&
        keyboardInset() == 0;
  }, timeoutReason: 'direct_ssh_encrypted_idle_ime_timeout');
}

Future<void> verifyOrdinaryMobileControls(
  WidgetTester tester,
  Terminal terminal,
  String directory,
  void Function(String) step,
  void Function(String, Object) publish,
) async {
  Future<void> checkpoint(String phase) async {
    publish('ordinary-mobile-stage.json', {'phase': phase});
    final reply = File('$directory/ordinary-mobile-$phase-confirmed.json');
    await until(tester, reply.existsSync);
    expect(jsonDecode(reply.readAsStringSync()), {
      'phase': phase,
      'serverEvidenceAccepted': true,
    });
  }

  final terminalView = find.byType(TerminalView);
  final disconnect = control('direct-disconnect');
  bool activeTerminal() =>
      terminalView.hitTestable().evaluate().length == 1 &&
      disconnect.hitTestable().evaluate().length == 1 &&
      identical(tester.widget<TerminalView>(terminalView).terminal, terminal);

  // Read the engine's surface metrics, which don't use WidgetTester's mock
  // input client or view-inset overrides. The app must resize with the IME.
  final surface = ui.PlatformDispatcher.instance.implicitView!;
  double terminalHeight() => tester.getRect(terminalView).height;
  await until(tester, () => activeTerminal() && surface.viewInsets.bottom == 0);
  final closedHeight = terminalHeight();

  step('keyboard_shown');
  await toggleOrdinaryKeyboard(tester, show: true);
  expect(activeTerminal(), isTrue);
  expect(terminalHeight(), lessThan(closedHeight));
  final keyboardTop =
      (surface.physicalSize.height - surface.viewInsets.bottom) /
      surface.devicePixelRatio;
  expect(tester.getRect(terminalView).bottom, lessThanOrEqualTo(keyboardTop));
  await checkpoint('keyboard_shown');

  step('keyboard_hidden');
  await toggleOrdinaryKeyboard(tester, show: false);
  expect(activeTerminal(), isTrue);
  expect(terminalHeight(), closedHeight);
  await checkpoint('keyboard_hidden');

  for (final (tab, pageAnchor, terminalTab) in [
    ('board', control('hosts-direct-ssh'), control('home-tab-1')),
    (
      'network',
      control('networks-add'),
      find.widgetWithText(NavigationDestination, '终端'),
    ),
    (
      'settings',
      control('direct-settings-active'),
      control('direct-tab-terminal'),
    ),
  ]) {
    final visible = '${tab}_visible';
    step(visible);
    await tapControl(tester, control('direct-tab-$tab'), tab, reveal: false);
    await until(
      tester,
      () =>
          pageAnchor.hitTestable().evaluate().length == 1 &&
          terminalView.hitTestable().evaluate().isEmpty,
    );
    expect(surface.viewInsets.bottom, 0);
    await checkpoint(visible);

    final returned = '${tab}_returned';
    step(returned);
    await tapControl(tester, terminalTab, returned, reveal: false);
    await until(tester, activeTerminal);
    expect(pageAnchor.hitTestable(), findsNothing);
    expect(surface.viewInsets.bottom, 0);
    await checkpoint(returned);
  }
}

Future<void> toggleOrdinaryKeyboard(
  WidgetTester tester, {
  required bool show,
}) async {
  final toggle = control('direct-keyboard-toggle');
  final surface = ui.PlatformDispatcher.instance.implicitView!;
  expect(tester.widget<IconButton>(toggle).tooltip, show ? '打开键盘' : '收起键盘');
  await tapControl(tester, toggle, 'direct-keyboard-toggle', reveal: false);
  await until(
    tester,
    () =>
        (show
            ? surface.viewInsets.bottom > 0
            : surface.viewInsets.bottom == 0) &&
        toggle.hitTestable().evaluate().length == 1 &&
        tester.widget<IconButton>(toggle).tooltip == (show ? '收起键盘' : '打开键盘'),
    timeoutReason: 'direct_ssh_keyboard_ui_timeout',
  );
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
  await openDirectSshFromHome(tester);
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
  expect(find.byKey(const ValueKey('direct-secret')), findsNothing);
  expect(find.byKey(const ValueKey('direct-connect')), findsNothing);
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
  expect(tester.widget<TextField>(secret).controller!.text, config['password']);
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
  await verifyOrdinaryMobileControls(
    tester,
    terminal,
    directory,
    step,
    publish,
  );
  step('input');
  await toggleOrdinaryKeyboard(tester, show: true);
  // Normal TerminalView debug-client commit, not terminal.onOutput injection
  // and not evidence of physical IME touch/composition.
  tester.testTextInput.enterText('hp-check');
  await tester.pump();
  await tapControl(tester, control('direct-key-enter'), 'terminal-enter');
  await until(tester, () => hasMarker(terminal, 'POCKET-ANDROID-SSH-OK'));
  await toggleOrdinaryKeyboard(tester, show: false);
  await capture('connected');
  step('disconnect');
  step('disconnect_tap');
  await tapControl(
    tester,
    control('direct-disconnect'),
    'direct-disconnect',
    reveal: false,
  );
  step('disconnect_wait');
  await until(tester, () => find.byType(TerminalView).evaluate().isEmpty);
  step('disconnect_secret');
  final clearedSecret = find.byKey(const ValueKey('direct-secret'));
  await until(
    tester,
    () => find.byKey(const ValueKey('direct-form')).evaluate().length == 1,
  );
  expect(clearedSecret, findsNothing);
  final dynamic state = tester.state(find.byType(DirectSshPage));
  expect(state.secret.text, isEmpty);
  expect(state.passphrase.text, isEmpty);
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
    'platformKeyboardOpenedAndClosed': true,
    'boardNetworkSettingsReturnedToSameTerminal': true,
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

Future<void> runEncryptedDirectSshUi(
  WidgetTester tester, {
  required IntegrationTestWidgetsFlutterBinding binding,
  required Map<String, dynamic> config,
  required String directory,
  required String platform,
  required void Function(String) step,
  required void Function(String, Object) publish,
  required Future<void> Function(String) capture,
}) async {
  Future<void> checkpoint(String phase) async {
    publish('encrypted-stage.json', {'phase': phase});
    final confirmation = File('$directory/encrypted-$phase-confirmed.json');
    await until(tester, confirmation.existsSync);
    expect(jsonDecode(confirmation.readAsStringSync()), {
      'phase': phase,
      'serverEvidenceAccepted': true,
    });
  }

  String? lastDiagnostic;
  void diagnostic(String phase, [Terminal? terminal]) {
    final views = find.byType(TerminalView);
    final toggle = control('direct-keyboard-toggle');
    final disconnect = control('direct-disconnect');
    final enter = control('direct-key-enter');
    final surface = ui.PlatformDispatcher.instance.implicitView!;
    final oneView = views.evaluate().length == 1;
    final oneToggle = toggle.evaluate().length == 1;
    final oneEnter = enter.evaluate().length == 1;
    final tooltip = oneToggle
        ? tester.widget<IconButton>(toggle).tooltip
        : null;
    final rect = oneView ? tester.getRect(views) : null;
    final enterRect = oneEnter ? tester.getRect(enter) : null;
    final value = {
      'phase': phase,
      'terminalCount': views.evaluate().length,
      'terminalHit': oneView && views.hitTestable().evaluate().length == 1,
      'disconnectHit': disconnect.hitTestable().evaluate().length == 1,
      'toggleHit': oneToggle && toggle.hitTestable().evaluate().length == 1,
      'enterHit': oneEnter && enter.hitTestable().evaluate().length == 1,
      'headerHit': find.text('普通 SSH').hitTestable().evaluate().isNotEmpty,
      'toggleState': tooltip == '打开键盘'
          ? 'open'
          : tooltip == '收起键盘'
          ? 'close'
          : tooltip == null
          ? 'missing'
          : 'other',
      'insetBottomPx': surface.viewInsets.bottom.round(),
      'viewSizePx': [
        surface.physicalSize.width.round(),
        surface.physicalSize.height.round(),
      ],
      'terminalRectPt': rect == null
          ? null
          : [
              rect.left.round(),
              rect.top.round(),
              rect.width.round(),
              rect.height.round(),
            ],
      'enterRectPt': enterRect == null
          ? null
          : [
              enterRect.left.round(),
              enterRect.top.round(),
              enterRect.width.round(),
              enterRect.height.round(),
            ],
      'columns': terminal?.viewWidth ?? 0,
      'rows': terminal?.viewHeight ?? 0,
      'terminalFocused':
          oneView &&
          (tester.widget<TerminalView>(views).focusNode?.hasFocus ?? false),
      'testInputRegistered': tester.testTextInput.isRegistered,
      'testClientSet': tester.testTextInput.setClientArgs != null,
      'welcomeVisible':
          terminal != null && hasMarker(terminal, 'POCKET-ANDROID-READY'),
      'echoVisible':
          terminal != null && hasMarker(terminal, 'POCKET-ANDROID-SSH-OK'),
    };
    final encoded = jsonEncode(value);
    if (encoded != lastDiagnostic) {
      publish('encrypted-diagnostic.json', value);
      lastDiagnostic = encoded;
    }
  }

  Future<void> pasteKey() async {
    try {
      await tester.runAsync(
        () => Clipboard.setData(
          ClipboardData(text: config['privateKey'] as String),
        ),
      );
      await tap(tester, 'direct-paste-key');
      await until(
        tester,
        () =>
            tester
                .widget<TextField>(control('direct-secret'))
                .controller!
                .text ==
            config['privateKey'],
      );
    } finally {
      await tester.runAsync(
        () => Clipboard.setData(const ClipboardData(text: '')),
      );
      final cleared = await tester.runAsync(
        () => Clipboard.getData(Clipboard.kTextPlain),
      );
      expect(cleared?.text?.isEmpty ?? true, isTrue);
      // Let Android's transient clipboard preview expire before any capture.
      await tester.pump(const Duration(seconds: 8));
    }
  }

  step('encrypted_home');
  await app.main();
  await until(
    tester,
    () =>
        find.byType(HostCatalogPage).evaluate().length == 1 &&
        control('hosts-direct-ssh').evaluate().isNotEmpty,
  );
  final home = tester.widget<HostCatalogPage>(find.byType(HostCatalogPage));
  expect(home.catalog, isNull);
  expect(home.adapterFactory, isNull);
  expect(home.keys, isNull);
  await capture('home');
  await openDirectSshFromHome(tester);
  for (final entry in {
    'direct-host': '127.0.0.1',
    'direct-port': '${config['port']}',
    'direct-user': 'fixture',
  }.entries) {
    await tester.ensureVisible(control(entry.key));
    await tester.enterText(control(entry.key), entry.value);
    await tester.pump();
  }
  expect(control('direct-secret'), findsNothing);
  step('encrypted_probe');
  await tap(tester, 'direct-probe');
  await until(
    tester,
    () => control('direct-trust-key').evaluate().length == 1,
  );
  expect(
    find.textContaining(config['fingerprint'] as String),
    findsOneWidget,
  );
  step('encrypted_review');
  await checkpoint('review');
  await tap(tester, 'direct-trust-key');
  await tap(tester, 'direct-auth-key');
  await pasteKey();
  final passphrase = control('direct-passphrase');
  expect(tester.widget<TextField>(passphrase).obscureText, isTrue);
  await tester.ensureVisible(passphrase);
  await tester.enterText(passphrase, 'invalid-fixture-passphrase');
  await tester.pump();
  await tap(tester, 'direct-connect', requireEnabled: true);
  await until(
    tester,
    () => find.textContaining('私钥无法解析或解密').evaluate().isNotEmpty,
  );
  final dynamic state = tester.state(find.byType(DirectSshPage));
  expect(state.secret.text.isEmpty, isTrue);
  expect(state.passphrase.text.isEmpty, isTrue);
  step('encrypted_rejected');
  await checkpoint('rejected');
  await pasteKey();
  await tester.ensureVisible(passphrase);
  await tester.enterText(passphrase, config['passphrase'] as String);
  config.remove('privateKey');
  config.remove('passphrase');
  await tester.pump();
  expect(tester.widget<TextField>(passphrase).obscureText, isTrue);
  step('encrypted_connect');
  await tap(tester, 'direct-connect', requireEnabled: true);
  step('encrypted_wait_terminal');
  await until(tester, () {
    diagnostic('encrypted_wait_terminal');
    return find.byType(TerminalView).evaluate().length == 1;
  });
  final terminalView = find.byType(TerminalView);
  final terminal = tester.widget<TerminalView>(terminalView).terminal;
  step('encrypted_wait_welcome');
  await until(tester, () {
    diagnostic('encrypted_wait_welcome', terminal);
    return hasMarker(terminal, 'POCKET-ANDROID-READY');
  });
  expect(state.secret.text.isEmpty, isTrue);
  expect(state.passphrase.text.isEmpty, isTrue);
  final surface = ui.PlatformDispatcher.instance.implicitView!;
  step('encrypted_wait_idle_ime');
  await waitForEncryptedIdleTerminal(
    tester,
    terminal,
    keyboardInset: () => surface.viewInsets.bottom,
    observe: () => diagnostic('encrypted_wait_idle_ime', terminal),
  );
  step('encrypted_keyboard_show');
  try {
    await toggleOrdinaryKeyboard(tester, show: true);
  } finally {
    diagnostic('encrypted_keyboard_show', terminal);
  }
  step('encrypted_input');
  diagnostic('encrypted_input', terminal);
  tester.testTextInput.enterText('hp-check');
  await tester.pump();
  step('encrypted_enter');
  try {
    await tapControl(tester, control('direct-key-enter'), 'terminal-enter');
  } finally {
    diagnostic('encrypted_enter', terminal);
  }
  step('encrypted_wait_echo');
  await until(tester, () {
    diagnostic('encrypted_wait_echo', terminal);
    return hasMarker(terminal, 'POCKET-ANDROID-SSH-OK');
  });
  step('encrypted_keyboard_hide');
  try {
    await toggleOrdinaryKeyboard(tester, show: false);
  } finally {
    diagnostic('encrypted_keyboard_hide', terminal);
  }
  step('encrypted_capture');
  diagnostic('encrypted_capture', terminal);
  await capture('connected');
  step('encrypted_disconnect');
  await tapControl(
    tester,
    control('direct-disconnect'),
    'direct-disconnect',
    reveal: false,
  );
  await until(tester, () => find.byType(TerminalView).evaluate().isEmpty);
  expect(state.secret.text.isEmpty, isTrue);
  expect(state.passphrase.text.isEmpty, isTrue);
  expect(find.textContaining('已断开'), findsOneWidget);
  await capture('disconnected');
  expect(tester.takeException(), isNull);
  final report = {
    'schemaVersion': 1,
    'platform': platform,
    'homepageEntry': true,
    'fingerprintMatched': true,
    'explicitTrustRequired': true,
    'privateKeyPasted': true,
    'passphraseObscured': true,
    'wrongPassphraseRejectedLocally': true,
    'realTerminalView': true,
    'normalTextInputCommit': true,
    'remoteEchoVisible': true,
    'disconnectUiConfirmed': true,
    'credentialsCleared': true,
    'privateInputRemoved': true,
    'clipboardCleared': true,
    'physicalImeVerified': false,
  };
  publish('encrypted-result.json', report);
  final confirmation = File('$directory/encrypted-peer-confirmed.json');
  await until(tester, confirmation.existsSync);
  expect(jsonDecode(confirmation.readAsStringSync()), {
    'protocolAccepted': true,
    'peerClosedBeforeDriverExit': true,
  });
  binding.reportData = report;
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
  await openDirectSshFromHome(tester);
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
  expect(tester.widget<SelectableText>(find.byKey(const ValueKey('direct-target-value'))).data, 'fixture@127.0.0.1:${config['port']}');
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
  expect(state.secret.text, isEmpty); expect(state.passphrase.text, isEmpty);
  expect(secret, findsNothing);
  expect(find.byKey(const ValueKey('direct-auth-key')), findsNothing);
  expect(find.byKey(const ValueKey('direct-connect')), findsNothing);
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
