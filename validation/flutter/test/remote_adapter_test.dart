import 'dart:async';
import 'dart:convert';
import 'dart:io' show File;
import 'dart:typed_data';
import 'package:dartssh2/dartssh2.dart';
import 'package:flutter_test/flutter_test.dart';
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

void main() {
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
      "/usr/bin/env 'XDG_CONFIG_HOME=/tmp/fixture-config' '/tmp/fixture/herdr' --session 'probe' terminal session observe 'term_abcd' --cols 80 --rows 24");
    expect(() => validateSnapshotTarget(RemoteConfig.fromJson({...fixtureConfig(),'session':'other'}),envelope),throwsA(failure('session_mismatch')));
    expect(() => validateSnapshotTarget(config,{'type':'session_snapshot','snapshot':{...snapshot,'panes':[]}}),throwsA(failure('pane_missing')));
    expect(() => validateSnapshotTarget(config,{'type':'session_snapshot','snapshot':{...snapshot,'protocol':23}}),throwsA(failure('unsupported_protocol')));
    expect(() => validateSnapshotTarget(config,snapshot),throwsA(failure('unsupported_protocol')));
    expect(() => validateSnapshotTarget(config,{...envelope,'type':'another_result'}),throwsA(failure('unsupported_protocol')));
    expect(() => config.observeCommand('term_x;touch /tmp/no'),throwsA(failure('invalid_terminal_id')));
    expect(shellQuote("/tmp/a'b;echo no"),"'/tmp/a'\\''b;echo no'");
  });
  test('private key single-line input reconstructs only OpenSSH PEM in memory', () {
    final pem = fixtureConfig()['privateKeyPem'] as String;
    final compact = pem.replaceAll('\n','');
    expect(SSHKeyPair.fromPem(pemFromSingleLineInput(compact)).single.type,'ssh-ed25519');
    expect(() => pemFromSingleLineInput('private-file-path'),throwsA(failure('invalid_private_key')));
  });
  test('first real frame must be full ANSI 80x24, strict UTF8 and bounded', () async {
    Stream<Uint8List> frame(Map<String,Object?> data) => Stream.value(Uint8List.fromList(utf8.encode('${jsonEncode(data)}\n')));
    final valid = <String,Object?>{'type':'terminal.frame','seq':0,'full':true,'encoding':'ansi','width':80,'height':24,'bytes':base64Encode(utf8.encode('中文 é'))};
    expect(await firstFullFrame(frame(valid)),'中文 é');
    await expectLater(firstFullFrame(frame({...valid,'type':'terminal.closed'})),throwsA(failure('invalid_first_frame')));
    await expectLater(firstFullFrame(frame({...valid,'full':false})),throwsA(failure('invalid_first_frame')));
    await expectLater(firstFullFrame(frame({...valid,'seq':-1})),throwsA(failure('invalid_first_frame')));
    await expectLater(firstFullFrame(frame({...valid,'width':81})),throwsA(failure('invalid_first_frame')));
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
    final first = expectLater(adapter.read(RemoteConfig.fromJson(fixtureConfig())),throwsA(failure('cancelled')));
    await Future<void>.delayed(Duration.zero);
    await adapter.cancel(); await first;
    await expectLater(adapter.read(RemoteConfig.fromJson(fixtureConfig())),throwsA(failure('connection_busy')));
    expect(calls,1);
    final late = FakeSocket(); pending.complete(late);
    await Future<void>.delayed(Duration.zero);
    expect(late.destroyed,isTrue); expect(adapter.evidence.fullFrameReceived,isFalse);
    expect(adapter.evidence.lateEventsIgnored,greaterThan(0));
    await expectLater(adapter.read(RemoteConfig.fromJson(fixtureConfig())),throwsA(failure('synthetic_connection')));
    expect(calls,2);
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

}
