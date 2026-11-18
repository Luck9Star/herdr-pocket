import 'dart:async';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/network_runtime.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'remote_adapter_test.dart' show FakeSocket,failure;
import 'remote_test_data.dart';

class HeldNativeClose extends NativeNetworkRuntime {
  final closing=Completer<Object?>();
  int closes=0;
  @override Future<Object?> call(String method,Map<String,Object> args) {
    if(method!='streamClose')throw StateError('unexpected fixture call');
    closes++;return closing.future;
  }
}
class RetiringFixtureSocket extends FakeSocket implements RetiringSSHSocket {
  final closing=Completer<bool>();
  @override Future<bool> get retired=>closing.future;
}
Future<void> tick()=>Future<void>.delayed(Duration.zero);
void main() {
  for(final outcome in ['ack','rejected','error']) {
    test('managed socket seals locally once and requires native close $outcome',() async {
      final runtime=HeldNativeClose(),socket=NetworkSSHSocket(runtime,'owned','easy-tier:fixture');
      final retired=socket.retired;var completed=false;
      final waiting=retired.then((ack) {completed=true;return ack;});
      socket.destroy();socket.destroy();await socket.done;await tick();
      expect(runtime.closes,1);expect(completed,isFalse);expect(identical(retired,socket.retired),isTrue);
      if(outcome=='error')runtime.closing.completeError(StateError('synthetic native close unknown'));
      else runtime.closing.complete({'closed':outcome=='ack'});
      expect(await waiting,outcome=='ack');expect(completed,isTrue);
      expect(runtime.closes,1);
    });
  }
  for(final outcome in ['ack','error']) {
    test('real adapter cancel joins managed retirement $outcome without another close',() async {
      final socket=RetiringFixtureSocket(),adapter=RemoteReadOnlyAdapter(connector:(_,__) async=>socket);
      final reading=expectLater(adapter.read(RemoteConfig.fromJson(fixtureConfig())),throwsA(failure('cancelled')));
      await tick();var completed=false;
      final cancelling=adapter.cancel().then<void>((_) {completed=true;});
      final failureExpectation=outcome=='ack'?null:expectLater(cancelling,throwsA(isA<RemoteFailure>()));
      await tick();expect(socket.destroyed,isTrue);expect(completed,isFalse);
      socket.closing.complete(outcome=='ack');
      if(outcome=='ack') {await cancelling;expect(completed,isTrue);}else {await failureExpectation;expect(completed,isFalse);}
      await reading;
    });
  }
}
