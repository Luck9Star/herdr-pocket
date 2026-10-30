import 'dart:async';
import 'dart:convert';
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
    expect(validateSnapshotTarget(config,snapshot),'term_abcd');
    expect(config.observeCommand('term_abcd'),
      "/usr/bin/env 'XDG_CONFIG_HOME=/tmp/fixture-config' '/tmp/fixture/herdr' --session 'probe' terminal session observe 'term_abcd' --cols 80 --rows 24");
    expect(() => validateSnapshotTarget(RemoteConfig.fromJson({...fixtureConfig(),'session':'other'}),snapshot),throwsA(failure('session_mismatch')));
    expect(() => validateSnapshotTarget(config,{'version':'0.9.5','protocol':22,'panes':[]}),throwsA(failure('pane_missing')));
    expect(() => validateSnapshotTarget(config,{...snapshot,'protocol':23}),throwsA(failure('unsupported_protocol')));
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
}
