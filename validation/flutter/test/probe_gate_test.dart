import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/probe_gate.dart';

ProbeGate ready() {
  final g = ProbeGate('host-a/session-1/pane-a');
  g.select(true);
  g.enqueue(Frame(g.ticket, 'full', full: true));
  g.consume();
  g.setMode(InputMode.direct);
  return g;
}

void main() {
  test('observation and stale focus cannot send; IME target lease is invalidated', () {
    final g = ready(), old = ready();
    final ticket = g.ticket;
    g.select(false);
    g.select(true);
    g.setMode(InputMode.direct);
    expect(g.send(ticket, '中文', InputMode.direct), isFalse);
    expect(g.send(old.ticket, 'wrong target', InputMode.observe), isFalse);
    expect(g.send(g.ticket, '中文', InputMode.direct), isTrue);
    expect(g.inputHex.single, 'e4b8ade69687');
  });
  test('hidden restoration requires a new full and rejects old epoch', () {
    final g = ready(), old = ready().ticket;
    final stale = g.ticket;
    g.hide(); g.resume();
    expect(g.enqueue(Frame(stale, 'late')), isFalse);
    expect(g.enqueue(Frame(old, 'late full', full: true)), isFalse);
    expect(g.enqueue(Frame(g.ticket, 'delta')), isFalse);
    expect(g.fresh, isFalse);
    expect(g.enqueue(Frame(g.ticket, 'fresh full', full: true)), isTrue);
    g.consume();
    expect(g.fresh, isTrue);
    expect(g.mode, InputMode.observe);
  });
  test('overflow fails closed with a bounded queue, then requires full', () {
    final g = ready();
    for (var i = 0; i < 16; i++) { expect(g.enqueue(Frame(g.ticket, 'x' * 4096)), isTrue); }
    expect(g.queuedBytes, 65536);
    expect(g.enqueue(Frame(g.ticket, 'x')), isFalse);
    expect(g.queuedBytes, 0);
    expect(g.peakQueuedBytes, 65536);
    expect(g.fresh, isFalse);
  });
  test('unknown input is retained only as evidence and never replayed', () {
    final g = ready();
    g.send(g.ticket, 'danger', InputMode.direct);
    g.markUnknown(); g.resume();
    g.enqueue(Frame(g.ticket, 'full', full: true)); g.consume();
    g.setMode(InputMode.direct);
    expect(g.send(g.ticket, 'next', InputMode.direct), isFalse);
    expect(g.inputCount, 1);
    expect(g.unknownHex, ['64616e676572']);
    g.acknowledgeUnknown();
    expect(g.inputCount, 1);
  });
  test('draft sends exact bytes without extra Enter and is bounded', () {
    final g = ready(); g.setMode(InputMode.draft);
    expect(g.send(g.ticket, 'echo example', InputMode.draft), isTrue);
    expect(g.inputHex.single.endsWith('0d'), isFalse);
    expect(g.send(g.ticket, 'x' * 4097, InputMode.draft), isFalse);
  });
}
