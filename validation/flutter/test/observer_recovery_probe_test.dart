import 'dart:async';
import 'package:flutter_test/flutter_test.dart';
import '../lib/remote_adapter.dart';
import '../tool/remote_probe.dart' show runObserverRecovery;
import 'remote_test_data.dart';

class RecoveryScript extends RemoteReadOnlyAdapter {
  RecoveryScript(this.mode);
  final String mode;
  final ended = Completer<RemoteSnapshot>();
  late FrameConsumer frames;
  var epoch = 0, resumes = 0, cancellations = 0;
  @override
  Future<RemoteSnapshot> observe(RemoteConfig config,
      {required DashboardConsumer onDashboard,required FrameConsumer onFrame,RemoteProgress? onProgress}) {
    frames = onFrame;
    evidence.connectionCount = 1;
    scheduleMicrotask(() {
      onDashboard(RemoteDashboard(1,'probe',[RemotePane(config.paneId,'term_1234')],freshness:DashboardFreshness.fresh));
      frames(1,config.paneId,const RemoteFrame(1,true,'',observationEpoch:0));
    });
    return ended.future;
  }
  @override void selectTarget(int generation,RemotePane target) {}
  @override bool pauseObservation() => mode != 'pause-failed';
  @override bool resumeObservation() {
    if (mode == 'resume-failed') return false;
    resumes++; epoch++;
    scheduleMicrotask(() {
      if (mode == 'connection-changed') evidence.connectionCount = 2;
      if ((mode.startsWith('wrong-generation-') || mode.startsWith('wrong-pane-')) && mode.endsWith('-$resumes')) {
        final generation = mode.startsWith('wrong-generation-') ? 2 : 1;
        final paneId = mode.startsWith('wrong-pane-') ? 'w9:p9' : 'w1:p1';
        frames(generation,paneId,RemoteFrame(1,true,'',observationEpoch:epoch));
        frames(generation,paneId,RemoteFrame(2,false,'',observationEpoch:epoch));
        return;
      }
      // Simulate a stale delta already queued before the new full as well.
      frames(1,'w1:p1',RemoteFrame(2,false,'',observationEpoch:epoch - 1));
      frames(1,'w1:p1',RemoteFrame(1,true,'',observationEpoch:mode == 'old-full' ? epoch - 1 : epoch));
      if (mode != 'full-only') {
        frames(1,'w1:p1',RemoteFrame(2,false,'',observationEpoch:mode == 'old-delta' ? epoch - 1 : epoch));
      }
    });
    return true;
  }
  @override Future<void> cancel() async {
    cancellations++;
    if (!ended.isCompleted) ended.completeError(RemoteFailure(mode == 'cancel-unconfirmed' ? 'observe_ended' : 'cancelled'));
  }
}

void main() {
  test('five resumes each require a fresh full and a following same-epoch delta', () async {
    final adapter = RecoveryScript('positive'), progress = <String,int>{};
    await runObserverRecovery(adapter,RemoteConfig.fromJson(fixtureConfig()),progress);
    expect(progress,{'resumeCount':5,'freshFullCount':5,'sameEpochDeltaCount':5});
    expect(adapter.resumes,5);
    expect(adapter.cancellations,1);
  });
  for (final (mode,code,resumes,fulls,deltas) in [
    ('old-full','recovery_timeout',1,0,0),
    ('old-delta','recovery_timeout',1,1,0),
    ('full-only','recovery_timeout',1,1,0),
    ('connection-changed','recovery_connection_changed',5,5,5),
    ('pause-failed','recovery_pause_failed',0,0,0),
    ('resume-failed','recovery_resume_failed',0,0,0),
    ('cancel-unconfirmed','recovery_cancel_unconfirmed',5,5,5),
    ('wrong-generation-1','recovery_target_changed',1,0,0),
    ('wrong-pane-3','recovery_target_changed',3,2,2),
    ('wrong-generation-5','recovery_target_changed',5,4,4),
    ('wrong-pane-5','recovery_target_changed',5,4,4),
  ]) {
    test('recovery rejects $mode and still closes its observation', () async {
      final adapter = RecoveryScript(mode), progress = <String,int>{};
      await expectLater(runObserverRecovery(adapter,RemoteConfig.fromJson(fixtureConfig()),progress,
          phaseTimeout:const Duration(milliseconds:50)),
        throwsA(isA<RemoteFailure>().having((failure) => failure.code,'code',code)));
      expect(adapter.cancellations,1);
      expect(progress['resumeCount'] ?? 0,resumes);
      expect(progress['freshFullCount'] ?? 0,fulls);
      expect(progress['sameEpochDeltaCount'] ?? 0,deltas);
    });
  }
}
