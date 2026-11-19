import 'dart:convert';
import 'dart:io';
import 'dart:ui' show FlutterView, Size;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart' show ButtonStyleButton, OutlinedButton;
import 'package:flutter/rendering.dart' show DiagnosticsDebugCreator, RenderBox;
import 'package:flutter/services.dart'
    show MissingPluginException, PlatformException;
import 'package:flutter/widgets.dart' show DebugCreator, Element, State, Text;
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/direct_ssh_page.dart';
import 'package:integration_test/integration_test.dart';

import 'direct_ssh_ui_steps.dart' show control, tapControl;
import 'linux_direct_ssh_test.dart' show LinuxTarget, runLinuxOrdinary, waitUi;

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

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  const directory = String.fromEnvironment('HERDR_FLUTTER_WINDOWS_DIRECT_DIR');
  testWidgets('native Windows ordinary SSH password', (tester) async {
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
    if (value.length != 3 || !value.containsKey('password')) {
      fail('windows_direct_password_fixture_required');
    }
    final target = LinuxTarget.parse(value);
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
    try {
      await runLinuxOrdinary(
        tester,
        target,
        platform: TargetPlatform.windows,
        step: step,
        verifyHome: (home, homeState) =>
            _verifyWindowsReturnHome(tester, home, homeState, step),
        checkpoint: (phase, evidence) async {
          if (phase == 'complete') step('return_home_publish');
          publish(phase, evidence);
          final reply = File(path('$phase.ok'));
          await waitUi(
            tester,
            reply.existsSync,
            'windows_direct_peer_ack_timeout_$phase',
          );
          if (phase == 'complete') step('return_home_acknowledged');
        },
      );
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
