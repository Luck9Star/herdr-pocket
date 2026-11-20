import 'dart:convert';
import 'dart:io';
import 'dart:ui' show FlutterView, Size;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart'
    show
        ButtonStyleButton,
        EditableText,
        EditableTextState,
        FilledButton,
        FocusManager,
        ModalRoute,
        OutlinedButton,
        SelectableText,
        TextButton,
        TextField,
        Theme;
import 'package:flutter/rendering.dart'
    show DiagnosticsDebugCreator, RenderBox, SemanticsNode;
import 'package:flutter/services.dart'
    show
        LogicalKeyboardKey,
        MissingPluginException,
        PhysicalKeyboardKey,
        PlatformException;
import 'package:flutter/widgets.dart' show DebugCreator, Element, State, Text, View;
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
        verifyLocalClose;
import 'linux_direct_ssh_test.dart'
    show
        Checkpoint,
        LinuxTarget,
        outcomePixels,
        reviewLinuxFingerprint,
        runLinuxOrdinary,
        visiblePixels,
        waitUi;

const _diagnosticAnchors = {
  'app-sidebar',
  'direct-form',
  'direct-page-header',
  'direct-trust-header',
  'direct-closed-feedback',
  'direct-active-target',
  'host-catalog-list',
  'home-empty-card',
  'home-ssh-closed',
};
const _diagnosticWidgets = {'Column', 'Row', 'Flex', 'Stack', 'ListView'};

List<int>? _diagnosticSize(Size size) {
  if (!size.width.isFinite ||
      !size.height.isFinite ||
      size.width < 0 ||
      size.height < 0 ||
      size.width > 16384 ||
      size.height > 16384) {
    return null;
  }
  return [size.width.round(), size.height.round()];
}

Map<String, Object> windowsFrameworkError(
  FlutterErrorDetails details,
  FlutterView view, {
  required String phase,
  required bool returnTapStarted,
}) {
  final error = details.exception;
  final evidence = <String, Object>{
    'phase': phase,
    'returnTapStarted': returnTapStarted,
    'kind': switch (error) {
      FlutterError() => 'FlutterError',
      AssertionError() => 'AssertionError',
      StateError() => 'StateError',
      TypeError() => 'TypeError',
      ArgumentError() => 'ArgumentError',
      PlatformException() => 'PlatformException',
      MissingPluginException() => 'MissingPluginException',
      _ => 'Other',
    },
    'library': switch (details.library) {
      'rendering library' => 'rendering',
      'widgets library' => 'widgets',
      'scheduler library' => 'scheduler',
      'services library' => 'services',
      'gestures library' => 'gestures',
      'foundation library' => 'foundation',
      'Flutter test framework' => 'test',
      _ => 'other',
    },
  };
  final viewport = _diagnosticSize(view.physicalSize);
  if (viewport != null) evidence['viewportPx'] = viewport;
  final scale = view.devicePixelRatio;
  if (scale.isFinite && scale > 0 && scale <= 8) {
    evidence['dprMilli'] = (scale * 1000).round();
  }
  if (error is FlutterError && details.library == 'rendering library') {
    final overflow = RegExp(
      r'^A RenderFlex overflowed by (\d{1,5}(?:\.\d{1,3})?) '
      r'pixels on the (left|right|top|bottom)\.$',
    ).firstMatch(error.toString().trim());
    if (overflow != null) {
      evidence['overflow'] = {
        'pixels': double.parse(overflow[1]!),
        'side': overflow[2]!,
      };
    }
  }
  final stack = details.stack;
  if (stack != null) {
    final frame = RegExp(
      r'\(package:herdr_flutter_probe/(direct_ssh_page|host_catalog_page|'
      r'main|design_tokens)\.dart:([1-9]\d{0,4})(?::\d{1,5})?\)',
    ).firstMatch(FlutterError.demangleStackTrace(stack).toString());
    if (frame != null) {
      evidence['frame'] = {'source': frame[1]!, 'line': int.parse(frame[2]!)};
    }
  }
  // Rendering diagnostics often have no stack. Inspect the live creator
  // without serializing the widget tree, its properties or source paths.
  try {
    final collector = details.informationCollector;
    if (collector != null) {
      for (final node in collector().whereType<DiagnosticsDebugCreator>()) {
        final creator = node.value;
        if (creator is! DebugCreator) continue;
        final element = creator.element;
        final kind = element.widget.runtimeType.toString();
        if (_diagnosticWidgets.contains(kind)) evidence['creator'] = kind;
        final render = element.renderObject;
        if (render is RenderBox && render.hasSize) {
          final size = _diagnosticSize(render.size);
          if (size != null) evidence['renderSize'] = size;
        }
        bool findAnchor(Element current) {
          final key = current.widget.key;
          if (key is ValueKey<String> &&
              _diagnosticAnchors.contains(key.value)) {
            evidence['anchor'] = key.value;
            return false;
          }
          return true;
        }

        if (findAnchor(element)) element.visitAncestorElements(findAnchor);
        break;
      }
    }
  } catch (_) {
    // Some errors occur after disposal. Basic class and phase still apply.
  }
  return evidence;
}

Future<void> _verifyWindowsReturnHome(
  WidgetTester tester,
  Finder home,
  State homeState,
  void Function(String) step,
) async {
  String? lastReturnStep;
  void returnStep(String stage) {
    if (stage == lastReturnStep) return;
    lastReturnStep = stage;
    step('return_home_$stage');
  }

  final returnButton = control('direct-return-home');
  var readyToReturn = false;
  await tapControl(
    tester,
    returnButton,
    'linux_return_home',
    onObservation: (stage, ready) {
      readyToReturn = ready;
      returnStep('button_$stage');
    },
    beforeTap: () {
      if (readyToReturn) {
        returnStep('button_enabled');
        expect(tester.widget<OutlinedButton>(returnButton).onPressed, isNotNull);
        returnStep('tap');
      }
    },
  );
  final homeNotice = control('home-ssh-closed');
  final homeEntry = control('hosts-direct-ssh').hitTestable();
  final homeTitle = find.descendant(
    of: homeNotice,
    matching: control('home-ssh-closed-title'),
  );
  await waitUi(tester, () {
    if (find.byType(DirectSshPage, skipOffstage: false).evaluate().isNotEmpty) {
      returnStep('route');
      return false;
    }
    if (home.evaluate().length != 1) {
      returnStep('catalog');
      return false;
    }
    if (homeEntry.evaluate().length != 1) {
      returnStep('entry');
      return false;
    }
    if (tester.widget<ButtonStyleButton>(homeEntry).onPressed == null) {
      returnStep('entry_disabled');
      return false;
    }
    if (homeNotice.hitTestable().evaluate().length != 1 ||
        homeTitle.hitTestable().evaluate().length != 1) {
      returnStep('notice');
      return false;
    }
    return true;
  }, 'linux_direct_return_home_timeout');
  returnStep('catalog_identity');
  expect(tester.state(home), same(homeState));
  returnStep('receipt');
  expect(homeNotice.hitTestable(), findsOneWidget);
  expect(tester.widget<Text>(homeTitle).data, '本机已断开');
  returnStep('flutter_exception');
  expect(tester.takeException(), isNull);
  returnStep('geometry');
}

// The shared fingerprint witness needs only target metadata. Its encrypted
// Linux fixture path has a different credential policy and is not used here.
class WindowsKeyTarget implements LinuxTarget {
  const WindowsKeyTarget(this.port, this.fingerprint);

  @override
  final int port;
  @override
  final String fingerprint;
  @override
  String get label => 'fixture@127.0.0.1:$port';
  @override
  bool get encrypted => false;
  @override
  Null get password => null;
  @override
  Null get privateKey => null;
  @override
  Null get passphrase => null;
  @override
  Null get wrongPassphrase => null;
  @override
  Null get rotatedFingerprint => null;
}

bool windowsDirectSshHomeReady(WidgetTester tester, Finder home) {
  if (home.evaluate().length != 1) return false;
  final entry = find.descendant(
    of: home,
    matching: control('hosts-direct-ssh'),
  ).hitTestable();
  if (entry.evaluate().length != 1) return false;
  final button = tester.widget(entry);
  return button is ButtonStyleButton && button.onPressed != null;
}

Future<void> runWindowsDirectSshPublicKey(
  WidgetTester tester,
  WindowsKeyTarget target,
  String privateKey, {
  required void Function(String) step,
  required Checkpoint checkpoint,
}) async {
  step('home');
  await tester.runAsync(app.main);
  final home = find.byType(HostCatalogPage);
  await waitUi(
    tester,
    () => windowsDirectSshHomeReady(tester, home),
    'windows_direct_publickey_home_timeout',
  );
  final catalog = tester.widget<HostCatalogPage>(home);
  final homeState = tester.state(home);
  expect(
    catalog.catalog == null &&
        catalog.adapterFactory == null &&
        catalog.keys == null,
    isTrue,
  );

  step('form');
  await openDirectSshFromHome(tester);
  final page = find.byType(DirectSshPage);
  final view = View.of(tester.element(page));
  expect(Theme.of(tester.element(page)).platform, TargetPlatform.windows);
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
      pemField = control('direct-secret');
  expect(connect, findsNothing);
  expect(pemField, findsNothing);
  step('probe');
  await reviewLinuxFingerprint(
    tester,
    target,
    target.fingerprint,
    checkpoint,
    'probe',
  );

  step('private_key');
  final approvedTarget = control('direct-target-value');
  await waitUi(
    tester,
    () =>
        ModalRoute.of(tester.element(page))?.isCurrent == true &&
        control('direct-trust-header').evaluate().isEmpty &&
        control('direct-trust-approved').hitTestable().evaluate().length == 1 &&
        pemField.hitTestable().evaluate().length == 1 &&
        connect.evaluate().length == 1,
    'windows_direct_publickey_review_close_timeout',
  );
  expect(
    tester.widget<SelectableText>(approvedTarget).data == target.label,
    isTrue,
  );
  expect(tester.widget<TextField>(pemField).obscureText, isTrue);
  expect(tester.widget<TextField>(pemField).controller!.text.isEmpty, isTrue);
  expect(tester.widget<FilledButton>(connect).onPressed, isNull);
  final keyMode = control('direct-auth-key');
  await tapControl(
    tester,
    keyMode,
    'windows_key_mode',
    beforeTap: () =>
        expect(tester.widget<OutlinedButton>(keyMode).onPressed, isNotNull),
  );

  final passphraseField = control('direct-passphrase');
  final editable = find.descendant(
    of: pemField,
    matching: find.byType(EditableText),
  );
  await tapControl(
    tester,
    pemField,
    'windows_pem',
    beforeTap: () {
      final pem = tester.widget<TextField>(pemField);
      expect(
        pem.enabled != false && !pem.obscureText && pem.maxLines != 1,
        isTrue,
        reason: 'windows_direct_publickey_pem_not_ready',
      );
    },
  );
  await waitUi(
    tester,
    () =>
        editable.evaluate().length == 1 &&
        tester
            .state<EditableTextState>(editable)
            .widget
            .focusNode
            .hasPrimaryFocus,
    'windows_direct_publickey_focus_timeout',
  );
  final editor = tester.state<EditableTextState>(editable);
  final input = editor.widget;
  final passphrase = tester.widget<TextField>(passphraseField);
  bool focusBound() =>
      editable.evaluate().length == 1 &&
      identical(View.of(tester.element(editable)), view) &&
      identical(tester.state<EditableTextState>(editable), editor) &&
      identical(editor.widget.controller, input.controller) &&
      identical(editor.widget.focusNode, input.focusNode) &&
      input.focusNode.hasPrimaryFocus;
  bool credentialsEmpty() =>
      input.controller.text.isEmpty && passphrase.controller!.text.isEmpty;
  expect(
    focusBound() &&
        !input.obscureText &&
        !input.readOnly &&
        passphrase.obscureText &&
        credentialsEmpty(),
    isTrue,
  );
  tester.testTextInput.enterText(privateKey);
  await tester.idle();
  await tester.pump();
  expect(
    focusBound() &&
        input.controller.text == privateKey &&
        passphrase.controller!.text.isEmpty &&
        tester.widget<SelectableText>(approvedTarget).data == target.label,
    isTrue,
    reason: 'windows_direct_publickey_readback_failed',
  );
  final semantics = tester.ensureSemantics();
  bool semanticKeyAbsent() {
    // Inspect values in memory only; never publish the private key.
    final root =
        // ignore: deprecated_member_use
        tester.binding.pipelineOwner.semanticsOwner!.rootSemanticsNode!;
    var absent = true;
    void inspect(SemanticsNode node) {
      final data = node.getSemanticsData();
      final parts = privateKey.split('\n').where((line) => line.length >= 20);
      if (parts.any(
        (line) => data.label.contains(line) || data.value.contains(line),
      )) {
        absent = false;
      }
      node.visitChildren((child) {
        inspect(child);
        return true;
      });
    }

    inspect(root);
    return absent;
  }

  final editPem = control('direct-edit-pem');
  Future<void> blurAndVerify() async {
    await tapControl(tester, passphraseField, 'windows_passphrase');
    await waitUi(
      tester,
      () =>
          pemField.evaluate().isEmpty &&
          editPem.hitTestable().evaluate().length == 1,
      'windows_direct_publickey_collapse_timeout',
    );
    expect(editable, findsNothing);
    expect(find.text('已填写私钥 · 重新编辑').hitTestable(), findsOneWidget);
    expect(
      semanticKeyAbsent(),
      isTrue,
      reason: 'windows_direct_publickey_semantics_exposed',
    );
    expect(passphrase.controller!.text.isEmpty, isTrue);
  }

  await blurAndVerify();
  await tapControl(tester, editPem, 'windows_pem_reopen');
  await waitUi(
    tester,
    () =>
        editable.evaluate().length == 1 &&
        tester
            .state<EditableTextState>(editable)
            .widget
            .focusNode
            .hasPrimaryFocus,
    'windows_direct_publickey_reopen_focus_timeout',
  );
  final reopened = tester.state<EditableTextState>(editable).widget;
  expect(
    identical(View.of(tester.element(editable)), view) &&
        reopened.controller.text == privateKey &&
        !reopened.obscureText &&
        !reopened.readOnly &&
        passphrase.controller!.text.isEmpty,
    isTrue,
    reason: 'windows_direct_publickey_reopen_readback_failed',
  );
  await blurAndVerify();
  semantics.dispose();
  await checkpoint('key_entry', const {
    'privateKeyExact': true,
    'passphraseEmpty': true,
    'collapsedSemanticsAbsent': true,
    'summaryHit': true,
    'reopenedExactFocused': true,
    'collapsedAgain': true,
  });
  await tap(
    tester,
    'direct-connect',
    requireEnabled: true,
    stableHitPoint: true,
    beforeTap: () => expect(
      pemField.evaluate().isEmpty &&
          editPem.hitTestable().evaluate().length == 1 &&
          passphrase.controller!.text.isEmpty &&
          tester.widget<SelectableText>(approvedTarget).data == target.label,
      isTrue,
    ),
  );
  privateKey = '';

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
    'windows_direct_publickey_terminal_timeout',
  );
  final terminal = tester.widget<TerminalView>(terminalView).terminal;
  final terminalState = tester.state<TerminalViewState>(terminalView);
  bool targetBound() =>
      terminalView.evaluate().length == 1 &&
      identical(View.of(tester.element(terminalView)), view) &&
      identical(tester.state<TerminalViewState>(terminalView), terminalState) &&
      tester.widget<Text>(bound).data == target.label;
  expect(targetBound() && credentialsEmpty(), isTrue);
  expect(
    find
        .descendant(
          of: control('direct-terminal-status'),
          matching: find.text('已连接'),
        )
        .hitTestable(),
    findsOneWidget,
  );
  await checkpoint('connected', const {});

  step('input');
  await tapControl(tester, terminalView, 'windows_terminal', reveal: false);
  bool inputBound() =>
      targetBound() &&
      terminalState.hasInputConnection &&
      identical(
        FocusManager.instance.primaryFocus?.context
            ?.findAncestorStateOfType<TerminalViewState>(),
        terminalState,
      );
  await waitUi(
    tester,
    inputBound,
    'windows_direct_publickey_terminal_focus_timeout',
  );
  expect(find.widgetWithText(TextButton, 'Enter').hitTestable(), findsNothing);
  tester.testTextInput.enterText('hp-check');
  await tester.pump();
  expect(inputBound(), isTrue);
  await tester.sendKeyEvent(
    LogicalKeyboardKey.enter,
    physicalKey: PhysicalKeyboardKey.enter,
  );
  await waitUi(
    tester,
    () => hasMarker(terminal, 'POCKET-ANDROID-SSH-OK'),
    'windows_direct_publickey_echo_timeout',
  );

  step('capture');
  expect(
    targetBound() &&
        credentialsEmpty() &&
        control('direct-form').evaluate().isEmpty,
    isTrue,
  );
  final geometry = visiblePixels(tester, terminalView, bound);
  await checkpoint('capture', geometry);
  expect(visiblePixels(tester, terminalView, bound), geometry);
  expect(targetBound(), isTrue);

  step('disconnect');
  final disconnect = control('direct-desktop-disconnect');
  expect(disconnect.hitTestable(), findsOneWidget);
  expect(tester.widget<TextButton>(disconnect).onPressed, isNotNull);
  await tapControl(tester, disconnect, 'windows_disconnect', reveal: false);
  await waitUi(
    tester,
    () =>
        terminalView.evaluate().isEmpty &&
        bound.evaluate().isEmpty &&
        control('direct-form').evaluate().length == 1 &&
        control('direct-status').evaluate().length == 1 &&
        tester.widget<Text>(control('direct-status')).data == '本机已断开',
    'windows_direct_publickey_disconnect_timeout',
  );
  await verifyLocalClose(tester, tester.state(page));
  expect(credentialsEmpty(), isTrue);
  expect(pemField, findsNothing);
  expect(passphraseField, findsNothing);
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
  final closed = control('direct-closed-feedback');
  final outcomeGeometry = outcomePixels(tester, closed);
  await checkpoint('disconnect', outcomeGeometry);
  expect(outcomePixels(tester, closed), outcomeGeometry);
  step('return_home');
  await _verifyWindowsReturnHome(tester, home, homeState, step);
  final homeNotice = control('home-ssh-closed');
  final homeGeometry = outcomePixels(tester, homeNotice);
  await checkpoint('complete', homeGeometry);
  expect(outcomePixels(tester, homeNotice), homeGeometry);
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  const directory = String.fromEnvironment('HERDR_FLUTTER_WINDOWS_DIRECT_DIR');
  const publicKey = bool.fromEnvironment('HERDR_FLUTTER_WINDOWS_DIRECT_PUBLICKEY');
  const testName = publicKey
      ? 'native Windows ordinary SSH public key'
      : 'native Windows ordinary SSH password';
  testWidgets(testName, (tester) async {
    if (!Platform.isWindows ||
        !kDebugMode ||
        !RegExp(r'^[A-Za-z]:[\\/]').hasMatch(directory) ||
        !directory
            .split(RegExp(r'[\\/]'))
            .last
            .startsWith('hp-flutter-windows-direct-')) {
      fail('windows_direct_native_fixture_required');
    }

    String path(String name) => '$directory${Platform.pathSeparator}$name';
    void publish(String name, Object value) {
      final pending = File(path('$name.pending'))
        ..writeAsStringSync(jsonEncode(value), flush: true);
      pending.renameSync(path('$name.json'));
    }

    final targetFile = File(path('target.json'));
    final value =
        jsonDecode(targetFile.readAsStringSync()) as Map<String, dynamic>;
    targetFile.deleteSync();
    final LinuxTarget target;
    String? privateKey;
    if (publicKey) {
      final port = value['port'];
      final fingerprint = value['fingerprint'];
      final pem = value['privateKey'];
      if (value.length != 3 ||
          port is! int || port < 1024 || port > 65535 ||
          fingerprint is! String ||
          !RegExp(r'^SHA256:[A-Za-z0-9+/]{43}$').hasMatch(fingerprint) ||
          pem is! String ||
          !pem.startsWith('-----BEGIN OPENSSH PRIVATE KEY-----\n') ||
          !pem.trimRight().endsWith('-----END OPENSSH PRIVATE KEY-----')) {
        fail('windows_direct_publickey_fixture_required');
      }
      target = WindowsKeyTarget(port, fingerprint);
      privateKey = pem;
    } else {
      if (value.length != 3 || !value.containsKey('password')) {
        fail('windows_direct_password_fixture_required');
      }
      target = LinuxTarget.parse(value);
    }
    value.clear();
    publish('window', {'processId': pid});
    var currentPhase = 'window';
    var returnTapStarted = false;
    var observedFrameworkError = false;
    void step(String phase) {
      currentPhase = phase;
      if (phase == 'return_home_tap') returnTapStarted = true;
      publish('stage', {'phase': phase});
    }

    final bindingHandler = FlutterError.onError;
    expect(bindingHandler, isNotNull);
    FlutterError.onError = (details) {
      if (!observedFrameworkError) {
        observedFrameworkError = true;
        try {
          publish(
            'framework-error',
            windowsFrameworkError(
              details,
              tester.view,
              phase: currentPhase,
              returnTapStarted: returnTapStarted,
            ),
          );
        } catch (_) {
          // Failure to record diagnostics never overrides the binding error.
        }
      }
      bindingHandler!(details);
    };
    Future<void> checkpoint(String phase, Map<String, Object> evidence) async {
      if (phase == 'complete') step('return_home_publish');
      publish(phase, evidence);
      final reply = File(path('$phase.ok'));
      await waitUi(
        tester,
        reply.existsSync,
        'windows_direct_peer_ack_timeout_$phase',
      );
      if (phase == 'complete') step('return_home_acknowledged');
    }
    try {
      if (publicKey) {
        final verification = runWindowsDirectSshPublicKey(
          tester,
          target as WindowsKeyTarget,
          privateKey!,
          step: step,
          checkpoint: checkpoint,
        );
        privateKey = null;
        await verification;
      } else {
        await runLinuxOrdinary(
          tester,
          target,
          platform: TargetPlatform.windows,
          step: step,
          verifyHome: (home, homeState) =>
              _verifyWindowsReturnHome(tester, home, homeState, step),
          checkpoint: checkpoint,
        );
      }
      expect(
        observedFrameworkError,
        isFalse,
        reason: 'windows_direct_framework_error',
      );
    } finally {
      FlutterError.onError = bindingHandler;
    }
  }, skip: directory.isEmpty);
}
