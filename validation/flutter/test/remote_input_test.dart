import 'dart:async';
import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/remote_input.dart';

RemoteInputTarget target({Object? connection,int generation=1,String pane='w1:p1',String term='term_abcd',
  String fingerprint='SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA',String session='probe'}) => RemoteInputTarget(
    connection:connection ?? Object(),generation:generation,host:'fixture.invalid',port:2222,
    username:'fixture',hostFingerprint:fingerprint,session:session,
    socketPath:'/tmp/fixture/herdr/sessions/probe/herdr.sock',paneId:pane,terminalId:term);

void ready(RemoteInputGate gate,RemoteInputTarget value,{RemoteInputMode mode=RemoteInputMode.direct}) {
  gate.bind(value,const RemoteInputCapability(4096)); gate.setFocused(true); gate.setMode(mode);
}

void main() {
  test('only exact side-effect-free atomic capability enables input', () {
    final value = {'type':'pocket_input_capabilities','version':1,'protocol':22,
      'atomic_terminal_guard':true,'raw_bytes':true,'max_input_bytes':4096};
    expect(RemoteInputCapability.parse(value)?.maxBytes,4096);
    for (final invalid in [null,{}, {...value,'atomic_terminal_guard':false},
      {...value,'raw_bytes':false},{...value,'max_input_bytes':65536},
      {...value,'version':2},{...value,'protocol':23}]) {
      expect(RemoteInputCapability.parse(invalid),isNull);
    }
  });
  test('write ACK binds request ID, byte count, pane and stable terminal; unknown errors stay unknown', () {
    final t = target();
    final value = {'id':'request','result':{'type':'pocket_input_accepted','pane_id':t.paneId,
      'terminal_id':t.terminalId,'accepted_bytes':7}};
    final accepted = parseInputResponse(value,'request',t,7);
    expect(accepted.disposition,RemoteInputDisposition.accepted);
    expect(accepted.receipt!.requestId,'request'); expect(accepted.receipt!.acceptedBytes,7);
    expect(accepted.receipt!.paneId,t.paneId); expect(accepted.receipt!.terminalId,t.terminalId);
    for (final invalid in [
      {...value,'id':'late'}, {...value,'ok':false},
      {...value,'result':{...value['result'] as Map,'terminal_id':'term_ffff'}},
      {...value,'result':{...value['result'] as Map,'pane_id':'w1:p2'}},
      {...value,'result':{...value['result'] as Map,'accepted_bytes':8}},
      {...value,'result':{...value['result'] as Map,'accepted_bytes':7.0}},
      {'id':'request','error':{'code':'timeout'}},
      {'id':'request','error':{'code':'pane_send_failed'}},
      {...value,'error':{'code':'pocket_input_rejected'}},
    ]) {
      expect(parseInputResponse(invalid,'request',t,7).disposition,RemoteInputDisposition.unknown);
      expect(parseInputResponse(invalid,'request',t,7).receipt,isNull);
    }
    expect(parseInputResponse({'id':'request','error':{'code':'pocket_input_rejected'}},'request',t,7).disposition,
      RemoteInputDisposition.rejected);
    expect(parseInputResponse({'id':'wrong','error':{'code':'pocket_input_rejected'}},'request',t,7).disposition,
      RemoteInputDisposition.unknown);
  });
  test('observation, missing full/focus, missing capability and stale leases never call writer', () async {
    var calls = 0;
    final gate = RemoteInputGate((t,b,current) async { calls++; return const RemoteInputResult.accepted(); });
    final t = target(); final stale = RemoteInputLease(t,0,RemoteInputMode.direct);
    await gate.submit(stale,'before-full');
    gate.bind(t,null); gate.setFocused(true); gate.setMode(RemoteInputMode.direct);
    await gate.submit(stale,'unsupported'); expect(gate.mode,RemoteInputMode.observe);
    ready(gate,t); final lease = gate.capture()!;
    gate.setMode(RemoteInputMode.draft); await gate.submit(lease,'old-mode');
    final draft = gate.capture()!; gate.setFocused(false); await gate.submit(draft,'old-focus');
    ready(gate,t); final beforeStop = gate.capture()!; gate.invalidate();
    await gate.submit(beforeStop,'after-stop'); expect(calls,0);
  });
  test('raw Unicode, combining characters and keys keep their bytes with no implicit newline', () async {
    final received = <List<int>>[];
    final gate = RemoteInputGate((t,b,current) async {
      expect(current(),isTrue); received.add(b.toList()); return const RemoteInputResult.accepted();
    });
    ready(gate,target());
    for (final text in ['中文 e\u0301','\x1b[A','\x03','\r']) {
      expect((await gate.submit(gate.capture()!,text)).disposition,RemoteInputDisposition.accepted);
    }
    expect(received,[utf8.encode('中文 e\u0301'),[27,91,65],[3],[13]]);
  });
  test('live direct events are bounded and ordered; focus loss discards unsent events', () async {
    final replies = <Completer<RemoteInputResult>>[]; final received = <String>[];
    final guards = <bool Function()>[];
    final gate = RemoteInputGate((t,b,current) {
      received.add(utf8.decode(b)); guards.add(current);
      final reply = Completer<RemoteInputResult>(); replies.add(reply); return reply.future;
    });
    ready(gate,target()); final lease = gate.capture()!;
    final a = gate.submit(lease,'a'), b = gate.submit(lease,'b'), c = gate.submit(lease,'c');
    expect(received,['a']);
    replies.first.complete(const RemoteInputResult.accepted()); await a;
    await Future<void>.delayed(Duration.zero); expect(received,['a','b']);
    gate.setFocused(false); expect(guards.last(),isFalse);
    expect((await c).code,'input_cancelled_before_write');
    replies.last.complete(const RemoteInputResult.accepted()); await b;
    expect(received,['a','b']); expect(gate.mode,RemoteInputMode.observe);
  });
  test('draft double-submit is rejected and a definitive server rejection keeps the lock clear', () async {
    final reply = Completer<RemoteInputResult>(); var calls = 0;
    final gate = RemoteInputGate((t,b,current) { calls++; return reply.future; });
    ready(gate,target(),mode:RemoteInputMode.draft); final lease = gate.capture()!;
    final first = gate.submit(lease,'draft\ntext');
    expect((await gate.submit(lease,'draft\ntext')).disposition,RemoteInputDisposition.rejected);
    expect(calls,1); reply.complete(const RemoteInputResult.rejected('pocket_input_rejected'));
    await first; expect(gate.unknown,isNull); expect(gate.canInput,isTrue);
  });
  test('lost result drops queued input, survives invalidation, and needs new full of same endpoint plus manual acknowledgement', () async {
    final reply = Completer<RemoteInputResult>(); var calls = 0;
    final gate = RemoteInputGate((t,b,current) { calls++; return reply.future; });
    final firstTarget = target(); ready(gate,firstTarget); final lease = gate.capture()!;
    final first = gate.submit(lease,'sent-once'), queued = gate.submit(lease,'never-write');
    reply.complete(const RemoteInputResult.unknown()); await first;
    expect((await queued).code,'input_cancelled_before_write'); expect(calls,1);
    expect(gate.unknown!.text,'sent-once'); expect(gate.canInput,isFalse);
    expect(gate.acknowledgeUnknown(),isFalse);
    gate.invalidate(); gate.bind(firstTarget,const RemoteInputCapability(4096));
    expect(gate.acknowledgeUnknown(),isFalse); // Same SSH attempt cannot resolve it.
    gate.bind(target(generation:2,term:'term_ffff'),const RemoteInputCapability(4096));
    expect(gate.acknowledgeUnknown(),isFalse); // Same pane, replaced terminal.
    gate.bind(target(generation:3,fingerprint:'SHA256:changed'),const RemoteInputCapability(4096));
    expect(gate.acknowledgeUnknown(),isFalse);
    gate.bind(target(generation:4),const RemoteInputCapability(4096));
    expect(gate.canAcknowledgeUnknown,isTrue); expect(gate.canInput,isFalse);
    expect(gate.acknowledgeUnknown(),isTrue); expect(gate.mode,RemoteInputMode.observe);
    expect(calls,1); // Acknowledging/rebinding never replays anything.
  });
  test('IJ01 late A unknown cannot discard B live input or transfer A bytes to B', () async {
    final first = Completer<RemoteInputResult>(),second = Completer<RemoteInputResult>();
    final writes = <String>[];
    final gate = RemoteInputGate((t,b,current) {
      writes.add(t.terminalId); return writes.length == 1 ? first.future : second.future;
    });
    final a = target(),b = target(term:'term_1234');
    ready(gate,a); final sentA = gate.submit(gate.capture()!,'A only');
    ready(gate,b); final sentB = gate.submit(gate.capture()!,'B independent');
    expect(writes,['term_abcd','term_1234']); // B starts while A is still unresolved.
    expect(first.isCompleted,isFalse);
    first.complete(const RemoteInputResult.unknown()); await sentA;
    expect(writes,['term_abcd','term_1234']); expect(gate.unknown,isNull);
    expect(gate.mode,RemoteInputMode.direct);
    second.complete(const RemoteInputResult.accepted()); await sentB;
    expect(gate.canInput,isTrue); expect(gate.lastResult!.disposition,RemoteInputDisposition.accepted);
    ready(gate,target(generation:2));
    expect(gate.unknown!.text,'A only'); expect(gate.canInput,isFalse); expect(writes.length,2);
  });
  test('an old A journal-unavailable result cannot invalidate B mode or its queued bytes', () async {
    final aReply = Completer<RemoteInputResult>(),bReply = Completer<RemoteInputResult>();
    final writes = <String>[];
    final gate = RemoteInputGate((t,b,current) {
      writes.add(utf8.decode(b));
      if (t.terminalId == 'term_abcd') return aReply.future;
      return writes.where((value) => value.startsWith('B')).length == 1 ? bReply.future
        : Future.value(const RemoteInputResult.accepted());
    });
    ready(gate,target()); final sentA = gate.submit(gate.capture()!,'A');
    ready(gate,target(term:'term_1234')); final bLease = gate.capture()!;
    final firstB = gate.submit(bLease,'B1'),secondB = gate.submit(bLease,'B2');
    expect(writes,['A','B1']);
    aReply.complete(const RemoteInputResult.rejected('input_journal_unavailable')); await sentA;
    expect(gate.current(bLease),isTrue); expect(gate.mode,RemoteInputMode.direct); expect(gate.sending,isTrue);
    bReply.complete(const RemoteInputResult.accepted()); await firstB; await secondB;
    expect(writes,['A','B1','B2']); expect(gate.canInput,isTrue);
  });
  test('same-endpoint lanes keep a later observation ordered behind its unsettled writer', () async {
    final reply = Completer<RemoteInputResult>(); var writes = 0;
    final gate = RemoteInputGate((t,b,current) { writes++; return writes == 1 ? reply.future
      : Future.value(const RemoteInputResult.accepted()); });
    ready(gate,target()); final first = gate.submit(gate.capture()!,'old');
    ready(gate,target(generation:2)); final second = gate.submit(gate.capture()!,'new');
    expect(writes,1); reply.complete(const RemoteInputResult.accepted()); await first; await second;
    expect(writes,2); expect(gate.canInput,isTrue);
  });
  test('unsettled independent target lanes are bounded without evicting older ownership', () async {
    final replies = <Completer<RemoteInputResult>>[],sent = <Future<RemoteInputResult>>[];
    final gate = RemoteInputGate((t,bytes,current) {
      final reply = Completer<RemoteInputResult>(); replies.add(reply); return reply.future;
    });
    for (var i = 0; i < 32; i++) {
      ready(gate,target(pane:'w1:p$i',term:'term_${(i+1).toRadixString(16)}'));
      sent.add(gate.submit(gate.capture()!,'one'));
    }
    expect(replies.length,32);
    ready(gate,target(pane:'w1:p33',term:'term_ff'));
    expect((await gate.submit(gate.capture()!,'not-started')).code,'input_buffer_full');
    expect(replies.length,32); expect(replies.every((reply) => !reply.isCompleted),isTrue);
    for (final reply in replies) { reply.complete(const RemoteInputResult.accepted()); }
    await Future.wait(sent); expect(gate.mode,RemoteInputMode.observe);
  });
  test('IJ01 resolving reviewed A never removes B unknown and old records cannot unlock replacements', () async {
    final gate = RemoteInputGate((t,b,current) async => const RemoteInputResult.unknown());
    ready(gate,target()); await gate.submit(gate.capture()!,'A');
    ready(gate,target(term:'term_1234')); await gate.submit(gate.capture()!,'B');
    ready(gate,target(generation:2)); final reviewedA = gate.unknown!;
    expect(gate.acknowledgeUnknown(reviewed:reviewedA),isTrue);
    ready(gate,target(term:'term_1234',generation:2)); expect(gate.unknown!.text,'B');
    final reviewedB = gate.unknown!;
    final replacement = RemoteInputPending.create('9'*32,target(term:'term_1234',generation:3));
    gate.restorePending(replacement);
    expect(gate.acknowledgeUnknown(reviewed:reviewedB),isFalse);
    expect(gate.unknown!.pendingRaw,replacement.raw); expect(gate.canInput,isFalse);
  });
  test('IJ10 known receipt stays attached to the exact pending raw across new full and target switches', () async {
    final a = target(),pending = RemoteInputPending.create('8'*32,target());
    final receipt = RemoteInputReceipt(pending.requestId,a.paneId,a.terminalId,4);
    final gate = RemoteInputGate((t,b,current) async => RemoteInputResult.journalLocked(
      RemoteInputDisposition.accepted,receipt:receipt).withPending(pending));
    ready(gate,a); await gate.submit(gate.capture()!,'once');
    final original = gate.unknown!;
    ready(gate,target(term:'term_1234')); expect(gate.unknown,isNull); expect(gate.canInput,isTrue);
    gate.bind(target(generation:2),const RemoteInputCapability(4096)); gate.restorePending(pending);
    expect(identical(gate.unknown,original),isTrue); expect(gate.unknown!.receipt,receipt);
    expect(gate.unknown!.knownDisposition,RemoteInputDisposition.accepted);
    expect(gate.unknown!.pendingRaw,pending.raw); expect(gate.lastResult,isNull);
  });
  test('MT08 MT09 hide revokes queued bytes and preserves the submitted unknown on its original target', () async {
    final reply = Completer<RemoteInputResult>(); var calls = 0;
    final gate = RemoteInputGate((t,b,current) { calls++; return reply.future; });
    final original = target(); ready(gate,original);
    final lease = gate.capture()!;
    final sent = gate.submit(lease,'once'),queued = gate.submit(lease,'unsent');
    gate.invalidate();
    expect((await queued).code,'input_cancelled_before_write');
    reply.complete(const RemoteInputResult.unknown()); await sent;
    expect(calls,1); expect(gate.unknown!.target,original); expect(gate.unknown!.text,'once');
    gate.bind(original,const RemoteInputCapability(4096));
    expect(gate.canAcknowledgeUnknown,isFalse); expect(gate.canInput,isFalse);
  });
  test('MT10 old known rejection cannot overwrite new observation lease result or mode', () async {
    final reply = Completer<RemoteInputResult>(),connection = Object();
    final gate = RemoteInputGate((t,b,current) => reply.future);
    final oldTarget = target(connection:connection); ready(gate,oldTarget,mode:RemoteInputMode.draft);
    final oldResult = gate.submit(gate.capture()!,'old');
    gate.invalidate();
    final resumedTarget = target(connection:connection); ready(gate,resumedTarget,mode:RemoteInputMode.draft);
    final resumedLease = gate.capture()!;
    reply.complete(const RemoteInputResult.rejected('pocket_input_rejected')); await oldResult;
    expect(gate.lastResult,isNull); expect(gate.current(resumedLease),isTrue);
    expect(gate.mode,RemoteInputMode.draft); expect(gate.unknown,isNull);
  });
  test('journal records only public identity and attempt ID; malformed/noncanonical/extra fields fail closed', () {
    final t = target(); final pending = RemoteInputPending.create('a'*32,t);
    final data = jsonDecode(pending.raw) as Map<String,dynamic>;
    expect(data.keys.toSet(),RemoteInputPending.fields);
    expect(data.containsKey('text'),isFalse); expect(data.containsKey('bytes_base64'),isFalse);
    final restored = RemoteInputPending.parse(pending.raw);
    expect(restored.raw,pending.raw); expect(restored.target.sameEndpoint(t),isTrue);
    expect(restored.requestId,'a'*32);
    for (final invalid in [
      jsonEncode({...data,'text':'must-not-store'}),jsonEncode({...data,'requestId':'bad'}),
      jsonEncode({...data,'terminalId':'pane-alias'}),jsonEncode({...data,'session':'default'}),
      jsonEncode({...data,'host':'host\nsecret'}),jsonEncode({...data,'generation':0}),
      jsonEncode({...data,'schemaVersion':true}),jsonEncode({...data,'schemaVersion':1.0}),jsonEncode({...data,'schemaVersion':1.5}),
      jsonEncode({...data,'hostFingerprint':'SHA256:short'}),jsonEncode({...data,'socketPath':'/tmp/../other'}),
      '{"schemaVersion":1,${pending.raw.substring(1)}', ' ${pending.raw}',
    ]) { expect(() => RemoteInputPending.parse(invalid),throwsFormatException); }
  });
  test('crash residual restores a byte-free unknown lock and never invokes writer', () {
    var calls = 0;
    final gate = RemoteInputGate((t,b,current) async { calls++; return const RemoteInputResult.accepted(); });
    final pending = RemoteInputPending.parse(RemoteInputPending.create('b'*32,target()).raw);
    gate.restorePending(pending); ready(gate,target(generation:2));
    expect(gate.unknown!.bytes,isEmpty); expect(gate.unknown!.requestId,'b'*32);
    expect(gate.canInput,isFalse); expect(gate.canAcknowledgeUnknown,isTrue);
    expect(calls,0);
  });
  test('durable route is actual overlay identity and legacy markers mean system', () {
    const route = 'easy-tier:0123456789abcdef0123456789abcdef:3:a0000000-0000-4000-8000-000000000001';
    final base = target();
    final overlay = RemoteInputTarget(connection:Object(),generation:base.generation,host:base.host,port:base.port,
      username:base.username,hostFingerprint:base.hostFingerprint,session:base.session,socketPath:base.socketPath,
      paneId:base.paneId,terminalId:base.terminalId,route:route);
    final marker = RemoteInputPending.create('a'*32,overlay);
    final parsed = RemoteInputPending.parse(marker.raw);
    expect(parsed.target.route,route); expect(parsed.target.sameEndpoint(overlay),isTrue);
    expect(parsed.target.sameEndpoint(base),isFalse);
    final data = jsonDecode(marker.raw) as Map<String,dynamic>;
    for (final invalid in ['easy-tier:0123456789abcdef0123456789abcdef:03:a0000000-0000-4000-8000-000000000001',
      'easy-tier:0123456789abcdef0123456789abcdef:2147483648:a0000000-0000-4000-8000-000000000001',
      'tailscale:0123456789abcdef0123456789abcdef:3:a0000000-0000-4000-8000-000000000001']) {
      expect(() => RemoteInputPending.parse(jsonEncode({...data,'route':invalid})),throwsFormatException);
    }
    final old = RemoteInputPending.create('b'*32,base);
    expect(RemoteInputPending.parse(old.raw).target.route,'system');
    final nullRoute = jsonEncode({...jsonDecode(old.raw) as Map<String,dynamic>,'schemaVersion':2,'route':null});
    expect(RemoteInputPending.parse(nullRoute).target.route,'system');
    expect(() => parseRemoteInputJournalRecords([old.raw,nullRoute]),throwsFormatException);
  });
  test('a known result cannot hide a newly discovered same-target pending marker', () async {
    final pending = RemoteInputPending.create('a'*32,target(generation:2));
    final gate = RemoteInputGate((t,b,current) async => const RemoteInputResult.accepted().withPending(pending));
    ready(gate,target()); final result = await gate.submit(gate.capture()!,'known old input');
    expect(result.disposition,RemoteInputDisposition.accepted);
    expect(gate.unknown!.pendingRaw,pending.raw); expect(gate.unknown!.bytes,isEmpty);
    expect(gate.unknown!.knownDisposition,isNull); expect(gate.canInput,isFalse);
  });
  test('writer exceptions are unknown and journal-unavailable pre-write rejection disables input', () async {
    final gate = RemoteInputGate((t,b,current) async { throw StateError('synthetic'); });
    ready(gate,target()); await gate.submit(gate.capture()!,'once'); expect(gate.unknown,isNotNull);
    final noJournal = RemoteInputGate((t,b,current) async => const RemoteInputResult.rejected('input_journal_unavailable'));
    ready(noJournal,target()); await noJournal.submit(noJournal.capture()!,'not-written');
    expect(noJournal.unknown,isNull); expect(noJournal.fresh,isFalse); expect(noJournal.mode,RemoteInputMode.observe);
  });
  test('buffer overflow discards unsent events without an unbounded queue or any replay', () async {
    final reply = Completer<RemoteInputResult>(); var calls = 0;
    final gate = RemoteInputGate((t,b,current) { calls++; return reply.future; });
    ready(gate,target()); final lease = gate.capture()!;
    final first = gate.submit(lease,'first');
    final queued = [for (var i=0;i<64;i++) gate.submit(lease,'x')];
    expect((await gate.submit(lease,'overflow')).code,'input_buffer_full');
    for (final q in queued) { expect((await q).code,'input_cancelled_before_write'); }
    reply.complete(const RemoteInputResult.accepted()); await first;
    expect(calls,1); expect(gate.mode,RemoteInputMode.observe);
  });
  test('writer receives a guard invalidated by mode switch during channel opening', () async {
    final opened = Completer<void>(); var remoteWrites = 0;
    final gate = RemoteInputGate((t,b,current) async {
      await opened.future;
      if (!current()) return const RemoteInputResult.rejected('input_cancelled_before_write');
      remoteWrites++; return const RemoteInputResult.accepted();
    });
    ready(gate,target()); final pending = gate.submit(gate.capture()!,'late');
    gate.setMode(RemoteInputMode.observe); opened.complete();
    expect((await pending).disposition,RemoteInputDisposition.rejected); expect(remoteWrites,0);
  });
  test('a later full cannot resurrect a revoked capability on the same connection', () async {
    var calls = 0;
    final gate = RemoteInputGate((t,b,current) async { calls++; return const RemoteInputResult.accepted(); });
    final t = target(); ready(gate,t); final old = gate.capture()!;
    gate.bind(t,null);
    expect(gate.canInput,isFalse);
    expect((await gate.submit(old,'not-written')).disposition,RemoteInputDisposition.rejected);
    expect(calls,0);
  });
  test('a failed marker clear locks further input without erasing a matching remote ACK or rejection', () async {
    for (final disposition in [RemoteInputDisposition.accepted,RemoteInputDisposition.rejected]) {
      var calls = 0;
      final gate = RemoteInputGate((t,b,current) async {
        calls++; return RemoteInputResult.journalLocked(disposition);
      });
      ready(gate,target());
      final result = await gate.submit(gate.capture()!,'once');
      expect(result.disposition,disposition); expect(result.requiresJournalRecovery,isTrue);
      expect(gate.unknown!.knownDisposition,disposition); expect(gate.canInput,isFalse);
      gate.invalidate(); expect(gate.unknown!.knownDisposition,disposition); expect(calls,1);
    }
  });
}
