import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import 'linux_direct_ssh_test.dart' show LinuxTarget, runLinuxOrdinary, waitUi;

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
    await runLinuxOrdinary(
      tester,
      target,
      platform: TargetPlatform.windows,
      step: (phase) => publish('stage', {'phase': phase}),
      checkpoint: (phase, evidence) async {
        publish(phase, evidence);
        final reply = File(path('$phase.ok'));
        await waitUi(
          tester,
          reply.existsSync,
          'windows_direct_peer_ack_timeout_$phase',
        );
      },
    );
  }, skip: directory.isEmpty);
}
