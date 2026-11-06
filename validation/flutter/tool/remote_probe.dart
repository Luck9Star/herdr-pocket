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
    if (!{'positive','wrong-pin','missing-session','cancel','observe-positive','observe-cancel','observe-reconnect'}.contains(testCase)) throw const RemoteFailure('invalid_arguments');
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
    if (testCase.startsWith('observe-')) {
      Future<bool> observeOnce() async {
        var intentionalStop = false,selected = false;
        try {
          await adapter.observe(config,onDashboard:(dashboard) {
            if (selected || !dashboard.selectable) return;
            final matches = dashboard.panes.where((p) => p.paneId == config.paneId).toList();
            if (matches.length != 1) throw const RemoteFailure('pane_missing');
            adapter.selectTarget(dashboard.generation,matches.single); selected = true;
          },onFrame:(generation,paneId,frame) {
            final evidence = adapter.evidence;
            final enough = testCase == 'observe-cancel' ? evidence.frameCount >= 1 :
              evidence.frameCount >= (testCase == 'observe-positive' ? 3 : 2) && evidence.deltaFrames >= 1;
            if (enough) { intentionalStop = true; unawaited(adapter.cancel()); }
          });
        } on RemoteFailure catch (failure) {
          return intentionalStop && failure.code == 'cancelled' && adapter.evidence.errorCode == 'cancelled';
        }
        return false;
      }
      final first = await observeOnce();
      final firstFrames = adapter.evidence.frameCount, firstDeltas = adapter.evidence.deltaFrames;
      final firstHighWater = adapter.evidence.bufferHighWaterBytes;
      if (testCase == 'observe-reconnect' && first) {
        // A second explicit call on the same adapter; no automatic retry path.
        passed = await observeOnce() && adapter.evidence.connectionCount == 2;
        adapter.evidence.frameCount += firstFrames;
        adapter.evidence.deltaFrames += firstDeltas;
        if (firstHighWater > adapter.evidence.bufferHighWaterBytes) adapter.evidence.bufferHighWaterBytes = firstHighWater;
      } else { passed = first; }
    } else {
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
