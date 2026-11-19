import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart' show kDebugMode;
import 'package:flutter/services.dart' show Clipboard, ClipboardData;
import 'package:flutter/widgets.dart' show Text, ValueKey;
import 'package:flutter_test/flutter_test.dart';
import 'package:terminal_view/terminal_view.dart';
import 'package:integration_test/integration_test.dart';

import 'direct_ssh_ui_steps.dart';

const packageName = 'dev.herdr.herdr_flutter_probe';
const enabled = String.fromEnvironment('HERDR_ANDROID_DIRECT_SSH');
const runId = String.fromEnvironment('HERDR_ANDROID_RUN_ID');
const targetJson = String.fromEnvironment('HERDR_ANDROID_DIRECT_TARGET');
const encryptedCase = String.fromEnvironment(
  'HERDR_ANDROID_ENCRYPTED_KEY_CASE',
);
const encryptedTargetJson = String.fromEnvironment(
  'HERDR_ANDROID_ENCRYPTED_KEY_TARGET',
);
const rotationTargetJson = String.fromEnvironment(
  'HERDR_ANDROID_ROTATION_TARGET',
);
const directory = '/data/user/0/$packageName/cache/herdr-direct-ssh-$runId';

Map<String, dynamic> target({
  String encoded = targetJson,
  bool rotating = false,
  bool encrypted = false,
}) {
  if (!Platform.isAndroid ||
      !kDebugMode ||
      enabled != '1' ||
      !RegExp(r'^\d+$').hasMatch(runId)) {
    throw StateError('direct_ssh_android_isolated_fixture_required');
  }
  dynamic value;
  try {
    value = jsonDecode(encoded);
  } catch (_) {
    throw StateError('direct_ssh_android_invalid_target');
  }
  final keys = {
    'host',
    'port',
    'username',
    if (!encrypted) 'password',
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
      (!encrypted &&
          (value['password'] is! String ||
              !RegExp(r'^[0-9a-f]{32}$').hasMatch(value['password']))) ||
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
  test('terminal markers respect soft and hard line boundaries', () {
    for (final width in [8, 12, 20, 40]) {
      final terminal = Terminal()..resize(width, 24);
      terminal.write('POCKET-ANDROID-READY\r\n\$ ');
      expect(
        hasMarker(terminal, 'POCKET-ANDROID-READY'),
        isTrue,
        reason: 'soft-wrapped welcome at $width columns',
      );
      expect(hasMarker(terminal, 'POCKET-ANDROID-SSH-OK'), isFalse);
      final echo = Terminal()..resize(width, 24);
      echo.write('\r\n\x1b[32mPOCKET-ANDROID-SSH-OK\x1b[0m\r\n');
      expect(
        hasMarker(echo, 'POCKET-ANDROID-SSH-OK'),
        isTrue,
        reason: 'soft-wrapped remote echo at $width columns',
      );
    }
    final split = Terminal()..resize(12, 24);
    split.write('POCKET-AND\r\nROID-READY');
    expect(hasMarker(split, 'POCKET-ANDROID-READY'), isFalse);
    expect(hasMarker(split, ''), isFalse);
  });
  testWidgets(
    'Android homepage host key rotation, ordinary SSH input, echo and disconnect',
    (tester) async {
      var stage = 'fixture_validation';
      var fixtureValidated = false;
      try {
        if (encryptedCase != '' && encryptedCase != '1') {
          throw StateError('direct_ssh_android_invalid_case');
        }
        final encrypted = encryptedCase == '1';
        final config = encrypted
            ? target(encoded: encryptedTargetJson, encrypted: true)
            : target();
        final rotation = encrypted
            ? null
            : target(encoded: rotationTargetJson, rotating: true);
        if (rotation != null && rotation['port'] == config['port']) {
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

        if (encrypted) {
          step('encrypted_waiting_private');
          final incoming = File(
            '/data/user/0/$packageName/cache/herdr-key-$runId.json',
          );
          final deadline = DateTime.now().add(const Duration(seconds: 120));
          while (!incoming.existsSync()) {
            if (DateTime.now().isAfter(deadline)) {
              throw StateError('direct_ssh_android_private_input_timeout');
            }
            await tester.pump(const Duration(milliseconds: 100));
          }
          dynamic secret;
          try {
            secret = jsonDecode(incoming.readAsStringSync());
          } catch (_) {
            throw StateError('direct_ssh_android_private_input_invalid');
          } finally {
            incoming.deleteSync();
          }
          expect(incoming.existsSync(), isFalse);
          if (secret is! Map<String, dynamic> ||
              secret.length != 2 ||
              !secret.containsKey('privateKey') ||
              !secret.containsKey('passphrase') ||
              secret['privateKey'] is! String ||
              (secret['privateKey'] as String).length > 8192 ||
              !RegExp(
                r'^-----BEGIN OPENSSH PRIVATE KEY-----\n[A-Za-z0-9+/=\n]+\n-----END OPENSSH PRIVATE KEY-----\n?$',
              ).hasMatch(secret['privateKey']) ||
              secret['passphrase'] is! String ||
              !RegExp(r'^[0-9a-f]{32}$').hasMatch(secret['passphrase'])) {
            throw StateError('direct_ssh_android_private_input_invalid');
          }
          config.addAll(secret);
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
            final peer = name == 'connected' ? config : rotation!;
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

        if (encrypted) {
          await runEncryptedDirectSshUi(
            tester,
            binding: binding,
            config: config,
            directory: directory,
            platform: 'android-api35-emulator',
            step: step,
            publish: publish,
            capture: capture,
          );
          return;
        }
        await runDirectSshRotationUi(
          tester,
          config: rotation!,
          directory: directory,
          platform: 'android-api35-emulator',
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
      } finally {
        if (fixtureValidated && Platform.isAndroid && encryptedCase == '1') {
          await tester.runAsync(
            () => Clipboard.setData(const ClipboardData(text: '')),
          );
        }
      }
    },
  );
}
