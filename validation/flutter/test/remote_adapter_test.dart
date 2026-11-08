import 'dart:async';
import 'dart:convert';
import 'dart:io' show File;
import 'dart:typed_data';
import 'package:dartssh2/dartssh2.dart';
// The pinned library exposes SSHSession.channel with this internal type.
// ignore: implementation_imports
import 'package:dartssh2/src/ssh_channel.dart' show SSHChannel;
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/network_runtime.dart' show RoutedSSHSocket;
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'package:herdr_flutter_probe/remote_page.dart';
import 'remote_test_data.dart';


Matcher failure(String code) => isA<RemoteFailure>().having((e) => e.code,'code',code);

class FakeSocket implements SSHSocket {
  bool destroyed = false;
  final input = StreamController<Uint8List>();
  final output = StreamController<List<int>>();
  @override Stream<Uint8List> get stream => input.stream;
  @override StreamSink<List<int>> get sink => output.sink;
  @override Future<void> get done => input.done;
  @override Future<void> flush() async {}
  @override Future<void> close() async { destroy(); }
  @override void destroy() { destroyed = true; input.close(); output.close(); }
}
class FakeRoutedSocket extends FakeSocket implements RoutedSSHSocket {
  FakeRoutedSocket(this.actualRoute);
  @override final String actualRoute;
}
class TraceObject {
  @override String toString() => throw StateError('must not stringify');
}
class FailedDestroySocket extends FakeSocket {
  @override void destroy() { throw StateError('synthetic close failed'); }
}
class DelayedCloseSocket extends FakeSocket {
  final closing = Completer<void>();
  bool closeCalled = false;
  @override Future<void> close() { closeCalled = true; return closing.future; }
}
class FakeObserverChannel implements SSHChannel {
  FakeObserverChannel(this.calls);
  final List<String> calls;
  @override void destroy() { calls.add('destroy'); }
  @override dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}
class FakeObserverSession implements SSHSession {
  FakeObserverSession(this.calls,{this.rejectSignal=false}) : channel = FakeObserverChannel(calls);
  final List<String> calls;
  final bool rejectSignal;
  @override final SSHChannel channel;
  @override void kill(SSHSignal signal) { calls.add(signal.name); if (rejectSignal) throw StateError('signal unavailable'); }
  @override dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  test('observer termination requests TERM before destroy only once, even if unsupported', () {
    for (final reject in [false,true]) {
      final calls=<String>[],session=FakeObserverSession(calls,rejectSignal:reject),stopper=ObserverSessionTerminator();
      stopper.stop(session); stopper.stop(session);
      expect(calls,['TERM','destroy']);
    }
  });
  test('MT10 fixed-version channel trace waits for exact peer close and rejects forged, stale and wrong IDs', () async {
    var overflow = 0;
    final tracker = ChannelRetirementTracker('fixture',onOverflow:() { overflow++; });
    String opened(int id) => '<- fixture: SSH_Message_Channel_Confirmation(recipientChannel: $id, senderChannel: 7, initialWindowSize: 2097152, maximumPacketSize: 32768)';
    String closed(int id) => '<- fixture: SSH_Message_Channel_Close(recipientChannel: $id)';
    tracker.startOpen(); tracker.trace(opened(1)); tracker.finishOpen(succeeded:true);
    tracker.trace(null); tracker.trace(7); tracker.trace(TraceObject());
    final initial = tracker.waitIdle(); var retired = false; unawaited(initial.then((_) { retired = true; }));
    for (final fake in [
      'banner <- fixture: SSH_Message_Channel_Close(recipientChannel: 1)',
      '<- fixture: SSH_Message_Channel_Data(recipientChannel: 1, data=SSH_Message_Channel_Close(recipientChannel: 1))',
      '-> fixture: SSH_Message_Channel_Close(recipientChannel: 1)',
      '<- fixture: SSH_Message_Channel_Close(recipientChannel: 1, extra: 0)',closed(2),
    ]) { tracker.trace(fake); }
    await Future<void>.delayed(Duration.zero); expect(retired,isFalse); expect(tracker.activeCount,1);
    await expectLater(tracker.waitIdle().timeout(const Duration(milliseconds:1)),throwsA(isA<TimeoutException>()));
    tracker.trace(closed(1)); await initial; expect(retired,isTrue);
    tracker.startOpen(); tracker.trace(opened(3)); tracker.finishOpen(succeeded:true);
    tracker.trace(closed(1)); expect(tracker.activeCount,1); // Late close cannot retire a different ID.
    tracker.trace(closed(3)); await tracker.waitIdle(); expect(overflow,0);
  });
  test('watch subscriptions match shared fixed wire and bind each real pane', () {
    final fixture = jsonDecode(File('assets/shared/session-watch-v1.json').readAsStringSync()) as Map<String,dynamic>;
    final subscriptions = dashboardSubscriptions(const [RemotePane('w1:p1','term_abcd'),RemotePane('w1:p2','term_1234')]);
    final globals = (fixture['globalSubscriptions'] as List).cast<String>();
    expect(subscriptions.take(globals.length).map((entry) => entry['type']),globals);
    expect(subscriptions.skip(globals.length),[
      {'type':'pane.agent_status_changed','pane_id':'w1:p1'},
      {'type':'pane.agent_status_changed','pane_id':'w1:p2'},
    ]);
    expect(subscriptions.every((entry) => entry['type'] != 'pane.agent_status_changed' || entry['pane_id'] != null),isTrue);
  });
  test('watch ACK binds request ID and only global unsupported errors allow a one-shot board', () {
    final fixture = jsonDecode(File('assets/shared/session-watch-v1.json').readAsStringSync()) as Map<String,dynamic>;
    final wire = fixture['wire'] as Map<String,dynamic>;
    final ack = Map<String,dynamic>.from(wire['ack'] as Map),id = ack['id'] as String;
    expect(validateDashboardWatchAck(ack,id,initialGlobal:true),DashboardWatchAck.started);
    final rejected = <String,dynamic>{'id':id,'error':{'code':'invalid_request','message':'fixture missing pane'}};
    expect(validateDashboardWatchAck(rejected,id,initialGlobal:false),DashboardWatchAck.retry);
    expect(validateDashboardWatchAck(rejected,id,initialGlobal:true),DashboardWatchAck.unavailable);
    for (final code in ['unknown_method','method_not_found','invalid_method']) {
      for (final global in [true,false]) {
        expect(validateDashboardWatchAck({'id':id,'error':{'code':code,'message':'fixture'}},id,initialGlobal:global),DashboardWatchAck.unavailable);
      }
    }
    expect(validateDashboardWatchAck({'id':id,'error':{'code':'events_lost','message':'fixture'}},id,initialGlobal:true),DashboardWatchAck.retry);
    for (final invalid in <Map<String,dynamic>>[
      {...ack,'id':'different-request'}, {...ack,'error':null}, {...ack,'ok':true},
      {...ack,'result':{'type':'session_snapshot'}},
      {'id':id,'error':{'code':'invalid_request'}}, {...rejected,'result':{'type':'subscription_started'}},
    ]) {
      expect(() => validateDashboardWatchAck(invalid,id,initialGlobal:true),throwsA(failure('invalid_response')));
    }
  });
  test('watch push accepts fixed fixture envelopes and rejects foreign pane filters or forged RPC errors', () {
    final fixture = jsonDecode(File('assets/shared/session-watch-v1.json').readAsStringSync()) as Map<String,dynamic>;
    final wire = fixture['wire'] as Map<String,dynamic>;
    final id = (wire['ack'] as Map)['id'] as String;
    for (final key in ['created','closed','exited','status']) {
      validateDashboardWatchEvent(Map<String,dynamic>.from(wire[key] as Map),id,{'w1:p1'});
    }
    final status = Map<String,dynamic>.from(wire['status'] as Map);
    final created = Map<String,dynamic>.from(wire['created'] as Map);
    for (final invalid in <Map<String,dynamic>>[
      {...status,'event':'pane_agent_status_changed'}, {...status,'id':id},
      {...status,'data':{...(status['data'] as Map),'pane_id':'w1:p999'}},
      {...status,'data':{...(status['data'] as Map),'agent_status':'invented'}},
      {...created,'event':'pane.created'}, {...created,'data':{'type':'pane_closed'}},
      {'event':'arbitrary-string','data':{}}, {'event':'pane_closed'},
    ]) {
      expect(() => validateDashboardWatchEvent(invalid,id,{'w1:p1'}),throwsA(failure('invalid_response')));
    }
    expect(() => validateDashboardWatchEvent(status,id,{}),throwsA(failure('invalid_response')));
    final lost = Map<String,dynamic>.from(wire['lost'] as Map);
    expect(() => validateDashboardWatchEvent(lost,id,{'w1:p1'}),throwsA(failure('watch_disconnected')));
    expect(() => validateDashboardWatchEvent({...lost,'id':'other-subscription'},id,{'w1:p1'}),throwsA(failure('invalid_response')));
  });
  test('a matching pane in a starting, stale or refreshing dashboard cannot authorize selection', () {
    const pane = RemotePane('w1:p1','term_abcd');
    const initial = RemoteDashboard(1,'probe',[pane]);
    expect(initial.freshness,DashboardFreshness.stale); expect(initial.selectable,isFalse);
    for (final state in DashboardFreshness.values) {
      final board = RemoteDashboard(1,'probe',const [pane],freshness:state);
      if (state == DashboardFreshness.fresh || state == DashboardFreshness.unavailable) {
        requireSelectableDashboardTarget(pane,board);
      } else {
        expect(() => requireSelectableDashboardTarget(pane,board),throwsA(failure('stale_selection')));
      }
    }
    expect(() => requireSelectableDashboardTarget(pane,const RemoteDashboard(1,'probe',
      [RemotePane('w1:p1','term_1234')],freshness:DashboardFreshness.fresh)),throwsA(failure('resume_target_changed')));
  });
  test('concurrent waiters all receive failure and removing an old waiter preserves newer waits', () {
    final all = RemoteWaitGroup(),watch = RemoteWaitGroup(),observation = RemoteWaitGroup();
    final interrupted = <String>[];
    void first(RemoteFailure failure) { interrupted.add('snapshot:${failure.code}'); }
    void second(RemoteFailure failure) { interrupted.add('event:${failure.code}'); }
    void frame(RemoteFailure failure) { interrupted.add('frame:${failure.code}'); }
    all.add(first); all.add(second); all.add(frame); watch.add(first); watch.add(second); observation.add(frame);
    watch.remove(first); all.remove(first); // The older read settled first.
    watch.interrupt(const RemoteFailure('observation_paused'));
    expect(interrupted,['event:observation_paused']);
    interrupted.clear(); all.interrupt(const RemoteFailure('synthetic_failure'));
    expect(interrupted,['event:synthetic_failure','frame:synthetic_failure']);
    interrupted.clear(); watch.remove(second); all.remove(second);
    observation.interrupt(const RemoteFailure('observation_paused'));
    expect(interrupted,['frame:observation_paused']);
  });
  test('watch invalidations coalesce a storm and a lost stream cannot freshen an in-flight snapshot', () {
    final pending = DashboardInvalidations();
    final beforeRead = pending.revision;
    expect(pending.mark(),isTrue);
    for (var i = 0; i < 999; i++) { expect(pending.mark(),isFalse); }
    expect(pending.dirty,isTrue); expect(pending.revision,1000);
    expect(pending.acceptSnapshot(beforeRead),isFalse);
    expect(pending.dirty,isTrue); // One pending read; no queued payloads.
    final nextRead = pending.revision;
    expect(pending.acceptSnapshot(nextRead),isTrue);
    expect(pending.dirty,isFalse);
    final interrupted = pending.revision;
    pending.mark(disconnected:true);
    expect(pending.lost,isTrue);
    expect(pending.acceptSnapshot(interrupted),isFalse);
    pending.resetSubscription();
    expect(pending.acceptSnapshot(pending.revision),isTrue);
  });
  test('ticket retirement ignores other channel close and post-ACK failure fails closed', () async {
    var failures = 0;
    final tracker = ChannelRetirementTracker('fixture',onOverflow:() { failures++; });
    String opened(int id) => '<- fixture: SSH_Message_Channel_Confirmation(recipientChannel: $id, senderChannel: 7, initialWindowSize: 1, maximumPacketSize: 1)';
    String closed(int id) => '<- fixture: SSH_Message_Channel_Close(recipientChannel: $id)';
    tracker.startOpen(); tracker.beginTicket(); tracker.trace(opened(11));
    final watch = tracker.endTicket(succeeded:true)!; tracker.finishOpen(succeeded:true);
    tracker.startOpen(); tracker.beginTicket(); tracker.trace(opened(12));
    final snapshot = tracker.endTicket(succeeded:true)!; tracker.finishOpen(succeeded:true);
    var retired = false; final waiting = tracker.waitTicket(watch).then((_) { retired = true; });
    tracker.trace(closed(snapshot)); await Future<void>.delayed(Duration.zero);
    expect(retired,isFalse); expect(tracker.activeCount,1);
    tracker.trace(closed(watch)); await waiting; expect(retired,isTrue);
    tracker.startOpen(); tracker.beginTicket(); tracker.trace(opened(13));
    expect(tracker.endTicket(succeeded:false),13); tracker.finishOpen(succeeded:true);
    expect(failures,1); // An exec failure after confirmation cannot be attributed safely.
    expect(() => tracker.startOpen(),throwsA(failure('channel_capacity')));
  });
  test('socket route comes from the connected socket and only an unrouted socket is system', () {
    const route = 'easy-tier:0123456789abcdef0123456789abcdef:3:a0000000-0000-4000-8000-000000000001';
    final system = FakeSocket(),overlay = FakeRoutedSocket(route);
    expect(connectedSocketRoute(system),'system');
    expect(connectedSocketRoute(overlay),route);
    system.destroy(); overlay.destroy();
  });
  test('MT10 snapshot and input channels both require retirement and channel count stays bounded', () async {
    var overflow = 0;
    final tracker = ChannelRetirementTracker('fixture',onOverflow:() { overflow++; });
    String opened(int id) => '<- fixture: SSH_Message_Channel_Confirmation(recipientChannel: $id, senderChannel: 7, initialWindowSize: 1, maximumPacketSize: 1)';
    String closed(int id) => '<- fixture: SSH_Message_Channel_Close(recipientChannel: $id)';
    for (final id in [1,2,3]) { tracker.startOpen(); tracker.trace(opened(id)); tracker.finishOpen(succeeded:true); }
    var ready = false; final onlyObserver = tracker.waitOnly(1).then((_) { ready = true; });
    tracker.trace(closed(2)); await Future<void>.delayed(Duration.zero); expect(ready,isFalse);
    tracker.trace(closed(3)); await onlyObserver; expect(ready,isTrue);
    for (var id = 4; id <= 10; id++) { tracker.startOpen(); tracker.trace(opened(id)); tracker.finishOpen(succeeded:true); }
    expect(tracker.activeCount,8); expect(() => tracker.startOpen(),throwsA(failure('channel_capacity')));
    expect(overflow,1); expect(tracker.activeCount,8);
  });
  test('MT10 unrecognized confirmation cannot silently retire an opened channel', () {
    var failures = 0;
    final tracker = ChannelRetirementTracker('fixture',onOverflow:() { failures++; });
    tracker.startOpen();
    tracker.trace('<- fixture: SSH_Message_Channel_Confirmation(recipientChannel: 1, senderChannel: 7, initialWindowSize: 1, maximumPacketSize: 1, extra: 0)');
    tracker.finishOpen(succeeded:true);
    expect(failures,1);
    expect(() => tracker.startOpen(),throwsA(failure('channel_capacity')));
  });
  test('MT11 pending channel open retains cleanup until its own late completion', () async {
    final tracker = ChannelRetirementTracker('fixture',onOverflow:() {});
    tracker.startOpen(); var settled = false;
    final pending = tracker.waitPending().then((_) { settled = true; });
    await Future<void>.delayed(Duration.zero); expect(settled,isFalse);
    tracker.finishOpen(succeeded:false); await pending; expect(settled,isTrue);
  });
  test('MT11 unsettled opens have their own limit even before channel confirmation', () {
    var failures = 0;
    final tracker = ChannelRetirementTracker('fixture',onOverflow:() { failures++; });
    for (var i = 0; i < 8; i++) { tracker.startOpen(); }
    expect(tracker.pendingCount,8); expect(tracker.activeCount,0);
    expect(() => tracker.startOpen(),throwsA(failure('channel_capacity'))); expect(failures,1);
    for (var i = 0; i < 8; i++) { tracker.finishOpen(succeeded:false); }
    expect(tracker.pendingCount,0);
  });
  test('unreviewed, multiline pin, wrong wire key, URL host and path aliases fail closed', () {
    final source = fixtureConfig();
    expect(() => RemoteConfig.fromJson({...source,'reviewConfirmed':false}),throwsA(failure('review_required')));
    expect(() => RemoteConfig.fromJson({...source,'expectedHostKey':'${source['expectedHostKey']}\n'}),throwsA(failure('invalid_config')));
    expect(() => RemoteConfig.fromJson({...source,'expectedHostKey':'ssh-ed25519 AAAA'}),throwsA(failure('invalid_host_key')));
    expect(() => RemoteConfig.fromJson({...source,'host':'https://host'}),throwsA(failure('invalid_config')));
    expect(() => RemoteConfig.fromJson({...source,'socketPath':'/tmp/../host'}),throwsA(failure('invalid_path')));
    expect(() => RemoteConfig.fromJson({...source,'session':'default'}),throwsA(failure('invalid_target')));
  });
  test('snapshot binds pane, stable terminal id and derived XDG root, not another same-name pane', () {
    final config = RemoteConfig.fromJson(fixtureConfig());
    final snapshot = {'version':'0.9.5','protocol':22,'panes':[{'pane_id':'w1:p1','terminal_id':'term_abcd'}]};
    final envelope = {'type':'session_snapshot','snapshot':snapshot};
    expect(validateSnapshotTarget(config,envelope),'term_abcd');
    expect(config.observeCommand('term_abcd'),
      "exec /usr/bin/env 'XDG_CONFIG_HOME=/tmp/fixture-config' '/tmp/fixture/herdr' --session 'probe' terminal session observe 'term_abcd' --cols 80 --rows 24");
    expect(() => validateSnapshotTarget(RemoteConfig.fromJson({...fixtureConfig(),'session':'other'}),envelope),throwsA(failure('session_mismatch')));
    expect(() => validateSnapshotTarget(config,{'type':'session_snapshot','snapshot':{...snapshot,'panes':[]}}),throwsA(failure('pane_missing')));
    expect(() => validateSnapshotTarget(config,{'type':'session_snapshot','snapshot':{...snapshot,'protocol':23}}),throwsA(failure('unsupported_protocol')));
    expect(() => validateSnapshotTarget(config,snapshot),throwsA(failure('unsupported_protocol')));
    expect(() => validateSnapshotTarget(config,{...envelope,'type':'another_result'}),throwsA(failure('unsupported_protocol')));
    expect(() => config.observeCommand('term_x;touch /tmp/no'),throwsA(failure('invalid_terminal_id')));
    expect(shellQuote("/tmp/a'b;echo no"),"'/tmp/a'\\''b;echo no'");
  });
  test('MT04 resumed observation rejects a replaced terminal even when pane name is unchanged', () {
    const original = RemotePane('w1:p1','term_abcd');
    requireOriginalObservationTarget(original,const RemoteDashboard(1,'probe',[RemotePane('w1:p1','term_abcd')]));
    for (final panes in <List<RemotePane>>[
      const [],const [RemotePane('w1:p1','term_ffff')],const [RemotePane('w1:p2','term_abcd')],
      const [RemotePane('w1:p1','term_abcd'),RemotePane('w1:p1','term_abcd')],
    ]) {
      expect(() => requireOriginalObservationTarget(original,RemoteDashboard(2,'probe',panes)),throwsA(failure('resume_target_changed')));
    }
  });
  test('nondefault streaming canvas leaves the legacy 80x24 request and target identity independent', () {
    final stream = RemoteConfig.fromJson(fixtureConfig()).withObservationCanvas(160,50);
    final legacy = stream.withObservationCanvas(80,24);
    expect(stream.observeCommand('term_abcd'),endsWith('--cols 160 --rows 50'));
    expect(legacy.observeCommand('term_abcd'),endsWith('--cols 80 --rows 24'));
    expect(stream.observationCols,160); expect(stream.observationRows,50);
    expect(legacy.host,stream.host); expect(legacy.port,stream.port);
    expect(legacy.username,stream.username); expect(legacy.expectedFingerprint,stream.expectedFingerprint);
    expect(legacy.socketPath,stream.socketPath); expect(legacy.session,stream.session);
    expect(legacy.paneId,stream.paneId); expect(legacy.herdrPath,stream.herdrPath);
    expect(legacy.observeCommand('term_abcd'),isNot(contains('resize')));
    expect(stream.observeCommand('term_abcd'),isNot(contains('resize')));
  });
  test('channel retire budget stays two seconds by default and widens per config', () {
    final base = RemoteConfig.fromJson(fixtureConfig());
    expect(base.channelRetireTimeout,const Duration(seconds:2));
    final widened = base.withChannelRetireTimeout(const Duration(seconds:8));
    expect(widened.channelRetireTimeout,const Duration(seconds:8));
    expect(widened.host,base.host); expect(widened.port,base.port);
    expect(widened.socketPath,base.socketPath); expect(widened.session,base.session);
    expect(widened.paneId,base.paneId); expect(widened.expectedFingerprint,base.expectedFingerprint);
    expect(widened.observationCols,base.observationCols); expect(widened.observationRows,base.observationRows);
    expect(widened.withObservationCanvas(160,50).channelRetireTimeout,const Duration(seconds:8));
    expect(base.withObservationCanvas(160,50).channelRetireTimeout,const Duration(seconds:2));
    expect(() => base.withChannelRetireTimeout(Duration.zero),throwsA(failure('invalid_config')));
  });
  test('a missed observation channel CLOSE deadline still fails the connection closed', () {
    final evidence = RemoteEvidence();
    expect(recordChannelRetireMiss(evidence,RemoteChannelRole.observation),isTrue);
    expect(evidence.channelRetireFailures,['observation']);
    expect(evidence.toReport('case',true)['channelRetireFailures'],['observation']);
  });
  test('watch, snapshot and input CLOSE misses retire only that channel and stay bounded in evidence', () {
    for (final role in [RemoteChannelRole.watch,RemoteChannelRole.snapshot,RemoteChannelRole.input]) {
      final evidence = RemoteEvidence();
      expect(recordChannelRetireMiss(evidence,role),isFalse);
      expect(evidence.channelRetireFailures,[role.name]);
      expect(evidence.toReport('case',true)['channelRetireFailures'],[role.name]);
    }
    final evidence = RemoteEvidence();
    for (final role in [RemoteChannelRole.watch,RemoteChannelRole.watch,RemoteChannelRole.input,RemoteChannelRole.observation]) {
      recordChannelRetireMiss(evidence,role);
    }
    expect(evidence.channelRetireFailures,['watch','input','observation']);
    expect(evidence.toReport('case',true)['channelRetireFailures'],['input','observation','watch']);
  });
  test('private key single-line input reconstructs only OpenSSH PEM in memory', () {
    final pem = fixtureConfig()['privateKeyPem'] as String;
    final compact = pem.replaceAll('\n','');
    expect(SSHKeyPair.fromPem(pemFromSingleLineInput(compact)).single.type,'ssh-ed25519');
    expect(() => pemFromSingleLineInput('private-file-path'),throwsA(failure('invalid_private_key')));
  });
  test('legacy first full stays ANSI 80x24 while streaming accepts bounded actual geometry', () async {
    Stream<Uint8List> frame(Map<String,Object?> data) => Stream.value(Uint8List.fromList(utf8.encode('${jsonEncode(data)}\n')));
    final valid = <String,Object?>{'type':'terminal.frame','seq':0,'full':true,'encoding':'ansi','width':80,'height':24,'bytes':base64Encode(utf8.encode('中文 é'))};
    expect(await firstFullFrame(frame(valid)),'中文 é');
    await expectLater(firstFullFrame(frame({...valid,'type':'terminal.closed'})),throwsA(failure('invalid_first_frame')));
    await expectLater(firstFullFrame(frame({...valid,'full':false})),throwsA(failure('invalid_first_frame')));
    await expectLater(firstFullFrame(frame({...valid,'seq':-1})),throwsA(failure('invalid_first_frame')));
    final wide = {...valid,'width':119,'height':40};
    await expectLater(firstFullFrame(frame(wide)),throwsA(failure('invalid_first_frame')));
    await expectLater(validatedFrames(frame(wide),continuous:false).toList(),throwsA(failure('invalid_first_frame')));
    final streamed = await validatedFrames(frame(wide)).single;
    expect(streamed.cols,119); expect(streamed.rows,40); expect(streamed.ansi,'中文 é');
    for (final dimensions in [
      {'width':0,'height':24}, {'width':80,'height':0}, {'width':513,'height':24},
      {'width':80,'height':513}, {'width':512,'height':129}, {'width':80.0,'height':24},
      {'width':null,'height':24}, {'width':80,'height':'24'},
    ]) {
      await expectLater(firstFullFrame(frame({...valid,...dimensions})),throwsA(failure('invalid_first_frame')));
    }
    final missing = {...valid}..remove('width');
    await expectLater(firstFullFrame(frame(missing)),throwsA(failure('invalid_first_frame')));
    await expectLater(boundedLines(Stream.value(Uint8List(1048577))).toList(),throwsA(failure('output_limit')));
  });
  test('stderr and stdout consume one total budget, with a smaller stderr cap', () {
    final budget = ObserveByteBudget();
    budget.add(2097152-65536); budget.add(65536,stderr:true);
    expect(() => budget.add(1),throwsA(failure('output_limit')));
    expect(() => ObserveByteBudget().add(65537,stderr:true),throwsA(failure('output_limit')));
  });
  test('cancel cannot release a pending dial budget; late socket is destroyed and never published', () async {
    final pending = Completer<SSHSocket>(); var calls = 0;
    final adapter = RemoteReadOnlyAdapter(connector:(host,port) {
      calls++; return calls == 1 ? pending.future : Future.error(const RemoteFailure('synthetic_connection'));
    });
    final requested = RemoteConfig.fromJson(fixtureConfig()).withObservationCanvas(160,50);
    final first = expectLater(adapter.read(requested),throwsA(failure('cancelled')));
    await Future<void>.delayed(Duration.zero);
    await adapter.cancel(); await first;
    expect(requested.observationCols,160); expect(requested.observationRows,50);
    await expectLater(adapter.read(RemoteConfig.fromJson(fixtureConfig())),throwsA(failure('connection_busy')));
    expect(calls,1);
    final late = FakeSocket(); pending.complete(late);
    await Future<void>.delayed(Duration.zero);
    expect(late.destroyed,isTrue); expect(adapter.evidence.fullFrameReceived,isFalse);
    expect(adapter.evidence.lateEventsIgnored,greaterThan(0));
    await expectLater(adapter.read(RemoteConfig.fromJson(fixtureConfig())),throwsA(failure('synthetic_connection')));
    expect(calls,2);
  });
  test('MT11 eight connection slots include cancelled dials until late sockets are destroyed', () async {
    final budget = RemoteConnectionBudget(),pending = List.generate(9,(_) => Completer<SSHSocket>());
    final adapters = List.generate(9,(index) => RemoteReadOnlyAdapter(connectionBudget:budget,
      connector:(_,__) => pending[index].future));
    final config = RemoteConfig.fromJson(fixtureConfig());
    final completions = <Future<void>>[];
    for (var i = 0; i < 8; i++) { completions.add(expectLater(adapters[i].read(config),throwsA(failure('cancelled')))); }
    await Future<void>.delayed(Duration.zero);
    expect(budget.inUse,8);
    for (var i = 0; i < 8; i++) { await adapters[i].cancel(); }
    await Future.wait(completions); expect(budget.inUse,8);
    await expectLater(adapters[8].read(config),throwsA(failure('connection_capacity')));
    final late = FakeSocket(); pending[0].complete(late); await Future<void>.delayed(Duration.zero);
    expect(late.destroyed,isTrue); expect(budget.inUse,7);
    final ninth = expectLater(adapters[8].read(config),throwsA(failure('cancelled')));
    await Future<void>.delayed(Duration.zero); await adapters[8].cancel(); await ninth;
    expect(budget.inUse,8);
    for (var i = 1; i < 9; i++) { pending[i].complete(FakeSocket()); }
    await Future<void>.delayed(Duration.zero); expect(budget.inUse,0);
  });
  test('MT11 late socket close failure keeps its admission slot', () async {
    final budget = RemoteConnectionBudget(limit:1),pending = Completer<SSHSocket>();
    final first = RemoteReadOnlyAdapter(connectionBudget:budget,connector:(_,__) => pending.future);
    final second = RemoteReadOnlyAdapter(connectionBudget:budget,connector:(_,__) => Future.error(StateError('must not dial')));
    final config = RemoteConfig.fromJson(fixtureConfig());
    final completed = expectLater(first.read(config),throwsA(failure('cancelled')));
    await Future<void>.delayed(Duration.zero); await first.cancel(); await completed;
    final late = FailedDestroySocket(); pending.complete(late); await Future<void>.delayed(Duration.zero);
    expect(budget.inUse,1); await expectLater(second.read(config),throwsA(failure('connection_capacity')));
    unawaited(late.input.close()); unawaited(late.output.close());
  });
  test('MT11 asynchronous SSH close still occupies its slot after local timeout', () async {
    final budget = RemoteConnectionBudget(limit:1),socket = DelayedCloseSocket();
    final first = RemoteReadOnlyAdapter(connectionBudget:budget,connector:(_,__) async => socket);
    final second = RemoteReadOnlyAdapter(connectionBudget:budget,connector:(_,__) => Future.error(StateError('must not dial')));
    final config = RemoteConfig.fromJson(fixtureConfig());
    final ended = expectLater(first.read(config),throwsA(failure('cancelled')));
    await Future<void>.delayed(Duration.zero);
    final cancelling = first.cancel();
    await Future<void>.delayed(Duration.zero); expect(socket.closeCalled,isTrue);
    await Future<void>.delayed(const Duration(milliseconds:2100));
    await cancelling; await ended;
    expect(socket.destroyed,isTrue); expect(budget.inUse,1);
    await expectLater(second.read(config),throwsA(failure('connection_capacity')));
    socket.closing.complete(); await Future<void>.delayed(Duration.zero);
    expect(budget.inUse,0);
  });
  test('detached transport errors fail the attempt without escaping or releasing a pending dial', () async {
    final pending = Completer<SSHSocket>();
    final adapter = RemoteReadOnlyAdapter(connector:(host,port) {
      scheduleMicrotask(() { throw StateError('synthetic secret must never be reported'); });
      return pending.future;
    });
    await expectLater(adapter.read(RemoteConfig.fromJson(fixtureConfig())),throwsA(failure('async_state_error')));
    expect(adapter.evidence.errorCode,'async_state_error');
    expect(adapter.evidence.fullFrameReceived,isFalse);
    await expectLater(adapter.read(RemoteConfig.fromJson(fixtureConfig())),throwsA(failure('connection_busy')));
    final late = FakeSocket(); pending.complete(late);
    await Future<void>.delayed(Duration.zero);
    expect(late.destroyed,isTrue);
  });
  test('shared dashboard labels are presentation only and unknown status stays unknown', () {
    final wire = jsonDecode(File('assets/shared/dashboard-snapshot.json').readAsStringSync()) as Map<String,dynamic>;
    final config = RemoteConfig.fromJson({...fixtureConfig(),'paneId':''});
    final panes = parseSnapshotDashboard(config,wire['result'] as Map<String,dynamic>,1).panes;
    expect([panes[0].label,panes[0].agent,panes[0].statusLabel,panes[0].workspace],
      ['构建 Android','Codex','工作中','w1']);
    expect([panes[1].terminalId,panes[1].label,panes[1].agent,panes[1].agentStatus],
      ['term_def',null,null,'unknown']);
  });
  test('snapshot list binds all unique pane identities, accepts honest empty and rejects aliases/overlimit', () {
    final config = RemoteConfig.fromJson({...fixtureConfig(),'paneId':''});
    Map<String,dynamic> snapshot(List<Object?> panes) => {'type':'session_snapshot',
      'snapshot':{'version':'0.9.5','protocol':22,'panes':panes}};
    const pane = {'pane_id':'w1:p1','terminal_id':'term_abcd'};
    expect(parseSnapshotDashboard(config,snapshot([]),3).panes,isEmpty);
    expect(parseSnapshotDashboard(config,snapshot([pane]),3).generation,3);
    expect(() => validateSnapshotTarget(config,snapshot([pane])),throwsA(failure('pane_missing')));
    expect(() => parseSnapshotDashboard(config,snapshot([pane,pane]),1),throwsA(failure('invalid_snapshot')));
    expect(() => parseSnapshotDashboard(config,snapshot([pane,{'pane_id':'w1:p2','terminal_id':'term_abcd'}]),1),
      throwsA(failure('invalid_terminal_id')));
    expect(() => parseSnapshotDashboard(config,snapshot(List.filled(257,pane)),1),throwsA(failure('invalid_snapshot')));
  });
  test('continuous full/delta sequences reject missing, duplicate, reordered or malformed frames', () async {
    Map<String,Object?> record(int seq,{bool full=false}) => {'type':'terminal.frame','seq':seq,'full':full,
      'encoding':'ansi','width':80,'height':24,'bytes':base64Encode(utf8.encode('synthetic $seq'))};
    Stream<Uint8List> stream(List<Map<String,Object?>> frames) => Stream.fromIterable(frames.map((f) =>
      Uint8List.fromList(utf8.encode('${jsonEncode(f)}\n'))));
    final frames = await validatedFrames(stream([record(5,full:true),record(6),record(7,full:true)])).toList();
    expect(frames.map((f) => f.seq),[5,6,7]); expect(frames[1].full,isFalse);
    for (final seq in [5,4,7]) {
      await expectLater(validatedFrames(stream([record(5,full:true),record(seq)])).toList(),throwsA(failure('sequence_gap')));
    }
    await expectLater(validatedFrames(stream([record(5)])).toList(),throwsA(failure('invalid_first_frame')));
    for (final invalid in [
      {...record(6),'encoding':'other'}, {...record(6),'width':79},
      {...record(6),'seq':9007199254740992}, {...record(6),'type':'terminal.closed'},
      {...record(6),'bytes':'!!!'}, {...record(6),'bytes':base64Encode([255])},
    ]) {
      await expectLater(validatedFrames(stream([record(5,full:true),invalid])).toList(),throwsA(failure('invalid_frame')));
    }
    await expectLater(validatedFrames(stream([{...record(5,full:true),'bytes':base64Encode(List.filled(65537,65))}])).toList(),
      throwsA(failure('output_limit')));
    final budget = ObserveByteBudget(continuous:true); budget.add(2097153);
    expect(() => budget.add(65537,stderr:true),throwsA(failure('output_limit')));
  });

  test('shared remote geometry cases preserve wire fields and change grid only on sequenced full', () async {
    final file = [File('assets/shared/remote-frame-geometry-v1.json'),
      File('../../validation/shared/remote-frame-geometry-v1.json'),
      File('validation/shared/remote-frame-geometry-v1.json')].firstWhere((file) => file.existsSync());
    final fixture = jsonDecode(file.readAsStringSync()) as Map<String,dynamic>;
    for (final item in fixture['cases'] as List) {
      final published = <RemoteFrame>[];
      final input = (item['frames'] as List).map((geometry) => Uint8List.fromList(utf8.encode('${jsonEncode({
        ...geometry as Map<String,dynamic>,'type':'terminal.frame','encoding':'ansi','bytes':base64Encode(utf8.encode('geometry fixture')),
      })}\n')));
      final accepted = item['accepted'] as List;
      final expectedCount = accepted.takeWhile((value) => value == true).length;
      try {
        await for (final frame in validatedFrames(Stream.fromIterable(input))) { published.add(frame); }
        expect(expectedCount,accepted.length,reason:item['id'] as String);
      } on RemoteFailure {
        expect(expectedCount,lessThan(accepted.length),reason:item['id'] as String);
      }
      expect(published.length,expectedCount,reason:item['id'] as String);
      for (var i = 0; i < published.length; i++) {
        final geometry = item['frames'][i];
        expect(published[i].cols,geometry['width'],reason:item['id'] as String);
        expect(published[i].rows,geometry['height'],reason:item['id'] as String);
      }
    }
  });

}
