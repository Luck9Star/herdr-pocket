import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart' show kDebugMode;
import 'package:flutter/widgets.dart' show Text, ValueKey;
import 'package:flutter_test/flutter_test.dart';
import 'package:terminal_view/terminal_view.dart';
import 'package:integration_test/integration_test.dart';

import 'direct_ssh_ui_steps.dart';

const packageName = 'dev.herdr.herdr_flutter_probe';
const enabled = String.fromEnvironment('HERDR_ANDROID_DIRECT_SSH');
const runId = String.fromEnvironment('HERDR_ANDROID_RUN_ID');
const targetJson = String.fromEnvironment('HERDR_ANDROID_DIRECT_TARGET');
const rotationTargetJson = String.fromEnvironment(
  'HERDR_ANDROID_ROTATION_TARGET',
);
const directory = '/data/user/0/$packageName/cache/herdr-direct-ssh-$runId';

Map<String, dynamic> target({
  String encoded = targetJson,
  bool rotating = false,
}) {
  if (!Platform.isAndroid ||
      !kDebugMode ||
      enabled != '1' ||
      !RegExp(r'^\d+$').hasMatch(runId)) {
    throw StateError('direct_ssh_android_isolated_fixture_required');
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
    throw StateError('direct_ssh_android_invalid_target');
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
  testWidgets(
    'Android homepage host key rotation, ordinary SSH input, echo and disconnect',
    (tester) async {
      var stage = 'fixture_validation';
      var fixtureValidated = false;
      try {
        final config = target();
        final rotation = target(encoded: rotationTargetJson, rotating: true);
        if (rotation['port'] == config['port']) {
          throw StateError('direct_ssh_android_peers_not_independent');
        }
        fixtureValidated = true;
        expect(tester.testTextInput.isRegistered, isFalse);
        if (Directory(directory).existsSync())
          throw StateError('direct_ssh_android_exchange_exists');
        void step(String next) {
          stage = next;
          publish('stage.json', {'stage': next});
        }

        var surfaceConverted = false;
        Future<void> capture(String name) async {
          if (name == 'preconnect') return;
          if (!surfaceConverted) {
            await binding.convertFlutterSurfaceToImage();
            await tester.pump();
            surfaceConverted = true;
          }
          final needsProof =
              name == 'connected' || name == 'rotation-connected';
          final tag = name == 'connected' ? 'ordinary' : 'key-rotation';
          for (var attempt = 1; attempt <= (needsProof ? 12 : 1); attempt++) {
            // A new frame must be submitted before every actual surface capture;
            // the independent host pixel check decides whether it is sufficient.
            await tester.pump(const Duration(milliseconds: 100));
            final bytes = await binding.takeScreenshot(name);
            final pending = File('$directory/$name.png.pending')
              ..writeAsBytesSync(bytes, flush: true);
            pending.renameSync('$directory/$name.png');
            if (!needsProof) return;
            final active = find.byKey(const ValueKey('direct-active-target'));
            expect(active, findsOneWidget);
            final observedTarget = tester.widget<Text>(active).data;
            final peer = name == 'connected' ? config : rotation;
            final expectedTarget =
                '${peer['username']}@${peer['host']}:${peer['port']}';
            expect(observedTarget, expectedTarget);
            final view = find.byType(TerminalView);
            expect(view, findsOneWidget);
            final rect = tester.getRect(view);
            final ratio = tester.view.devicePixelRatio;
            final left = (rect.left * ratio).floor();
            final top = (rect.top * ratio).floor();
            final right = (rect.right * ratio).ceil();
            final bottom = (rect.bottom * ratio).ceil();
            publish('screen-request.json', {
              'tag': tag,
              'attempt': attempt,
              'observedTarget': observedTarget,
              'bounds': [left, top, right - left, bottom - top],
              'viewSize': [
                tester.view.physicalSize.width.round(),
                tester.view.physicalSize.height.round(),
              ],
            });
            final reply = File('$directory/screen-$tag-$attempt.json');
            final deadline = DateTime.now().add(const Duration(seconds: 120));
            while (!reply.existsSync()) {
              if (DateTime.now().isAfter(deadline)) {
                throw StateError('direct_ssh_screen_reply_timeout');
              }
              await tester.pump(const Duration(milliseconds: 100));
            }
            final value = jsonDecode(reply.readAsStringSync());
            if (value is! Map<String, dynamic> ||
                value.length != 3 ||
                value['tag'] != tag ||
                value['attempt'] != attempt ||
                value['accepted'] is! bool) {
              throw StateError('direct_ssh_screen_reply_invalid');
            }
            if (value['accepted'] == true) return;
          }
          throw StateError('direct_ssh_screen_pixels_not_verified');
        }

        await runDirectSshRotationUi(
          tester,
          config: rotation,
          directory: directory,
          step: step,
          publish: publish,
          capture: capture,
        );
        await runDirectSshUi(
          tester,
          binding: binding,
          config: config,
          directory: directory,
          platform: 'android-api35-emulator',
          step: step,
          publish: publish,
          capture: capture,
        );
      } catch (_) {
        if (fixtureValidated) {
          publish('failure.json', {
            'stage': stage,
            'code': 'direct_ssh_android_ui_failed',
          });
        }
        rethrow;
      }
    },
  );
}
