import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart' show kDebugMode;
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'direct_ssh_ui_steps.dart';

const packageName = 'dev.herdr.herdr_flutter_probe';
const enabled = String.fromEnvironment('HERDR_ANDROID_DIRECT_SSH');
const runId = String.fromEnvironment('HERDR_ANDROID_RUN_ID');
const targetJson = String.fromEnvironment('HERDR_ANDROID_DIRECT_TARGET');
const directory = '/data/user/0/$packageName/cache/herdr-direct-ssh-$runId';

Map<String, dynamic> target() {
  if (!Platform.isAndroid ||
      !kDebugMode ||
      enabled != '1' ||
      !RegExp(r'^\d+$').hasMatch(runId)) {
    throw StateError('direct_ssh_android_isolated_fixture_required');
  }
  final value = jsonDecode(targetJson);
  const keys = {'host', 'port', 'username', 'password', 'fingerprint'};
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
      !RegExp(r'^SHA256:[A-Za-z0-9+/]{43}$').hasMatch(value['fingerprint'])) {
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
    'Android normal homepage to ordinary SSH fingerprint, actual input, echo and disconnect',
    (tester) async {
      var stage = 'fixture_validation';
      var fixtureValidated = false;
      try {
        final config = target();
        fixtureValidated = true;
        expect(tester.testTextInput.isRegistered, isFalse);
        if (Directory(directory).existsSync())
          throw StateError('direct_ssh_android_exchange_exists');
        void step(String next) {
          stage = next;
          publish('stage.json', {'stage': next});
        }

        Future<void> capture(String name) async {
          if (name == 'preconnect') return;
          if (name == 'home') {
            await binding.convertFlutterSurfaceToImage();
            await tester.pump();
          }
          final bytes = await binding.takeScreenshot(name);
          File('$directory/$name.png').writeAsBytesSync(bytes, flush: true);
        }

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
