import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/connection_diagnostics.dart';

void main() {
  test('local route choice alone does not prove network or host',() {
    final d=ConnectionDiagnostics()..localRouteReady()..progress('connecting');
    expect(d.localNetworkReady,isTrue); expect(d.network,ConnectionStepState.active);
    expect(d.hostKey,ConnectionStepState.waiting); expect(d.authentication,ConnectionStepState.waiting);
  });
  test('host mismatch stops before authentication without claiming a public-key rejection',() {
    final d=ConnectionDiagnostics()..localRouteReady()..fail('host_key_mismatch',hostChecked:true);
    expect(d.network,ConnectionStepState.passed); expect(d.hostKey,ConnectionStepState.failed);
    expect(d.authentication,ConnectionStepState.waiting); expect(d.guidance,contains('可信渠道'));
  });
  test('auth failure requires observed matched key and actual authentication start',() {
    final confirmed=ConnectionDiagnostics()..fail('authentication_failed',hostChecked:true,hostMatched:true,authStarted:true);
    expect(confirmed.hostKey,ConnectionStepState.passed); expect(confirmed.authentication,ConnectionStepState.failed);
    final ambiguous=ConnectionDiagnostics()..fail('authentication_failed');
    expect(ambiguous.authentication,ConnectionStepState.waiting); expect(ambiguous.network,ConnectionStepState.unknown);
  });
  test('snapshot event proves key and authentication; empty board still requires target and full',() {
    final d=ConnectionDiagnostics()..progress('snapshot')..progress('snapshot_received');
    expect(d.network,ConnectionStepState.passed); expect(d.hostKey,ConnectionStepState.passed);
    expect(d.authentication,ConnectionStepState.passed); expect(d.dashboard,ConnectionStepState.passed);
    expect(d.firstFrame,ConnectionStepState.waiting);
    d.progress('full_received'); expect(d.firstFrame,ConnectionStepState.waiting);
    d.progress('observing'); d.frameAccepted(); expect(d.firstFrame,ConnectionStepState.active);
    d.targetSelected('w1:p1','term_abcd'); d.frameAccepted(); expect(d.firstFrame,ConnectionStepState.passed);
  });
  test('timeout, cancellation and next attempt do not invent success or carry old state',() {
    final d=ConnectionDiagnostics()..progress('snapshot')..fail('timeout');
    expect(d.authentication,ConnectionStepState.passed); expect(d.dashboard,ConnectionStepState.unknown);
    expect(d.firstFrame,ConnectionStepState.waiting);
    final next=ConnectionDiagnostics(); expect(next.hostKey,ConnectionStepState.waiting);
    next.stopped(); expect(next.network,ConnectionStepState.unknown); expect(next.guidance,contains('不会自动重试'));
  });
  test('known failure marks only the phase that had started',() {
    final d=ConnectionDiagnostics()..progress('snapshot')..fail('snapshot_rejected');
    expect(d.dashboard,ConnectionStepState.failed); expect(d.firstFrame,ConnectionStepState.waiting);
    final other=ConnectionDiagnostics()..fail('snapshot_rejected');
    expect(other.dashboard,ConnectionStepState.waiting);
  });
}
