import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart' show kDebugMode;
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:herdr_flutter_probe/direct_ssh_page.dart';
import 'package:terminal_view/terminal_view.dart';

import 'ios_exchange.dart';
import '../test/ios_layout_diagnostics.dart';
import 'direct_ssh_ui_steps.dart';

const enabled = String.fromEnvironment('HERDR_IOS_DIRECT_SSH');
const runId = String.fromEnvironment('HERDR_IOS_RUN_ID');
const targetJson = String.fromEnvironment('HERDR_IOS_DIRECT_TARGET');
const rotationTargetJson = String.fromEnvironment('HERDR_IOS_ROTATION_TARGET');
final directory = '${Directory.systemTemp.path}/herdr-direct-ssh-$runId';

Map<String, dynamic> target({
  String encoded = targetJson,
  bool rotating = false,
}) {
  if (!Platform.isIOS ||
      !kDebugMode ||
      enabled != '1' ||
      !RegExp(r'^\d+$').hasMatch(runId)) {
    throw StateError('direct_ssh_ios_isolated_fixture_required');
  }
  final value = jsonDecode(encoded);
  final keys = {
    'host',
    'port',
    'username',
    'password',
    'fingerprint',
    if (rotating) 'rotatedFingerprint',
  };
  if (value is! Map<String, dynamic> ||
      value.keys.toSet().difference(keys).isNotEmpty ||
      value.length != keys.length ||
      value['host'] != '127.0.0.1' ||
      value['port'] is! int ||
      value['port'] < 1024 ||
      value['port'] > 65535 ||
      value['username'] != 'fixture' ||
      value['password'] is! String ||
      !RegExp(r'^[0-9a-f]{32}$').hasMatch(value['password']) ||
      value['fingerprint'] is! String ||
      !RegExp(r'^SHA256:[A-Za-z0-9+/]{43}$').hasMatch(value['fingerprint']) ||
      (rotating &&
          (value['rotatedFingerprint'] is! String ||
              !RegExp(r'^SHA256:[A-Za-z0-9+/]{43}$')
                  .hasMatch(value['rotatedFingerprint']) ||
              value['rotatedFingerprint'] == value['fingerprint']))) {
    throw StateError('direct_ssh_ios_invalid_target');
  }
  return value;
}

void publish(String name, Object value) {
  final dir = Directory(directory)..createSync(recursive: true);
  final pending = File('${dir.path}/$name.pending')
    ..writeAsStringSync(jsonEncode(value), flush: true);
  pending.renameSync('${dir.path}/$name');
}

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  Map<String, Object> semanticsProbe() => {
    'platformEnabled': binding.platformDispatcher.semanticsEnabled,
    'realPlatformEnabled': ui.PlatformDispatcher.instance.semanticsEnabled,
    'bindingHandles': binding.debugOutstandingSemanticsHandles,
    // The test framework verifies both counters separately.
    // ignore: deprecated_member_use
    'pipelineHandles': binding.pipelineOwner.debugOutstandingSemanticsHandles,
  };
  late Map<String, Object> semanticsBaseline;
  setUpAll(() {
    // Establish the platform semantics handle before testWidgets records its
    // baseline; retain the framework's normal leak checks throughout the test.
    binding.platformDispatcher.semanticsEnabledTestValue = true;
    semanticsBaseline = semanticsProbe();
  });
  tearDownAll(binding.platformDispatcher.clearSemanticsEnabledTestValue);
  var activeFixture = false;
  var privateValues = <String>[];
  final previousReporter = reportTestException;
  reportTestException = (details, description) {
    try {
      if (activeFixture) {
        String safe(String line) {
          for (final value in privateValues) {
            if (value.isNotEmpty) {
              line = line.replaceAll(value, '[redacted]');
              line = line.replaceAll(
                base64Encode(utf8.encode(value)),
                '[redacted]',
              );
            }
          }
          line = line.replaceAll(RegExp(r'-----BEGIN.*'), '[redacted]');
          line = line.replaceAll(
            RegExp(r'(?<![A-Za-z])/(?:[^\s:]+/?)+'),
            '[path]',
          );
          line = line.replaceAll(
            RegExp(r'\b[A-Za-z0-9_+/=-]{24,}\b'),
            '[token]',
          );
          line = line.replaceAll(RegExp(r'[^A-Za-z0-9 .,;:_()\[\]#=+\-]'), ' ');
          line = line.replaceAll(RegExp(r'\s+'), ' ').trim();
          return line.length > 200 ? line.substring(0, 200) : line;
        }

        final type = details.exception.runtimeType.toString();
        final source = RegExp(r'direct_ssh_ui_steps\.dart:(\d+)')
            .firstMatch(details.stack?.toString() ?? '');
        final excerpt = details
            .exceptionAsString()
            .split('\n')
            .take(3)
            .map(safe)
            .where((line) => line.isNotEmpty)
            .toList();
        publish('framework-error.json', {
          'exceptionClass':
              {
                'TestFailure',
                'AssertionError',
                'FlutterError',
                'StateError',
                'TimeoutException',
              }.contains(type)
              ? type
              : 'other',
          'sourceLine': source == null ? null : int.tryParse(source.group(1)!),
          'excerpt': excerpt,
          'semantics': semanticsProbe(),
        });
      }
    } catch (_) {
      // Reporting must never replace or suppress Flutter's original failure.
    } finally {
      previousReporter(details, description);
    }
  };
  testWidgets(
    'iOS Simulator normal homepage to ordinary SSH fingerprint, actual input, echo and disconnect',
    (tester) async {
      var stage = 'fixture_validation';
      var fixtureValidated = false;
      final previousLayoutReporter = FlutterError.onError;
      final overflows = <Map<String, Object?>>[];
      try {
        final config = target();
        final rotation = target(encoded: rotationTargetJson, rotating: true);
        if (rotation['port'] == config['port']) {
          throw StateError('direct_ssh_ios_peers_not_independent');
        }
        fixtureValidated = true;
        activeFixture = true;
        privateValues = [
          config['password'] as String,
          config['username'] as String,
          config['host'] as String,
          config['fingerprint'] as String,
          rotation['password'] as String,
          rotation['fingerprint'] as String,
          rotation['rotatedFingerprint'] as String,
          directory,
        ];
        expect(tester.testTextInput.isRegistered, isFalse);
        initializeIosExchange(Directory(directory), semanticsBaseline);
        FlutterError.onError = (details) {
          try {
            if (overflows.length < 4) {
              final value = iosOverflowDiagnostic(
                details,
                stage: stage,
                view: tester.view,
              );
              if (value != null) {
                overflows.add(value);
                publish('overflow-diagnostic.json', {'events': overflows});
              }
            }
          } catch (_) {
            // Diagnostics cannot replace the original framework error.
          } finally {
            previousLayoutReporter?.call(details);
          }
        };
        void step(String next) {
          stage = next;
          publish('stage.json', {'stage': next});
          if (next == 'home' || next == 'report_data_set') {
            publish('semantics-$next.json', semanticsProbe());
          }
        }

        Future<Map<String, dynamic>> screenshotReply(String filename) async {
          final file = File('$directory/$filename');
          final deadline = DateTime.now().add(const Duration(seconds: 120));
          while (!file.existsSync()) {
            if (DateTime.now().isAfter(deadline)) {
              throw StateError('direct_ssh_ios_screenshot_reply_timeout');
            }
            await tester.pump(const Duration(milliseconds: 100));
          }
          return jsonDecode(file.readAsStringSync()) as Map<String, dynamic>;
        }

        List<int> physicalBounds(Finder finder) {
          final rect = tester.getRect(finder);
          final ratio = tester.view.devicePixelRatio;
          final left = (rect.left * ratio).floor();
          final top = (rect.top * ratio).floor();
          return [
            left,
            top,
            (rect.right * ratio).ceil() - left,
            (rect.bottom * ratio).ceil() - top,
          ];
        }

        Future<void> capture(String name) async {
          if (name == 'rotation-rejected') {
            expect(
              find.byKey(const ValueKey('direct-host-key-change')),
              findsOneWidget,
            );
            expect(find.byKey(const ValueKey('direct-form')), findsNothing);
            expect(find.byKey(const ValueKey('direct-secret')), findsNothing);
            expect(
              find.byKey(const ValueKey('direct-host-key-cancel')),
              findsOneWidget,
            );
            expect(
              find.byKey(const ValueKey('direct-host-key-review')),
              findsOneWidget,
            );
            await tester.pump(const Duration(milliseconds: 100));
            for (final control in [
              find.text('已阻止连接与输入'),
              find.byKey(const ValueKey('direct-host-key-old')),
              find.byKey(const ValueKey('direct-host-key-new')),
              find.byKey(const ValueKey('direct-host-key-cancel')),
              find.byKey(const ValueKey('direct-host-key-review')),
              find.text('目标：fixture@127.0.0.1:${rotation['port']}'),
            ]) {
              expect(control, findsOneWidget);
              final rect = physicalBounds(control);
              expect(rect[0], greaterThanOrEqualTo(0));
              expect(rect[1], greaterThanOrEqualTo(0));
              expect(
                rect[0] + rect[2],
                lessThanOrEqualTo(tester.view.physicalSize.width),
              );
              expect(
                rect[1] + rect[3],
                lessThanOrEqualTo(tester.view.physicalSize.height),
              );
            }
            publish('review-request.json', {
              'tag': 'key-rotation',
              'formAbsent': true,
              'secretAbsent': true,
            });
            expect(await screenshotReply('review-done.json'), {
              'captured': true,
            });
            return;
          }
          if (name == 'connected' || name == 'rotation-connected') {
            final tag = name == 'connected' ? 'ordinary' : 'key-rotation';
            final peer = name == 'connected' ? config : rotation;
            final expectedTarget =
                '${peer['username']}@${peer['host']}:${peer['port']}';
            for (var attempt = 1; attempt <= 12; attempt++) {
              // Only pump/capture here: the single input commit already happened.
              await tester.pump(const Duration(milliseconds: 100));
              final active = find.byKey(const ValueKey('direct-active-target'));
              expect(active, findsOneWidget);
              expect(tester.widget<Text>(active).data, expectedTarget);
              expect(find.byKey(const ValueKey('direct-secret')), findsNothing);
              publish('screen-request.json', {
                'tag': tag,
                'attempt': attempt,
                'observedTarget': expectedTarget,
                'bounds': physicalBounds(find.byType(TerminalView)),
                'targetBounds': physicalBounds(active),
                'viewSize': [
                  tester.view.physicalSize.width.round(),
                  tester.view.physicalSize.height.round(),
                ],
              });
              final reply = await screenshotReply('screen-$tag-$attempt.json');
              if (reply.length != 3 ||
                  reply['tag'] != tag ||
                  reply['attempt'] != attempt ||
                  reply['accepted'] is! bool) {
                throw StateError('direct_ssh_ios_screenshot_reply_invalid');
              }
              if (reply['accepted'] == true) return;
            }
            throw StateError('direct_ssh_ios_screen_pixels_not_verified');
          }
          if (name != 'preconnect') return;
          final secret = find.byKey(const ValueKey('direct-secret'));
          final method = find.byType(SwitchListTile);
          if (secret.evaluate().length != 1 ||
              method.evaluate().length != 1 ||
              !tester.widget<TextField>(secret).obscureText ||
              tester.widget<SwitchListTile>(method).value)
            return;
          // Allow Flutter's brief last-character reveal to expire before any
          // screenshot; the runner only sees the approved synthetic fixture.
          await tester.pump(const Duration(seconds: 2));
          step('screenshot_wait');
          publish('screenshot-request.json', {
            'passwordMasked': true,
            'passwordAuth': true,
          });
          final deadline = DateTime.now().add(const Duration(seconds: 60));
          while (!File('$directory/screenshot-done.json').existsSync() &&
              DateTime.now().isBefore(deadline)) {
            await tester.pump(const Duration(milliseconds: 250));
          }
        }

        await runDirectSshRotationUi(
          tester,
          config: rotation,
          directory: directory,
          platform: 'ios-simulator',
          step: step,
          publish: publish,
          capture: capture,
        );
        await runDirectSshUi(
          tester,
          binding: binding,
          config: config,
          directory: directory,
          platform: 'ios-simulator',
          step: step,
          publish: publish,
          capture: capture,
        );
      } catch (error, stack) {
        if (fixtureValidated) {
          final detail = error.toString();
          final statusFinder = find.byKey(const ValueKey('direct-status'));
          final status = statusFinder.evaluate().length == 1
              ? tester.widget<Text>(statusFinder).data
              : null;
          final statusCode = status == '正在探测主机密钥，尚未发送认证信息。'
              ? 'probe_in_progress'
              : status == '探测失败或超时；未发送认证，请检查目标后重试。'
              ? 'probe_failed'
              : status == '填写连接信息后先探测主机密钥。'
              ? 'probe_idle'
              : status == '已确认本次主机密钥；连接时将重新核对。'
              ? 'fingerprint_confirmed'
              : status == '正在重新核对主机密钥并连接…'
              ? 'connecting'
              : status == '认证失败，请检查凭据。'
              ? 'auth_failed'
              : status == '主机密钥不符，已阻止认证；请重新核对。'
              ? 'key_mismatch'
              : status == '连接失败或超时，请检查网络、密钥与目标。'
              ? 'connect_failed'
              : status == '应用进入后台，连接已关闭；返回后需重新连接，不会重放输入。'
              ? 'background_closed'
              : status == '已断开；未重放输入。'
              ? 'disconnected'
              : status?.startsWith('远端 shell 已结束') == true
              ? 'shell_ended'
              : find.text('已连接 · 输入直接发送到远端 shell').evaluate().isNotEmpty
              ? 'connected'
              : find.byType(DirectSshPage).evaluate().isEmpty
              ? 'page_absent'
              : 'other';
          final connect = find.byKey(const ValueKey('direct-connect'));
          final exists = connect.evaluate().length == 1;
          final probe = find.byKey(const ValueKey('direct-probe'));
          final type = error.runtimeType.toString();
          final line = RegExp(r'direct_ssh_ui_steps\.dart:(\d+)')
              .firstMatch(stack.toString());
          publish('failure.json', {
            'stage': stage,
            'connection': find.byType(DirectSshPage).evaluate().length == 1
                ? (tester.state(
                    find.byType(DirectSshPage),
                  ) as dynamic).connectionDiagnostic
                : null,
            'code': 'direct_ssh_ios_ui_failed',
            'kind': detail.contains('control_not_ready')
                ? 'control_not_ready'
                : detail.contains('ui_timeout')
                ? 'timeout'
                : detail.contains('hitTestable')
                ? 'not_hit_testable'
                : 'other',
            'exceptionClass':
                {'TestFailure', 'StateError', 'FlutterError'}.contains(type)
                ? type
                : 'other',
            'sourceLine': line == null ? null : int.tryParse(line.group(1)!),
            'statusCode': statusCode,
            'appLifecycle': binding.lifecycleState?.name ?? 'unknown',
            'probeEnabled': probe.evaluate().length == 1
                ? tester.widget<OutlinedButton>(probe).onPressed != null
                : null,
            'trustDialogVisible': find
                .byKey(const ValueKey('direct-trust-key'))
                .evaluate()
                .isNotEmpty,
            'connectExists': exists,
            'connectEnabled': exists
                ? tester.widget<FilledButton>(connect).onPressed != null
                : null,
            'connectHitTestable': exists
                ? connect.hitTestable().evaluate().length == 1
                : null,
          });
        }
        rethrow;
      } finally {
        FlutterError.onError = previousLayoutReporter;
      }
    },
  );
}
