import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/remote_input.dart';
import 'remote_input_test.dart' show target,ready;

/// Explicit in-memory backend for the production Dart session/claim tests.
/// This is not native filesystem, durability, SSH or device evidence.
class MemoryTargetInputJournal implements RemoteInputJournal {
  final records = <String,String>{};
  final active = <String,({String raw,String lease})>{};
  final prepareBarriers = <String,Completer<void>>{};
  final completeBarriers = <String,Completer<void>>{};
  int _nextLease = 0;
  bool failComplete = false;
  Completer<void>? readBarrier;
  @override Future<List<String>> readAll() async {
    final snapshot = records.values.toList();
    await readBarrier?.future;
    return snapshot;
  }
  @override Future<String> prepare(String record) async {
    final pending = RemoteInputPending.parse(record),key = RemoteInputPending.parse(record).target.endpointKey;
    if (records.containsKey(key) || active.containsKey(key) || records.length >= 32) throw StateError('input_journal_unavailable');
    final lease = (++_nextLease).toRadixString(16).padLeft(32,'0');
    records[key] = pending.raw; active[key] = (raw:record,lease:lease);
    await prepareBarriers[record]?.future;
    return lease;
  }
  void _owns(String record,String lease) {
    final key = RemoteInputPending.parse(record).target.endpointKey,owner = active[RemoteInputPending.parse(record).target.endpointKey];
    if (owner == null || owner.raw != record || owner.lease != lease || records[key] != record) throw StateError('input_journal_unavailable');
  }
  @override Future<void> complete(String record,String lease) async {
    _owns(record,lease);
    if (failComplete) throw StateError('input_journal_unavailable');
    final key = RemoteInputPending.parse(record).target.endpointKey;
    active.remove(key); records.remove(key);
    await completeBarriers[record]?.future;
  }
  @override Future<void> abandon(String record,String lease) async {
    _owns(record,lease); active.remove(RemoteInputPending.parse(record).target.endpointKey);
  }
  @override Future<void> resolve(String record) async {
    final key = RemoteInputPending.parse(record).target.endpointKey;
    if (active.containsKey(key) || records[key] != record) throw StateError('input_journal_unavailable');
    records.remove(key);
  }
}

void main() {
  test('shared IJ limits and legacy raw fixture agree with the Dart parser', () {
    final fixture = jsonDecode(File('assets/shared/target-input-journal-v1.json').readAsStringSync()) as Map<String,dynamic>;
    expect(fixture['limits'],{'maxTargets':32,'maxRecordUtf8Bytes':8192,'maxStoreUtf8Bytes':262144,'maxActivePerTarget':1});
    final bridge = fixture['flutterBridge'] as Map<String,dynamic>;
    final originals = ((bridge['envelope'] as Map)['records'] as List).cast<String>();
    final parsed = parseRemoteInputJournalRecords(originals);
    expect(parsed.map((record) => record.raw),originals);
    expect(parsed.map((record) => record.target.route),['system','system']);
  });
  test('IJ01 A unknown does not block B and B completion leaves A byte exact', () async {
    final journal = MemoryTargetInputJournal(),a = target(),b = target(pane:'w1:p2',term:'term_1234');
    final left = RemoteInputJournalSession(journal),right = RemoteInputJournalSession(journal);
    await left.refresh(); await right.refresh();
    final original = RemoteInputPending.create('a'*32,a),other = RemoteInputPending.create('b'*32,b);
    final first = left.prepare(original); await first.prepared; await left.retire(first);
    await right.refresh(); expect(right.ready,isTrue); expect(right.pendingFor(b),isNull);
    expect(right.pendingFor(a)!.raw,original.raw);
    final second = right.prepare(other); await second.prepared; await right.complete(second); await right.retire(second);
    expect(await journal.readAll(),[original.raw]); expect(journal.active,isEmpty);
    expect(right.pendingFor(b),isNull); expect(right.pendingFor(a)!.raw,original.raw);
  });
  test('IJ02 IJ04 two adapter sessions cannot prepare or resolve an active same endpoint', () async {
    final journal = MemoryTargetInputJournal();
    final a = RemoteInputJournalSession(journal),b = RemoteInputJournalSession(journal);
    await a.refresh(); await b.refresh();
    final old = RemoteInputPending.create('a'*32,target()),newer = RemoteInputPending.create('b'*32,target(generation:2));
    final first = a.prepare(old); final lease = await first.prepared;
    final conflicting = b.prepare(newer);
    await expectLater(conflicting.prepared,throwsStateError); await b.retire(conflicting);
    expect(b.ready,isTrue); expect(b.pendingFor(newer.target)!.raw,old.raw);
    await expectLater(b.resolve(old.raw),throwsStateError);
    expect(journal.active[old.target.endpointKey]!.lease,lease); expect(await journal.readAll(),[old.raw]);
    await a.complete(first); await a.retire(first);
    await b.refresh(); final second = b.prepare(newer); final nextLease = await second.prepared;
    await expectLater(journal.abandon(old.raw,lease),throwsStateError);
    await expectLater(journal.complete(old.raw,lease),throwsStateError);
    await expectLater(journal.resolve(old.raw),throwsStateError);
    expect(journal.active[newer.target.endpointKey]!.lease,nextLease);
    expect(await journal.readAll(),[newer.raw]); await b.retire(second);
  });
  test('IJ09 timed-out prepare retains original ownership until settlement; B remains independent', () async {
    final journal = MemoryTargetInputJournal();
    final a = RemoteInputJournalSession(journal),b = RemoteInputJournalSession(journal);
    await a.refresh(); await b.refresh();
    final original = RemoteInputPending.create('c'*32,target()),other = RemoteInputPending.create('d'*32,target(term:'term_1234'));
    final barrier = Completer<void>(); journal.prepareBarriers[original.raw] = barrier;
    final claim = a.prepare(original);
    await expectLater(claim.prepared.timeout(const Duration(milliseconds:1)),throwsA(isA<TimeoutException>()));
    var retired = false; final cleanup = a.retire(claim).then((_) { retired = true; });
    await Future<void>.delayed(Duration.zero); expect(retired,isFalse);
    expect(journal.active.containsKey(original.target.endpointKey),isTrue);
    await expectLater(journal.resolve(original.raw),throwsStateError);
    await b.refresh(); final independent = b.prepare(other); await independent.prepared;
    await b.complete(independent); await b.retire(independent);
    expect(await journal.readAll(),[original.raw]);
    barrier.complete(); await cleanup;
    expect(journal.active,isEmpty); expect(await journal.readAll(),[original.raw]);
    expect(a.pendingFor(original.target)!.raw,original.raw); // Never complete/delete on timeout.
  });
  test('IJ03 delayed known completion cannot abandon a newer same-target lease', () async {
    final journal = MemoryTargetInputJournal(),a = RemoteInputJournalSession(journal),b = RemoteInputJournalSession(journal);
    await a.refresh(); await b.refresh();
    final old = RemoteInputPending.create('e'*32,target()),newer = RemoteInputPending.create('f'*32,target(generation:2));
    final first = a.prepare(old); await first.prepared;
    final barrier = Completer<void>(); journal.completeBarriers[old.raw] = barrier;
    final completion = a.complete(first); await Future<void>.delayed(Duration.zero);
    final cleanup = a.retire(first);
    await b.refresh(); final second = b.prepare(newer); final lease = await second.prepared;
    barrier.complete(); await completion; await cleanup;
    expect(journal.active[newer.target.endpointKey]!.lease,lease); expect(await journal.readAll(),[newer.raw]);
    await b.retire(second);
  });
  test('IJ10 known receipt cleanup failure locks only A in a readable table', () async {
    final journal = MemoryTargetInputJournal(),a = RemoteInputJournalSession(journal),b = RemoteInputJournalSession(journal);
    await a.refresh(); await b.refresh();
    final old = RemoteInputPending.create('1'*32,target()),other = RemoteInputPending.create('2'*32,target(term:'term_1234'));
    final first = a.prepare(old); await first.prepared; journal.failComplete = true;
    await expectLater(a.complete(first),throwsStateError); await a.retire(first);
    expect(a.ready,isTrue); expect(a.pendingFor(old.target)!.raw,old.raw); expect(journal.active,isEmpty);
    journal.failComplete = false; await b.refresh(); final second = b.prepare(other); await second.prepared;
    await b.complete(second); await b.retire(second); expect(await journal.readAll(),[old.raw]);
  });
  test('IJ03 reviewed old raw cannot resolve a replacement request after refresh', () async {
    final journal = MemoryTargetInputJournal(),session = RemoteInputJournalSession(journal);
    await session.refresh(); final old = RemoteInputPending.create('3'*32,target());
    final claim = session.prepare(old); await claim.prepared; await session.retire(claim);
    final reviewed = session.pendingFor(old.target)!.raw;
    await journal.resolve(old.raw);
    final newer = RemoteInputPending.create('4'*32,target(generation:2));
    final lease = await journal.prepare(newer.raw); await journal.abandon(newer.raw,lease);
    await expectLater(session.resolve(reviewed),throwsStateError);
    await session.refresh(); expect(session.pendingFor(old.target)!.raw,newer.raw); expect(await journal.readAll(),[newer.raw]);
  });
  test('IJ07 corrupt or duplicate endpoint records fail globally; valid unrelated records remain independent', () async {
    final a = RemoteInputPending.create('5'*32,target()),b = RemoteInputPending.create('6'*32,target(term:'term_1234'));
    expect(parseRemoteInputJournalRecords([a.raw,b.raw]).length,2);
    expect(() => parseRemoteInputJournalRecords([a.raw,RemoteInputPending.create('7'*32,target(generation:9)).raw]),throwsFormatException);
    expect(() => parseRemoteInputJournalRecords([a.raw,'{}']),throwsFormatException);
    final journal = MemoryTargetInputJournal()..records['fixture'] = '{}';
    final session = RemoteInputJournalSession(journal);
    await expectLater(session.refresh(),throwsFormatException); expect(session.ready,isFalse);
    expect(() => session.prepare(a),throwsFormatException);
  });
  test('another adapter resolves A; its next authoritative full can coordinate only the exact old UI lock', () async {
    final journal = MemoryTargetInputJournal(),a = RemoteInputJournalSession(journal),b = RemoteInputJournalSession(journal);
    await a.refresh(); await b.refresh();
    final pending = RemoteInputPending.create('8'*32,target());
    final claim = a.prepare(pending); await claim.prepared; await a.retire(claim);
    var writes = 0;
    final gate = RemoteInputGate((t,bytes,current) async { writes++; return const RemoteInputResult.unknown().withPending(pending); });
    ready(gate,pending.target); await gate.submit(gate.capture()!,'one attempt');
    final frozen = gate.captureJournalRefresh(pending.target)!;
    await b.refresh(); await b.resolve(pending.raw);
    final read = await a.refresh();
    expect(a.isCurrentRead(read),isTrue); expect(a.hasClaimFor(pending.target),isFalse); expect(a.pendingFor(pending.target),isNull);
    expect(gate.reconcileJournalRefresh(frozen),isTrue);
    expect(gate.unknown,isNull); expect(gate.canInput,isTrue); expect(gate.mode,RemoteInputMode.observe); expect(writes,1);
  });
  test('empty full read cannot clear a replacement unknown, a changed epoch or a newer read', () async {
    final journal = MemoryTargetInputJournal(),session = RemoteInputJournalSession(journal);
    await session.refresh();
    final original = RemoteInputPending.create('9'*32,target());
    final gate = RemoteInputGate((t,bytes,current) async => const RemoteInputResult.unknown().withPending(original));
    ready(gate,original.target); await gate.submit(gate.capture()!,'old');
    final oldReview = gate.captureJournalRefresh(original.target)!;
    final barrier = Completer<void>(); journal.readBarrier = barrier;
    final oldReadFuture = session.refresh();
    final replacement = RemoteInputPending.create('a'*32,target(generation:2));
    gate.restorePending(replacement);
    journal.readBarrier = null;
    final lease = await journal.prepare(replacement.raw); await journal.abandon(replacement.raw,lease);
    final latest = await session.refresh(); barrier.complete(); final oldRead = await oldReadFuture;
    expect(session.isCurrentRead(oldRead),isFalse); expect(session.isCurrentRead(latest),isTrue);
    expect(gate.reconcileJournalRefresh(oldReview),isFalse); expect(gate.unknown!.pendingRaw,replacement.raw);
    final currentReview = gate.captureJournalRefresh(original.target)!; gate.invalidate();
    expect(gate.reconcileJournalRefresh(currentReview),isFalse); expect(gate.unknown!.pendingRaw,replacement.raw);
  });
  test('known receipt becomes read-only lastResult after exact UI lock coordination', () async {
    final pending = RemoteInputPending.create('b'*32,target());
    final receipt = RemoteInputReceipt(pending.requestId,pending.target.paneId,pending.target.terminalId,4);
    final gate = RemoteInputGate((t,bytes,current) async => RemoteInputResult.journalLocked(
      RemoteInputDisposition.accepted,receipt:receipt).withPending(pending));
    ready(gate,pending.target); await gate.submit(gate.capture()!,'once');
    final review = gate.captureJournalRefresh(pending.target)!;
    expect(gate.reconcileJournalRefresh(review),isTrue);
    expect(gate.unknown,isNull); expect(gate.lastResult!.receipt,receipt);
    expect(gate.lastResult!.disposition,RemoteInputDisposition.accepted); expect(gate.mode,RemoteInputMode.observe);
    ready(gate,target(term:'term_1234')); expect(gate.lastResult,isNull); expect(gate.unknown,isNull);
  });
  test('IJ08 rejects a 33rd target without silently evicting records', () {
    final records = [for (var i = 0; i < 32; i++) RemoteInputPending.create(i.toRadixString(16).padLeft(32,'0'),target(pane:'w1:p$i')).raw];
    expect(parseRemoteInputJournalRecords(records).length,32);
    expect(() => parseRemoteInputJournalRecords([...records,RemoteInputPending.create('f'*32,target(pane:'w1:p33')).raw]),throwsFormatException);
    expect(records.length,32);
  });
}
