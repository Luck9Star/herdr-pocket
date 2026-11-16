import 'dart:async';
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/network_runtime.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'remote_adapter_test.dart' show FakeSocket,failure;
import 'remote_test_data.dart';

class GraceRuntime extends NativeNetworkRuntime {
  final calls=<String>[];
  final reads=<Completer<Object?>>[];
  final writes=<Completer<Object?>>[];
  Object? shutdown={'shutdown':true};
  bool holdWrite=false,failShutdown=false,holdShutdown=false;
  final shutting=Completer<Object?>();
  @override Future<Object?> call(String method,Map<String,Object> args) {
    calls.add('${args['streamId']}:$method');
    if(method=='streamRead') {final c=Completer<Object?>();reads.add(c);return c.future;}
    if(method=='streamWrite') {
      if(holdWrite){final c=Completer<Object?>();writes.add(c);return c.future;}
      return Future.value({'accepted':(args['bytes'] as Uint8List).length});
    }
    if(method=='streamFlush')return Future.value({'flushed':true});
    if(method=='streamShutdown' && holdShutdown)return shutting.future;
    if(method=='streamShutdown')return failShutdown?Future.error(StateError('synthetic shutdown unavailable')):Future.value(shutdown);
    if(method=='streamClose')return Future.value({'closed':true});
    throw StateError('unexpected fixture method');
  }
}
class GraceFixtureSocket extends FakeSocket implements RetiringSSHSocket,GracefulSSHSocket {
  final preparing=Completer<bool>();
  int prepares=0;
  @override Future<bool> finishGracefully({Duration budget=const Duration(seconds:1)}) {prepares++;return preparing.future;}
  @override Future<bool> get retired=>Future.value(true);
}
Future<void> tick()=>Future<void>.delayed(Duration.zero);
void main() {
  test('explicit close seals writes, drains once, half closes, preserves peer reply and waits EOF',() async {
    final runtime=GraceRuntime()..holdWrite=true;
    final a=NetworkSSHSocket(runtime,'A','easy-tier:fixture'),b=NetworkSSHSocket(runtime,'B','easy-tier:other');
    final received=<int>[];final subscription=a.stream.listen(received.addAll);
    a.sink.add([65]);await tick();
    final closing=a.finishGracefully();
    expect(()=>a.sink.add([88]),throwsA(isA<RemoteFailure>()));
    await tick();expect(runtime.calls.where((x)=>x=='A:streamShutdown'),isEmpty);
    runtime.writes.single.complete({'accepted':1});await tick();await tick();
    expect(runtime.calls.where((x)=>x=='A:streamWrite').length,1);
    expect(runtime.calls.where((x)=>x=='A:streamShutdown').length,1);
    expect(runtime.calls.where((x)=>x=='A:streamClose'),isEmpty);
    var completed=false;closing.then((_) {completed=true;});await tick();expect(completed,isFalse);
    runtime.reads[0].complete({'bytes':Uint8List.fromList([82]),'eof':false});await tick();
    expect(received,[82]);expect(completed,isFalse);
    runtime.reads[1].complete({'bytes':Uint8List(0),'eof':true});
    expect(await closing,isTrue);expect(await a.retired,isTrue);
    expect(runtime.calls.where((x)=>x=='A:streamClose').length,1);
    expect(runtime.calls.where((x)=>x.startsWith('B:')),isEmpty);
    runtime.holdWrite=false;b.sink.add([66]);await tick();expect(runtime.calls,contains('B:streamWrite'));
    b.destroy();await b.retired;await subscription.cancel();
  });
  for(final outcome in ['timeout','rejected','error']) {
    test('explicit close $outcome forces original retirement once and never repeats shutdown',() async {
      final runtime=GraceRuntime();
      if(outcome=='rejected')runtime.shutdown={'shutdown':false};
      if(outcome=='error')runtime.failShutdown=true;
      final socket=NetworkSSHSocket(runtime,'A','easy-tier:fixture');final subscription=socket.stream.listen((_) {});
      final closing=socket.finishGracefully(budget:const Duration(milliseconds:20));
      expect(identical(closing,socket.finishGracefully()),isTrue);
      expect(await closing,isFalse);expect(await socket.retired,isTrue);
      expect(runtime.calls.where((x)=>x=='A:streamShutdown').length,1);
      expect(runtime.calls.where((x)=>x=='A:streamClose').length,1);
      runtime.reads.single.complete({'bytes':Uint8List(0),'eof':true});await tick();
      expect(await closing,isFalse);expect(runtime.calls.where((x)=>x=='A:streamClose').length,1);
      await subscription.cancel();
    });
  }
  test('late native shutdown and EOF cannot revive a timed-out close',() async {
    final runtime=GraceRuntime()..holdShutdown=true;
    final socket=NetworkSSHSocket(runtime,'A','easy-tier:fixture');final subscription=socket.stream.listen((_) {});
    final closing=socket.finishGracefully(budget:const Duration(milliseconds:20));
    expect(await closing,isFalse);expect(await socket.retired,isTrue);
    runtime.shutting.complete({'shutdown':true});
    runtime.reads.single.complete({'bytes':Uint8List(0),'eof':true});await tick();
    expect(await socket.finishGracefully(),isFalse);
    expect(runtime.calls.where((x)=>x=='A:streamShutdown').length,1);
    expect(runtime.calls.where((x)=>x=='A:streamClose').length,1);
    await subscription.cancel();
  });
  for(final peerEof in [true,false]) {
    test('shutdown ACK after local close requires original peer EOF: $peerEof',() async {
      final runtime=GraceRuntime()..holdShutdown=true;
      final socket=NetworkSSHSocket(runtime,'A','easy-tier:fixture');final subscription=socket.stream.listen((_) {});
      final closing=socket.finishGracefully();await tick();
      if(peerEof)runtime.reads.single.complete({'bytes':Uint8List(0),'eof':true});else socket.destroy();
      await tick();expect(await socket.retired,isTrue);
      runtime.shutting.complete({'shutdown':true});
      expect(await closing,peerEof);
      expect(runtime.calls.where((x)=>x=='A:streamShutdown').length,1);
      expect(runtime.calls.where((x)=>x=='A:streamClose').length,1);
      if(!peerEof)runtime.reads.single.complete({'bytes':Uint8List(0),'eof':true});
      await subscription.cancel();
    });
  }
  test('hard destroy never starts graceful flush or shutdown',() async {
    final runtime=GraceRuntime(),socket=NetworkSSHSocket(runtime,'A','easy-tier:fixture');
    socket.destroy();socket.destroy();expect(await socket.retired,isTrue);
    expect(runtime.calls,['A:streamClose']);expect(await socket.finishGracefully(),isFalse);
  });
  test('real SSH transport keeps its original reader until managed half-close receives EOF',() async {
    final runtime=GraceRuntime();
    final socket=NetworkSSHSocket(runtime,'A','easy-tier:0123456789abcdef0123456789abcdef:1:a0000000-0000-4000-8000-000000000001');
    final adapter=RemoteReadOnlyAdapter(connector:(_,__) async=>socket);
    final reading=expectLater(adapter.read(RemoteConfig.fromJson(fixtureConfig())),throwsA(failure('cancelled')));
    await tick();await tick();expect(runtime.reads,isNotEmpty);
    adapter.requestGracefulClose();final cancelling=adapter.cancel();
    await tick();await tick();
    expect(runtime.calls.where((x)=>x=='A:streamShutdown').length,1);
    expect(runtime.calls.where((x)=>x=='A:streamClose'),isEmpty);
    runtime.reads.single.complete({'bytes':Uint8List(0),'eof':true});
    await cancelling;await reading;
    expect(runtime.calls.indexOf('A:streamShutdown'),lessThan(runtime.calls.indexOf('A:streamClose')));
    expect(runtime.calls.where((x)=>x=='A:streamClose').length,1);
  });
  for(final explicit in [true,false]) {
    for(final ack in [true,false]) {
      test('real adapter explicit=$explicit gracefulAck=$ack retains ordinary hard-cancel contract',() async {
        final socket=GraceFixtureSocket(),adapter=RemoteReadOnlyAdapter(connector:(_,__) async=>socket);
        final reading=expectLater(adapter.read(RemoteConfig.fromJson(fixtureConfig())),throwsA(failure('cancelled')));
        await tick();if(explicit)adapter.requestGracefulClose();
        final cancelling=adapter.cancel();
        final unknown=explicit&&!ack?expectLater(cancelling,throwsA(isA<RemoteFailure>())):null;
        await tick();expect(socket.prepares,explicit?1:0);expect(socket.destroyed,!explicit);
        if(explicit)socket.preparing.complete(ack);
        if(unknown!=null)await unknown;else await cancelling;
        await reading;expect(socket.destroyed,isTrue);expect(socket.prepares,explicit?1:0);
      });
    }
  }
}
