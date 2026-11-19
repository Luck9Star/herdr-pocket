import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart'
    show LogicalKeyboardKey, PhysicalKeyboardKey;
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/direct_ssh_page.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/main.dart' as app;
import 'package:integration_test/integration_test.dart';
import 'package:terminal_view/terminal_view.dart';

import 'direct_ssh_ui_steps.dart'
    show
        control,
        hasMarker,
        openDirectSshFromHome,
        tap,
        tapControl,
        verifyLocalClose,
        verifyReturnHome;

typedef Checkpoint = Future<void> Function(
  String phase,
  Map<String, Object> evidence,
);

class LinuxTarget {
  LinuxTarget.parse(Map<String, dynamic> value)
    : port = value['port'] as int,
      fingerprint = value['fingerprint'] as String,
      password = value['password'] as String {
    if (value.length != 3 ||
        port < 1024 ||
        port > 65535 ||
        !RegExp(r'^SHA256:[A-Za-z0-9+/]{43}$').hasMatch(fingerprint) ||
        !RegExp(r'^[a-f0-9]{32}$').hasMatch(password)) {
      throw StateError('linux_direct_fixture_invalid');
    }
  }

  final int port;
  final String fingerprint;
  final String password;
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
    control('direct-independent-verification').hitTestable(),
    findsOneWidget,
  );
  expect(connect, findsNothing);
  expect(password, findsNothing);
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
        tester.widget<SelectableText>(presentedFingerprint).data ==
            target.fingerprint,
    isTrue,
    reason: 'linux_direct_fingerprint_or_target_mismatch',
  );
  await checkpoint('probe', {'algorithm': algorithm!});
  await tap(
    tester,
    'direct-trust-key',
    requireEnabled: true,
    stableHitPoint: true,
  );

  step('password');
  await waitUi(
    tester,
    () =>
        review.evaluate().isEmpty &&
        password.hitTestable().evaluate().length == 1 &&
        connect.evaluate().length == 1 &&
        ModalRoute.of(tester.element(page))?.isCurrent == true,
    'linux_direct_review_close_timeout',
  );
  expect(control('direct-trust-approved').hitTestable(), findsOneWidget);
  expect(tester.widget<FilledButton>(connect).onPressed, isNull);
  final passwordField = tester.widget<TextField>(password);
  expect(passwordField.obscureText, isTrue);
  final credential = passwordField.controller!;
  expect(credential.text.isEmpty, isTrue);
  await tester.ensureVisible(password);
  await tester.enterText(password, target.password);
  await tester.pump();
  expect(credential.text == target.password, isTrue);
  await tap(
    tester,
    'direct-connect',
    requireEnabled: true,
    stableHitPoint: true,
  );

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
    tester.widget<Text>(bound).data == target.label && credential.text.isEmpty,
    isTrue,
  );
  expect(
    find
        .descendant(
          of: control('direct-terminal-status'),
          matching: find.text('已连接'),
        )
        .hitTestable(),
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
      identical(tester.state<TerminalViewState>(terminalView), terminalState) &&
      tester.widget<Text>(bound).data == target.label;
  await waitUi(
    tester,
    focusedOnBoundTerminal,
    'linux_direct_terminal_focus_timeout',
  );
  // Commit the line once and dispatch desktop Enter to the same focused view.
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
        credential.text.isEmpty &&
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
    () => terminalView.evaluate().isEmpty && bound.evaluate().isEmpty,
    'linux_direct_disconnect_timeout',
  );
  await verifyLocalClose(tester, tester.state(page));
  expect(control('direct-closed-feedback').hitTestable(), findsOneWidget);
  expect(connect, findsNothing);
  expect(
    tester.widget<FilledButton>(control('direct-probe')).onPressed,
    isNotNull,
  );
  for (final (name, value) in fields) {
    expect(tester.widget<TextField>(control(name)).controller!.text, value);
  }
  await checkpoint('disconnect', const {});

  step('return_home');
  await verifyReturnHome(tester);
  expect(tester.state(home), same(homeState));
  expect(control('home-ssh-closed').hitTestable(), findsOneWidget);
  await checkpoint('complete', const {});
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  const directory = String.fromEnvironment('HERDR_FLUTTER_LINUX_DIRECT_DIR');
  testWidgets('native Linux ordinary SSH password', (tester) async {
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

    final target = LinuxTarget.parse(
      jsonDecode(File('$directory/target.json').readAsStringSync())
          as Map<String, dynamic>,
    );
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
