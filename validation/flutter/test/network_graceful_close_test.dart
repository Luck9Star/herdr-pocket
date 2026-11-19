import 'dart:async';
import 'dart:io';
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_tabs.dart';
import 'package:herdr_flutter_probe/network_runtime.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'host_catalog_test.dart' show catalogPairing;
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

// Replace only the platform channel boundary; each peer observes real TCP EOF.
class LoopbackGraceRuntime extends NativeNetworkRuntime {
  LoopbackGraceRuntime(this.sockets) : readers = sockets.map((id, socket) => MapEntry(id, StreamIterator(socket)));
  final Map<String,Socket> sockets;
  final Map<String,StreamIterator<Uint8List>> readers;
  final calls = <String>[];
  @override Future<Object?> call(String method, Map<String,Object> args) async {
    final id = args['streamId'] as String;
    final socket = sockets[id]!;
    calls.add('$id:$method');
    switch (method) {
      case 'streamRead':
        final reader = readers[id]!;
        final next = await reader.moveNext();
        return {'bytes': next ? reader.current : Uint8List(0), 'eof': !next};
      case 'streamFlush': await socket.flush(); return {'flushed': true};
      case 'streamShutdown': await socket.close(); return {'shutdown': true};
      case 'streamClose': socket.destroy(); return {'closed': true};
      default: throw StateError('unexpected loopback stream operation');
    }
  }
}

Future<void> tick()=>Future<void>.delayed(Duration.zero);
void main() {
  test('closing tab A sends real TCP EOF while B receives fresh bytes on its original connection', () async {
    const bound = Duration(seconds: 3);
    final server = await ServerSocket.bind(InternetAddress.loopbackIPv4, 0);
    final peers = <Socket>[];
    final first = Completer<Socket>(), second = Completer<Socket>();
    server.listen((peer) {
      peers.add(peer);
      if (peers.length == 1) first.complete(peer);
      if (peers.length == 2) second.complete(peer);
    });
    addTearDown(() async { for (final peer in peers) { peer.destroy(); } await server.close(); });
    final aSocket = await Socket.connect(server.address, server.port, timeout: bound);
    addTearDown(aSocket.destroy);
    final aPeer = await first.future.timeout(bound);
    final bSocket = await Socket.connect(server.address, server.port, timeout: bound);
    addTearDown(bSocket.destroy);
    final bPeer = await second.future.timeout(bound);
    final input = [<int>[], <int>[]];
    final aEof = Completer<void>();
    aPeer.listen(input[0].addAll, onDone: () { aEof.complete(); unawaited(aPeer.close()); });
    bPeer.listen(input[1].addAll);

    final runtime = LoopbackGraceRuntime({'A': aSocket, 'B': bSocket});
    final a = NetworkSSHSocket(runtime, 'A', 'easy-tier:fixture');
    final b = NetworkSSHSocket(runtime, 'B', 'easy-tier:fixture');
    final readingA = a.stream.listen((_) {});
    final readingB = StreamIterator(b.stream);
    addTearDown(readingA.cancel);
    addTearDown(readingB.cancel);
    final tabs = HostTabs();
    addTearDown(tabs.dispose);
    HostProfile host(String label) => HostProfile.create(label, fixtureConfig(), catalogPairing(authorized: true), 1000);
    tabs.open(host('A'));
    final tabA = tabs.active!;
    tabs.open(host('B'));
    final tabB = tabs.active!;
    final aClosing = Completer<bool>();
    tabA.registerTransport(() async { aClosing.complete(await a.finishGracefully()); });
    bPeer.add([1]);
    expect(await readingB.moveNext().timeout(bound), isTrue);
    expect(readingB.current, [1]);

    tabs.close(tabA.id);
    await aEof.future.timeout(bound);
    expect(await aClosing.future.timeout(bound), isTrue);
    expect(await a.retired.timeout(bound), isTrue);
    expect(runtime.calls.where((call) => call == 'A:streamShutdown'), ['A:streamShutdown']);
    expect(runtime.calls.where((call) => call == 'A:streamClose'), ['A:streamClose']);
    bPeer.add([2]);
    expect(await readingB.moveNext().timeout(bound), isTrue);
    expect(readingB.current, [2]);
    expect(tabs.active, same(tabB));
    expect(peers, [aPeer, bPeer]);
    expect(runtime.calls.where((call) => call.startsWith('B:')).every((call) => call == 'B:streamRead'), isTrue);
    expect(input, [<int>[], <int>[]]);
  });
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
