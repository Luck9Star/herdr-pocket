import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart'
    show Clipboard, ClipboardData, LogicalKeyboardKey, PhysicalKeyboardKey;
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/direct_ssh_page.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/main.dart' as app;
import 'package:integration_test/integration_test.dart';
import 'package:terminal_view/terminal_view.dart';

import 'direct_ssh_ui_steps.dart'
    show control, hasMarker, openDirectSshFromHome, tap, tapControl;

typedef Checkpoint = Future<void> Function(
  String phase,
  Map<String, Object> evidence,
);

class LinuxTarget {
  LinuxTarget.parse(Map<String, dynamic> value)
    : port = value['port'] as int,
      fingerprint = value['fingerprint'] as String,
      password = value['password'] as String?,
      privateKey = value['privateKey'] as String?,
      passphrase = value['passphrase'] as String?,
      wrongPassphrase = value['wrongPassphrase'] as String?,
      rotatedFingerprint = value['rotatedFingerprint'] as String? {
    final fingerprintPattern = RegExp(r'^SHA256:[A-Za-z0-9+/]{43}$');
    final disposableSecret = RegExp(r'^[a-f0-9]{32}$');
    final validCredential = privateKey == null
        ? value.length == 3 && disposableSecret.hasMatch(password ?? '')
        : value.length == (rotatedFingerprint == null ? 5 : 6) &&
              !value.containsKey('password') &&
              privateKey!.startsWith('-----BEGIN OPENSSH PRIVATE KEY-----\n') &&
              privateKey!.trimRight().endsWith(
                '-----END OPENSSH PRIVATE KEY-----',
              ) &&
              disposableSecret.hasMatch(passphrase ?? '') &&
              disposableSecret.hasMatch(wrongPassphrase ?? '') &&
              wrongPassphrase != passphrase &&
              (rotatedFingerprint == null ||
                  (rotatedFingerprint != fingerprint &&
                      fingerprintPattern.hasMatch(rotatedFingerprint!)));
    if (!validCredential ||
        port < 1024 ||
        port > 65535 ||
        !fingerprintPattern.hasMatch(fingerprint)) {
      throw StateError('linux_direct_fixture_invalid');
    }
  }

  final int port;
  final String fingerprint;
  final String? password,
      privateKey,
      passphrase,
      wrongPassphrase,
      rotatedFingerprint;
  bool get encrypted => privateKey != null;
  String get label => 'fixture@127.0.0.1:$port';
}

Future<void> waitUi(
  WidgetTester tester,
  bool Function() ready,
  String code,
) async {
  final deadline = DateTime.now().add(const Duration(seconds: 45));
  while (!ready()) {
    if (DateTime.now().isAfter(deadline)) fail(code);
    // Live bindings stay responsive on device. Also yield to socket I/O in
    // the catalog-route widget test used for local verification.
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 30)),
    );
    await tester.pump(const Duration(milliseconds: 70));
  }
}

Map<String, Object> visiblePixels(
  WidgetTester tester,
  Finder terminalView,
  Finder target,
) {
  final surface = tester.view;
  final size = surface.physicalSize;
  expect(
    surface.devicePixelRatio == 1 && size.width >= 960 && size.height >= 600,
    isTrue,
  );
  expect(terminalView.hitTestable(), findsOneWidget);
  expect(target.hitTestable(), findsOneWidget);
  List<int> bounds(
    Finder finder, {
    required int minWidth,
    required int minHeight,
  }) {
    final rect = tester.getRect(finder);
    final left = rect.left.ceil(), top = rect.top.ceil();
    final right = rect.right.floor(), bottom = rect.bottom.floor();
    expect(
      left >= 0 &&
          top >= 0 &&
          right <= size.width &&
          bottom <= size.height &&
          right - left >= minWidth &&
          bottom - top >= minHeight,
      isTrue,
    );
    return [left, top, right - left, bottom - top];
  }

  return {
    'surface': [size.width.round(), size.height.round()],
    'terminalBounds': bounds(terminalView, minWidth: 300, minHeight: 160),
    'targetBounds': bounds(target, minWidth: 40, minHeight: 12),
  };
}

Map<String, Object> outcomePixels(WidgetTester tester, Finder outcome) {
  final size = tester.view.physicalSize;
  expect(tester.view.devicePixelRatio, 1);
  expect(outcome.hitTestable(), findsOneWidget);
  final rect = tester.getRect(outcome);
  final left = rect.left.ceil(), top = rect.top.ceil();
  final right = rect.right.floor(), bottom = rect.bottom.floor();
  expect(left >= 0 && top >= 0 && right <= size.width && bottom <= size.height &&
      right > left && bottom > top, isTrue);
  return {'surface': [size.width.round(), size.height.round()],
    'outcomeBounds': [left, top, right - left, bottom - top]};
}

Future<void> reviewLinuxFingerprint(
  WidgetTester tester,
  LinuxTarget target,
  String fingerprint,
  Checkpoint checkpoint,
  String phase,
) async {
  await tap(tester, 'direct-probe', requireEnabled: true, stableHitPoint: true);
  final review = control('direct-trust-header');
  final approve = control('direct-trust-key');
  await waitUi(tester, () {
    if (review.evaluate().length != 1 ||
        approve.hitTestable().evaluate().length != 1) {
      return false;
    }
    final route = ModalRoute.of(tester.element(review));
    return route?.isCurrent == true &&
        route?.animation?.status == AnimationStatus.completed;
  }, 'linux_direct_review_timeout');
  expect(
    find.descendant(of: review, matching: find.text('核对主机密钥')),
    findsOneWidget,
  );
  expect(
    control('direct-independent-verification').hitTestable(),
    findsOneWidget,
  );
  expect(control('direct-connect'), findsNothing);
  expect(control('direct-secret'), findsNothing);
  expect(control('direct-passphrase'), findsNothing);
  final presentedFingerprint = find.descendant(
    of: control('direct-key-fingerprint'),
    matching: find.byType(SelectableText),
  );
  final presentedTarget = control('direct-target-value');
  final presentedAlgorithm = control('direct-key-algorithm');
  for (final evidence in [
    presentedTarget,
    presentedAlgorithm,
    presentedFingerprint,
  ]) {
    expect(evidence.hitTestable(), findsOneWidget);
  }
  final algorithm = tester.widget<SelectableText>(presentedAlgorithm).data;
  const rsaAlgorithms = {'ssh-rsa', 'rsa-sha2-256', 'rsa-sha2-512'};
  expect(
    tester.widget<SelectableText>(presentedTarget).data == target.label &&
        rsaAlgorithms.contains(algorithm) &&
        tester.widget<SelectableText>(presentedFingerprint).data == fingerprint,
    isTrue,
    reason: 'linux_direct_fingerprint_or_target_mismatch',
  );
  await checkpoint(phase, {'algorithm': algorithm!});
  await tap(
    tester,
    'direct-trust-key',
    requireEnabled: true,
    stableHitPoint: true,
  );
}

Future<void> enterFocusedPassphrase(
  WidgetTester tester,
  Finder field,
  String passphrase,
) async {
  // enterText(field) can reuse a cached editor that has since lost focus.
  // Reacquire the live input connection through the visible field instead.
  await tapControl(tester, field, 'linux_passphrase');
  final editable = find.descendant(
    of: field,
    matching: find.byType(EditableText),
  );
  final editor = tester.state<EditableTextState>(editable);
  final input = editor.widget;
  expect(
    input.obscureText &&
        !input.readOnly &&
        input.focusNode.hasPrimaryFocus &&
        input.controller.text.isEmpty,
    isTrue,
    reason: 'linux_direct_passphrase_editor_not_focused',
  );
  tester.testTextInput.enterText(passphrase);
  await tester.idle();
  await tester.pump();
  expect(
    identical(tester.state<EditableTextState>(editable), editor) &&
        identical(editor.widget.controller, input.controller) &&
        identical(editor.widget.focusNode, input.focusNode) &&
        input.focusNode.hasPrimaryFocus &&
        input.controller.text == passphrase,
    isTrue,
    reason: 'linux_direct_passphrase_readback_failed',
  );
}

Future<TextEditingController> prepareEncryptedKey(
  WidgetTester tester,
  LinuxTarget target,
  Checkpoint checkpoint,
  void Function(String) step,
) async {
  final dynamic state = tester.state(find.byType(DirectSshPage));
  final pem = control('direct-secret'),
      passphrase = control('direct-passphrase');
  final connect = control('direct-connect');
  bool sameTrust(String fingerprint) =>
      state.fingerprint == fingerprint && state.checkedTarget == state.target;
  bool cleared() => state.secret.text.isEmpty && state.passphrase.text.isEmpty;
  bool connectDisabled() =>
      tester.widget<FilledButton>(connect).onPressed == null;
  Future<void> fill(Finder field, String text) async {
    await tester.ensureVisible(field);
    await tester.enterText(field, text);
    await tester.pump();
    expect(tester.widget<TextField>(field).controller!.text == text, isTrue);
  }

  Future<void> pastePem({bool traceCorrectKey = false}) async {
    void observe(String phase) {
      if (traceCorrectKey) step(phase);
    }

    observe('key_retry_editor');
    expect(tester.widget<TextField>(pem).controller!.text.isEmpty, isTrue);
    observe('key_retry_clipboard_seed');
    await Clipboard.setData(ClipboardData(text: target.privateKey!));
    var pasteVerified = false;
    try {
      observe('key_retry_paste_available');
      expect(
        tester.widget<OutlinedButton>(control('direct-paste-key')).onPressed,
        isNotNull,
      );
      observe('key_retry_paste_tap');
      await tap(tester, 'direct-paste-key');
      observe('key_retry_pem_readback');
      await waitUi(
        tester,
        () =>
            tester.widget<TextField>(pem).controller!.text == target.privateKey,
        'linux_direct_paste_timeout',
      );
      observe('key_retry_paste_feedback');
      expect(find.text('私钥已粘贴，仅本次使用。'), findsOneWidget);
      pasteVerified = true;
    } finally {
      // This belongs to the disposable X11 display, including on test failure.
      // Preserve the actual failing phase when the body failed.
      if (pasteVerified) observe('key_retry_clipboard_clear');
      await Clipboard.setData(const ClipboardData(text: ''));
    }
    observe('key_retry_clipboard_empty');
    expect(
      (await Clipboard.getData(Clipboard.kTextPlain))?.text?.isNotEmpty ??
          false,
      isFalse,
    );
  }

  step('key_mode_switch');
  expect(sameTrust(target.fingerprint) && cleared(), isTrue);
  await fill(pem, 'disposable-mode-switch');
  await tap(tester, 'direct-auth-key');
  final passwordToKeyCleared =
      cleared() &&
      sameTrust(target.fingerprint) &&
      tester.widget<TextField>(passphrase).obscureText;
  expect(passwordToKeyCleared, isTrue);
  await pastePem();
  expect(connectDisabled(), isTrue);
  await fill(passphrase, target.wrongPassphrase!);
  await tap(tester, 'direct-auth-password');
  final keyToPasswordCleared =
      cleared() &&
      sameTrust(target.fingerprint) &&
      tester.widget<TextField>(pem).obscureText &&
      passphrase.evaluate().isEmpty &&
      connectDisabled();
  expect(keyToPasswordCleared, isTrue);
  await checkpoint('mode-switch', {
    'passwordToKeyCleared': passwordToKeyCleared,
    'keyToPasswordCleared': keyToPasswordCleared,
    'sameTrust': sameTrust(target.fingerprint),
  });

  step('key_wrong_passphrase');
  await tap(tester, 'direct-auth-key');
  await pastePem();
  expect(connectDisabled(), isTrue);
  await fill(passphrase, target.wrongPassphrase!);
  await tap(
    tester,
    'direct-connect',
    requireEnabled: true,
    stableHitPoint: true,
  );
  const rejected = '私钥无法解析或解密；请检查完整 PEM 和私钥口令。尚未连接远端。';
  await waitUi(
    tester,
    () => find.text(rejected).hitTestable().evaluate().length == 1,
    'linux_direct_wrong_passphrase_not_rejected',
  );
  expect(
    cleared() &&
        sameTrust(target.fingerprint) &&
        connectDisabled() &&
        find.byType(TerminalView).evaluate().isEmpty,
    isTrue,
  );
  await checkpoint('wrong-passphrase', const {'rejectedLocally': true});

  await pastePem(traceCorrectKey: true);
  step('key_retry_passphrase_required');
  expect(connectDisabled(), isTrue);
  step('key_valid_passphrase');
  await enterFocusedPassphrase(tester, passphrase, target.passphrase!);
  step('key_retry_target_bound');
  expect(sameTrust(target.fingerprint), isTrue);
  final rotated = target.rotatedFingerprint;
  if (rotated != null) {
    step('key_rotation_reject');
    await tap(
      tester,
      'direct-connect',
      requireEnabled: true,
      stableHitPoint: true,
    );
    final change = control('direct-host-key-change');
    await waitUi(
      tester,
      () => change.hitTestable().evaluate().length == 1,
      'linux_direct_rotation_review_timeout',
    );
    final oldKey = control('direct-host-key-old'),
        newKey = control('direct-host-key-new');
    expect(oldKey.hitTestable(), findsOneWidget);
    expect(newKey.hitTestable(), findsOneWidget);
    expect(
      tester.widget<SelectableText>(oldKey).data == target.fingerprint &&
          tester.widget<SelectableText>(newKey).data == rotated &&
          tester.widget<SelectableText>(control('direct-target-value')).data ==
              target.label,
      isTrue,
    );
    expect(state.connectFailure, DirectSshConnectFailure.hostKeyChanged);
    expect(state.connectHostKeyMatched, isFalse);
    expect(
      sameTrust(target.fingerprint) && state.hostKeyReviewRequired && cleared(),
      isTrue,
    );
    for (final hidden in [
      pem,
      passphrase,
      connect,
      find.byType(TerminalView),
    ]) {
      expect(hidden, findsNothing);
    }
    await checkpoint(
      'rotation-rejected',
      outcomePixels(tester, control('direct-changed-keys')),
    );

    step('key_rotation_retain');
    await tap(tester, 'direct-host-key-cancel');
    expect(find.text('已保留旧信任').hitTestable(), findsOneWidget);
    expect(
      sameTrust(target.fingerprint) && state.hostKeyReviewRequired && cleared(),
      isTrue,
    );
    for (final hidden in [
      pem,
      passphrase,
      connect,
      find.byType(TerminalView),
    ]) {
      expect(hidden, findsNothing);
    }
    await checkpoint('rotation-retained', const {
      'oldTrustRetained': true,
      'credentialsLocked': true,
    });

    step('key_rotation_probe');
    await reviewLinuxFingerprint(
      tester,
      target,
      rotated,
      checkpoint,
      'rotation-probe',
    );
    await waitUi(
      tester,
      () =>
          control('direct-trust-header').evaluate().isEmpty &&
          control('direct-trust-approved').hitTestable().evaluate().length == 1,
      'linux_direct_rotation_approval_timeout',
    );
    expect(
      sameTrust(rotated) && !state.hostKeyReviewRequired && cleared(),
      isTrue,
    );
    if (state.keyAuth != true) await tap(tester, 'direct-auth-key');
    await pastePem();
    expect(connectDisabled(), isTrue);
    await enterFocusedPassphrase(tester, passphrase, target.passphrase!);
  }
  return tester.widget<TextField>(passphrase).controller!;
}

Future<void> runLinuxOrdinary(
  WidgetTester tester,
  LinuxTarget target, {
  required void Function(String phase) step,
  required Checkpoint checkpoint,
}) async {
  step('home');
  await tester.runAsync(app.main);
  final home = find.byType(HostCatalogPage);
  await waitUi(
    tester,
    () =>
        home.evaluate().length == 1 &&
        control('hosts-direct-ssh').hitTestable().evaluate().length == 1,
    'linux_direct_home_timeout',
  );
  final originalHome = tester.widget<HostCatalogPage>(home);
  final homeState = tester.state(home);
  expect(
    originalHome.catalog == null &&
        originalHome.adapterFactory == null &&
        originalHome.keys == null,
    isTrue,
  );

  step('form');
  await openDirectSshFromHome(tester);
  final page = find.byType(DirectSshPage);
  expect(Theme.of(tester.element(page)).platform, TargetPlatform.linux);
  final setupHeader = control('direct-page-header');
  expect(
    find.descendant(of: setupHeader, matching: find.text('普通 SSH')),
    findsOneWidget,
  );
  final fields = [
    ('direct-host', '127.0.0.1'),
    ('direct-port', '${target.port}'),
    ('direct-user', 'fixture'),
  ];
  for (final (name, value) in fields) {
    final field = control(name);
    await tester.ensureVisible(field);
    await tester.enterText(field, value);
    await tester.pump();
    expect(tester.widget<TextField>(field).controller!.text == value, isTrue);
  }
  final connect = control('direct-connect'),
      password = control('direct-secret');
  expect(connect, findsNothing);
  expect(password, findsNothing);

  step('probe');
  await reviewLinuxFingerprint(tester, target, target.fingerprint, checkpoint, 'probe');

  step(target.encrypted ? 'private_key' : 'password');
  final review = control('direct-trust-header');
  final presentedTarget = control('direct-target-value');
  await waitUi(
    tester,
    () =>
        review.evaluate().isEmpty &&
        password.hitTestable().evaluate().length == 1 &&
        connect.evaluate().length == 1 &&
        ModalRoute.of(tester.element(page))?.isCurrent == true,
    'linux_direct_review_close_timeout',
  );
  expect(
    find.descendant(of: setupHeader, matching: find.text('SSH 账号认证')),
    findsOneWidget,
  );
  expect(control('direct-trust-approved').hitTestable(), findsOneWidget);
  expect(
    tester.widget<SelectableText>(presentedTarget).data == target.label,
    isTrue,
  );
  for (final (name, _) in fields) {
    expect(control(name), findsNothing);
  }
  expect(control('direct-probe'), findsNothing);
  expect(tester.widget<FilledButton>(connect).onPressed, isNull);
  final passwordField = tester.widget<TextField>(password);
  expect(passwordField.obscureText, isTrue);
  final credential = passwordField.controller!;
  expect(credential.text.isEmpty, isTrue);
  TextEditingController? passphraseCredential;
  if (target.encrypted) {
    passphraseCredential = await prepareEncryptedKey(tester, target, checkpoint, step);
  } else {
    await tester.ensureVisible(password);
    await tester.enterText(password, target.password!);
    await tester.pump();
    expect(credential.text == target.password, isTrue);
  }
  if (target.encrypted) step('key_connect_tap');
  await tap(
    tester,
    'direct-connect',
    requireEnabled: true,
    stableHitPoint: true,
  );

  bool credentialsEmpty() => credential.text.isEmpty &&
      (passphraseCredential?.text.isEmpty ?? true);

  step('connected');
  final terminalView = find.byType(TerminalView),
      bound = control('direct-active-target');
  await waitUi(
    tester,
    () =>
        terminalView.evaluate().length == 1 &&
        bound.hitTestable().evaluate().length == 1 &&
        hasMarker(
          tester.widget<TerminalView>(terminalView).terminal,
          'POCKET-ANDROID-READY',
        ),
    'linux_direct_terminal_timeout',
  );
  expect(
    tester.widget<Text>(bound).data == target.label && credentialsEmpty(),
    isTrue,
  );
  expect(
    find.descendant(
      of: control('direct-terminal-status'),
      matching: find.text('已连接'),
    ).hitTestable(),
    findsOneWidget,
  );
  final terminal = tester.widget<TerminalView>(terminalView).terminal;
  final terminalState = tester.state<TerminalViewState>(terminalView);
  await checkpoint('connected', const {});

  step('input');
  await tapControl(tester, terminalView, 'linux_terminal', reveal: false);
  bool focusedOnBoundTerminal() =>
      terminalState.hasInputConnection &&
      identical(
        FocusManager.instance.primaryFocus?.context
            ?.findAncestorStateOfType<TerminalViewState>(),
        terminalState,
      ) &&
      identical(
        tester.state<TerminalViewState>(terminalView),
        terminalState,
      ) &&
      tester.widget<Text>(bound).data == target.label;
  await waitUi(
    tester,
    focusedOnBoundTerminal,
    'linux_direct_terminal_focus_timeout',
  );
  // Commit the line once and dispatch the desktop Enter key to the same view.
  expect(find.widgetWithText(TextButton, 'Enter').hitTestable(), findsNothing);
  tester.testTextInput.enterText('hp-check');
  await tester.pump();
  expect(focusedOnBoundTerminal(), isTrue);
  await tester.sendKeyEvent(
    LogicalKeyboardKey.enter,
    physicalKey: PhysicalKeyboardKey.enter,
  );
  await waitUi(
    tester,
    () => hasMarker(terminal, 'POCKET-ANDROID-SSH-OK'),
    'linux_direct_echo_timeout',
  );

  step('capture');
  expect(
    identical(tester.state<TerminalViewState>(terminalView), terminalState),
    isTrue,
  );
  expect(
    tester.widget<Text>(bound).data == target.label &&
        credentialsEmpty() &&
        control('direct-form').evaluate().isEmpty,
    isTrue,
  );
  final geometry = visiblePixels(tester, terminalView, bound);
  await checkpoint('capture', geometry);
  expect(visiblePixels(tester, terminalView, bound), geometry);
  expect(
    identical(tester.state<TerminalViewState>(terminalView), terminalState),
    isTrue,
  );

  step('disconnect');
  final disconnect = control('direct-desktop-disconnect');
  expect(disconnect.hitTestable(), findsOneWidget);
  expect(tester.widget<TextButton>(disconnect).onPressed, isNotNull);
  await tapControl(tester, disconnect, 'linux_disconnect', reveal: false);
  await waitUi(
    tester,
    () =>
        terminalView.evaluate().isEmpty &&
        bound.evaluate().isEmpty &&
        control('direct-form').evaluate().length == 1 &&
        control('direct-status').evaluate().length == 1 &&
        tester.widget<Text>(control('direct-status')).data == '本机已断开',
    'linux_direct_disconnect_timeout',
  );
  expect(control('direct-closed-feedback').hitTestable(), findsOneWidget);
  expect(
    find.descendant(
      of: control('direct-closed-feedback'),
      matching: find.text('凭据已清空，重连时请重新填写。'),
    ),
    findsOneWidget,
  );
  expect(credentialsEmpty(), isTrue);
  expect(password, findsNothing);
  expect(control('direct-passphrase'), findsNothing);
  expect(connect, findsNothing);
  expect(
    tester.widget<FilledButton>(control('direct-probe')).onPressed,
    isNotNull,
  );
  for (final (name, value) in fields) {
    expect(
      tester.widget<TextField>(control(name)).controller!.text == value,
      isTrue,
    );
  }
  final outcomeGeometry = outcomePixels(tester, control('direct-closed-feedback'));
  await checkpoint('disconnect', outcomeGeometry);
  expect(outcomePixels(tester, control('direct-closed-feedback')), outcomeGeometry);

  step('return_home');
  await tapControl(
    tester,
    control('direct-return-home'),
    'linux_return_home',
    reveal: false,
  );
  await waitUi(
    tester,
    () =>
        find.byType(DirectSshPage, skipOffstage: false).evaluate().isEmpty &&
        home.evaluate().length == 1 &&
        control('hosts-direct-ssh').hitTestable().evaluate().length == 1,
    'linux_direct_return_home_timeout',
  );
  expect(tester.state(home), same(homeState));
  expect(control('home-ssh-closed').hitTestable(), findsOneWidget);
  expect(
    tester.widget<Text>(control('home-ssh-closed-title')).data,
    '本机已断开',
  );
  expect(tester.takeException(), isNull);
  final homeGeometry = outcomePixels(tester, control('home-ssh-closed'));
  await checkpoint('complete', homeGeometry);
  expect(outcomePixels(tester, control('home-ssh-closed')), homeGeometry);
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  const directory = String.fromEnvironment('HERDR_FLUTTER_LINUX_DIRECT_DIR');
  testWidgets('native Linux ordinary SSH', (tester) async {
    if (!Platform.isLinux ||
        !kDebugMode ||
        !directory.startsWith('/') ||
        !directory.split('/').last.startsWith('hp-flutter-linux-direct-')) {
      fail('linux_direct_native_fixture_required');
    }
    void publish(String name, Object value) {
      final pending = File('$directory/$name.pending')
        ..writeAsStringSync(jsonEncode(value), flush: true);
      pending.renameSync('$directory/$name.json');
    }

    final targetFile = File('$directory/target.json');
    final target = LinuxTarget.parse(
      jsonDecode(targetFile.readAsStringSync())
          as Map<String, dynamic>,
    );
    if (target.encrypted) targetFile.deleteSync();
    await runLinuxOrdinary(
      tester,
      target,
      step: (phase) => publish('stage', {'phase': phase}),
      checkpoint: (phase, evidence) async {
        publish(phase, evidence);
        final reply = File('$directory/$phase.ok');
        await waitUi(
          tester,
          reply.existsSync,
          'linux_direct_peer_ack_timeout_$phase',
        );
      },
    );
  }, skip: directory.isEmpty);
}
