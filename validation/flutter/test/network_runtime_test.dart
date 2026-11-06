import 'dart:async';
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/network_runtime.dart';

class FakeRuntime extends NativeNetworkRuntime {
  final calls = <(String,Map<String,Object>)>[];
  final reads = <Completer<Object?>>[];
  final writes = <Completer<Object?>>[];
  final opens = <Completer<Object?>>[];
  final stops = <Completer<Object?>>[],statuses = <Completer<Object?>>[];
  Object? availableReply = {'available':true,'reason':null};
  bool throwWriteSynchronously = false;
  @override bool get supported => true;
  @override Future<Object?> call(String method,Map<String,Object> args) {
    calls.add((method,args));
    if (method == 'streamRead') { final c = Completer<Object?>(); reads.add(c); return c.future; }
    if (method == 'streamWrite') {
      if (throwWriteSynchronously) throw StateError('synthetic write failure');
      final c = Completer<Object?>(); writes.add(c); return c.future;
    }
    if (method == 'streamOpen') { final c = Completer<Object?>(); opens.add(c); return c.future; }
    if (method == 'nodeStop') { final c = Completer<Object?>(); stops.add(c); return c.future; }
    if (method == 'nodeStatus') { final c = Completer<Object?>(); statuses.add(c); return c.future; }
    return Future.value(switch (method) {
      'streamClose' => {'closed':true}, 'streamFlush' => {'flushed':true}, 'available' => availableReply, _ => null,
    });
  }
}

Future<void> tick() => Future<void>.delayed(Duration.zero);

void main() {
  test('available requires the exact two response keys',() async {
    final runtime = FakeRuntime();
    expect(await runtime.available(),isTrue);
    for (final reply in [
      {'available':true,'other':null}, {'available':false}, {'available':true,'reason':null,'extra':null},
      {'available':'true','reason':null}, {'available':true,'reason':1},
    ]) {
      runtime.availableReply = reply;
      await expectLater(runtime.available(),throwsA(anything));
    }
  });
  test('invalid actual route closes the returned stream exactly once',() async {
    const binding = NetworkNodeBinding('0123456789abcdef0123456789abcdef',3,'fixture','a0000000-0000-4000-8000-000000000001');
    for (final response in [
      {'streamId':'bad-route','route':{'provider':'easy-tier','profile_id':binding.profileId,'profile_revision':4,'identity_ref':binding.identityRef}},
      {'streamId':'bad-envelope','route':null},
    ]) {
      final runtime = FakeRuntime();
      final opening = runtime.open(binding,'fixture',22);
      final failed = expectLater(opening,throwsA(anything));
      runtime.opens.single.complete(response); await failed; await tick();
      expect(runtime.calls.where((c) => c.$1 == 'streamClose' && c.$2['streamId'] == response['streamId']).length,1);
    }
    final runtime = FakeRuntime();
    const invalidBinding = NetworkNodeBinding('0123456789abcdef0123456789abcdef',3,'fixture','not-a-uuid');
    final opening = runtime.open(invalidBinding,'fixture',22);
    final failed = expectLater(opening,throwsA(anything));
    runtime.opens.single.complete({'streamId':'bad-canonical','route':{'provider':'easy-tier','profile_id':invalidBinding.profileId,
      'profile_revision':invalidBinding.profileRevision,'identity_ref':invalidBinding.identityRef}});
    await failed; await tick();
    expect(runtime.calls.where((c) => c.$1 == 'streamClose' && c.$2['streamId'] == 'bad-canonical').length,1);
  });
  test('status started during unknown stop cannot unlock the profile',() async {
    final runtime = FakeRuntime();
    const binding = NetworkNodeBinding('abcdef0123456789abcdef0123456789',3,'fixture','a0000000-0000-4000-8000-000000000001');
    final stopping = runtime.stop(binding);
    final oldStatus = runtime.status(binding.profileId);
    final failed = expectLater(stopping,throwsA(anything));
    runtime.stops.single.completeError(StateError('unknown')); await failed;
    runtime.statuses.single.complete({'state':'stopped','binding':null}); await oldStatus;
    expect(runtime.stopUncertain(binding.profileId),isTrue);
    final fresh = runtime.status(binding.profileId);
    runtime.statuses.last.complete({'state':'stopped','binding':null}); await fresh;
    expect(runtime.stopUncertain(binding.profileId),isFalse);
  });
  test('timed-out open is cancelled and a late actual stream is closed',() async {
    final runtime = FakeRuntime();
    const binding = NetworkNodeBinding('0123456789abcdef0123456789abcdef',3,'fixture','a0000000-0000-4000-8000-000000000001');
    final opening = runtime.open(binding,'fixture',22,timeout:const Duration(milliseconds:1));
    await expectLater(opening,throwsA(isA<TimeoutException>()));
    runtime.opens.single.complete({'streamId':'late','route':{'provider':'easy-tier','profile_id':binding.profileId,
      'profile_revision':binding.profileRevision,'identity_ref':binding.identityRef}});
    await tick();
    expect(runtime.calls.where((c) => c.$1 == 'cancelOpen').length,1);
    expect(runtime.calls.where((c) => c.$1 == 'streamClose' && c.$2['streamId'] == 'late').length,1);
  });
  test('partial write advances only accepted prefix and unknown destroys without replay',() async {
    final runtime = FakeRuntime();
    final socket = NetworkSSHSocket(runtime,'fixture','easy-tier:0123456789abcdef0123456789abcdef:3:a0000000-0000-4000-8000-000000000001');
    socket.sink.add([1,2,3,4]);
    expect(runtime.writes.length,1);
    runtime.writes[0].complete({'accepted':2}); await tick();
    expect(runtime.writes.length,2);
    expect(runtime.calls.where((c) => c.$1 == 'streamWrite').last.$2['bytes'],[3,4]);
    runtime.writes[1].completeError(StateError('unknown')); await tick();
    expect(runtime.writes.length,2);
    expect(runtime.calls.where((c) => c.$1 == 'streamClose').length,1);
    await expectLater(socket.done,throwsA(anything));
  });
  test('synchronous bridge write failure closes without a null drain error',() async {
    final runtime = FakeRuntime()..throwWriteSynchronously = true;
    final socket = NetworkSSHSocket(runtime,'fixture','easy-tier:0123456789abcdef0123456789abcdef:3:a0000000-0000-4000-8000-000000000001');
    socket.sink.add([1]);
    await expectLater(socket.done,throwsA(anything));
    expect(runtime.calls.where((c) => c.$1 == 'streamClose').length,1);
  });
  test('read waits for listener and pauses instead of polling ahead',() async {
    final runtime = FakeRuntime();
    final socket = NetworkSSHSocket(runtime,'fixture','easy-tier:0123456789abcdef0123456789abcdef:3:a0000000-0000-4000-8000-000000000001');
    expect(runtime.reads,isEmpty);
    final seen = <int>[];
    late StreamSubscription<Uint8List> subscription;
    subscription = socket.stream.listen((bytes) { seen.addAll(bytes); subscription.pause(); });
    expect(runtime.reads.length,1);
    runtime.reads[0].complete({'bytes':Uint8List.fromList([7]),'eof':false}); await tick();
    expect(seen,[7]); expect(runtime.reads.length,1);
    subscription.resume(); await tick(); expect(runtime.reads.length,2);
    socket.destroy();
    runtime.reads[1].complete({'bytes':Uint8List(0),'eof':true});
    await subscription.cancel();
    expect(runtime.calls.where((c) => c.$1 == 'streamClose').length,1);
  });
  test('pause during an outstanding read buffers once and resumes without losing the pull',() async {
    final runtime = FakeRuntime();
    final socket = NetworkSSHSocket(runtime,'fixture','easy-tier:0123456789abcdef0123456789abcdef:3:a0000000-0000-4000-8000-000000000001');
    final seen = <int>[];
    final subscription = socket.stream.listen(seen.addAll);
    subscription.pause();
    runtime.reads.single.complete({'bytes':Uint8List.fromList([9]),'eof':false}); await tick();
    expect(seen,isEmpty); expect(runtime.reads.length,1);
    subscription.resume(); await tick();
    expect(seen,[9]); expect(runtime.reads.length,2);
    socket.destroy(); runtime.reads.last.complete({'bytes':Uint8List(0),'eof':true});
    await subscription.cancel();
  });
  test('malformed EOF carrying bytes fails closed',() async {
    final runtime = FakeRuntime();
    final socket = NetworkSSHSocket(runtime,'fixture','easy-tier:0123456789abcdef0123456789abcdef:3:a0000000-0000-4000-8000-000000000001');
    final errors = <Object>[];
    final subscription = socket.stream.listen((_) => fail('invalid bytes delivered'),onError:errors.add);
    runtime.reads.single.complete({'bytes':Uint8List.fromList([1]),'eof':true}); await tick();
    expect(errors.length,1); await expectLater(socket.done,throwsA(anything));
    expect(runtime.calls.where((c) => c.$1 == 'streamClose').length,1);
    await subscription.cancel();
  });
  test('bounded write queue rejects overflow and closes without dispatching suffix',() async {
    final runtime = FakeRuntime();
    final socket = NetworkSSHSocket(runtime,'fixture','easy-tier:0123456789abcdef0123456789abcdef:3:a0000000-0000-4000-8000-000000000001');
    socket.sink.add(Uint8List(65536));
    expect(() => socket.sink.add([1]),throwsA(anything));
    runtime.writes[0].complete({'accepted':1}); await tick();
    expect(runtime.writes.length,1);
    await expectLater(socket.done,throwsA(anything));
  });
}
