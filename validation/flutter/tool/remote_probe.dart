// CI-only entry point for the same read-only adapter used by RemotePage.
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import '../lib/remote_adapter.dart';

Future<void> main(List<String> arguments) async {
  var testCase = 'positive';
  final adapter = RemoteReadOnlyAdapter();
  File? output;
  var passed = false;
  try {
    if (Platform.environment['GITHUB_ACTIONS'] != 'true' ||
        !RegExp(r'^\d+$').hasMatch(Platform.environment['GITHUB_RUN_ID'] ?? '') ||
        !(Platform.environment['GITHUB_REF'] ?? '').startsWith('refs/heads/codex/')) {
      throw const RemoteFailure('ci_only');
    }
    if (arguments.length != 6 || arguments[0] != '--config' ||
        arguments[2] != '--case' || arguments[4] != '--output') throw const RemoteFailure('invalid_arguments');
    testCase = arguments[3];
    if (!{'positive','wrong-pin','missing-session','cancel'}.contains(testCase)) throw const RemoteFailure('invalid_arguments');
    final input = File(arguments[1]);
    final prefix = '/tmp/hp-mobile-${Platform.environment['GITHUB_RUN_ID']}-';
    if (!input.absolute.path.startsWith(prefix) || input.resolveSymbolicLinksSync() != input.absolute.path ||
        input.lengthSync() > 32768) throw const RemoteFailure('invalid_fixture_path');
    final proposed = File(arguments[5]);
    if (proposed.parent.absolute.path != input.parent.absolute.path ||
        FileSystemEntity.typeSync(proposed.path,followLinks:false) != FileSystemEntityType.notFound) throw const RemoteFailure('invalid_fixture_path');
    output = proposed;
    final config = RemoteConfig.fromJson(jsonDecode(input.readAsStringSync()) as Map<String,dynamic>);
    if (config.host != '127.0.0.1' || config.port < 1024) throw const RemoteFailure('invalid_fixture_target');
    try {
      await adapter.read(config,onProgress:(generation,phase) {
        if (testCase == 'cancel' && phase == 'snapshot_received') unawaited(adapter.cancel());
      });
      passed = testCase == 'positive' && adapter.evidence.fullFrameReceived;
    } on RemoteFailure {
      final e = adapter.evidence;
      passed = switch(testCase) {
        'wrong-pin' => e.hostKeyChecked && !e.hostKeyMatched && !e.authStarted && e.errorCode == 'host_key_mismatch',
        'missing-session' => e.hostKeyMatched && e.authStarted && e.snapshotReceived && !e.fullFrameReceived &&
          {'session_mismatch','pane_missing','observe_ended'}.contains(e.errorCode),
        'cancel' => e.hostKeyMatched && e.authStarted && e.snapshotReceived && !e.fullFrameReceived && e.errorCode == 'cancelled',
        _ => false,
      };
    }
  } catch (error) {
    adapter.evidence.errorCode = error is RemoteFailure ? error.code : 'probe_failed';
  } finally {
    // Only the allowlisted evidence is written; never stringify errors/config.
    final report = jsonEncode(adapter.evidence.toReport(testCase,passed));
    if (output != null && !output.existsSync()) output.writeAsStringSync('$report\n');
    exitCode = passed ? 0 : 1;
  }
}
