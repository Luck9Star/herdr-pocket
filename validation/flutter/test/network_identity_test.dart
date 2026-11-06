import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/foundation.dart' show TargetPlatform,debugDefaultTargetPlatformOverride;
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/network_identity.dart';
import 'package:herdr_flutter_probe/network_profiles.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'network_profiles_test.dart' show testNetwork;

Map<String,Object> identityReply(NetworkProfile p) => {'profileId':p.id,'provider':p.provider,
  'handle':'a0000000-0000-4000-8000-000000000001','instanceId':'b0000000-0000-4000-8000-000000000002','mode':'PRIVATE'};

class MemoryNetworkIdentity implements NetworkIdentityStore {
  @override
  bool supported = true;
  NetworkIdentityRecord? current;
  bool failRead = false,unknownWrite = false;
  int creates = 0,deletes = 0,reads = 0;
  Completer<void>? createWait;
  @override
  Future<NetworkIdentityRecord?> status(NetworkProfile profile) async {
    reads++; if (failRead) throw const RemoteFailure('unavailable'); return current;
  }
  @override
  Future<NetworkIdentityRecord> create(NetworkProfile profile,String mode,Uint8List secret) async {
    creates++; validateNetworkSecret(mode,secret);
    if (createWait != null) await createWait!.future;
    current = NetworkIdentityRecord.checked({...identityReply(profile),'mode':mode},profile);
    if (unknownWrite) throw const RemoteFailure('unknown');
    return current!;
  }
  @override
  Future<void> delete(NetworkProfile profile,NetworkIdentityRecord identity) async {
    deletes++; current = null; if (unknownWrite) throw const RemoteFailure('unknown');
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test('public metadata rejects foreign profile/provider and secret-bearing replies',() {
    final p = testNetwork('easytier'),reply = identityReply(p);
    for (final invalid in [{...reply,'profileId':'0'*32},{...reply,'provider':'tailscale'},
      {...reply,'secret':'must not return'},{...reply,'handle':'relative/path'},
      {...reply,'instanceId':'b0000000-0000-1000-8000-000000000002'},{...reply,'mode':'automatic'}]) {
      expect(() => NetworkIdentityRecord.checked(invalid,p),throwsA(isA<RemoteFailure>()));
    }
    expect(NetworkIdentityRecord.checked(reply,p).profileId,p.id);
  });
  test('private and explicit no-secret modes reject ambiguous or malformed input',() {
    for (final pair in <(String,List<int>)>[('PRIVATE',[]),('PRIVATE',[0]),('PRIVATE',[0xc0,0x80]),
      ('PRIVATE',List.filled(1025,65)),('PUBLIC_NO_SECRET',[65]),('AUTO',[])]) {
      expect(() => validateNetworkSecret(pair.$1,Uint8List.fromList(pair.$2)),throwsA(isA<RemoteFailure>()));
    }
    validateNetworkSecret('PRIVATE',Uint8List.fromList(utf8.encode('合成测试')));
    validateNetworkSecret('PUBLIC_NO_SECRET',Uint8List(0));
  });
  test('unknown create reads current state without replay and clears owned input',() async {
    final p = testNetwork('easytier'),store = MemoryNetworkIdentity()..unknownWrite = true;
    var stopped = 0;
    final s = NetworkIdentitySession(profile:p,store:store,stillCurrent:() => true,closeAffected:() { stopped++; });
    await s.refresh(); final bytes = Uint8List.fromList([65,66]); await s.create('PRIVATE',bytes);
    expect(store.creates,1); expect(store.reads,2); expect(stopped,1); expect(bytes,[0,0]);
    expect(s.record,isNotNull); expect(s.canCreate,isFalse); expect(s.notice,contains('未确认'));
    await s.refresh(); expect(store.creates,1); expect(store.deletes,0); s.dispose();
  });
  test('unknown delete never repeats or recreates an identity',() async {
    final p = testNetwork('easytier'),store = MemoryNetworkIdentity()..unknownWrite = true;
    store.current = NetworkIdentityRecord.checked(identityReply(p),p);
    final s = NetworkIdentitySession(profile:p,store:store,stillCurrent:() => true,closeAffected:() {});
    await s.refresh(); await s.delete();
    expect(store.deletes,1); expect(store.creates,0); expect(s.record,isNull); expect(s.known,isTrue);
    expect(s.notice,contains('未确认')); s.dispose();
  });
  test('unreadable status denies writes and does not reuse a stale record',() async {
    final p = testNetwork('easytier'),store = MemoryNetworkIdentity();
    store.current = NetworkIdentityRecord.checked(identityReply(p),p);
    final s = NetworkIdentitySession(profile:p,store:store,stillCurrent:() => true,closeAffected:() {});
    await s.refresh(); expect(s.canDelete,isTrue); store.failRead = true; await s.refresh();
    expect(s.record,isNull); expect(s.known,isFalse); expect(s.canDelete,isFalse);
    final bytes = Uint8List.fromList([65]); await s.create('PRIVATE',bytes); await s.delete();
    expect(bytes,[0]); expect(store.creates,0); expect(store.deletes,0); s.dispose();
  });
  test('catalog revision change blocks creation and clears the rejected input',() async {
    final p = testNetwork('easytier'),store = MemoryNetworkIdentity(); var current = true;
    final s = NetworkIdentitySession(profile:p,store:store,stillCurrent:() => current,closeAffected:() => fail('must not stop'));
    await s.refresh(); current = false;
    final bytes = Uint8List.fromList([65]); await s.create('PRIVATE',bytes);
    expect(store.creates,0); expect(bytes,[0]); s.dispose();
  });
  test('closing review while create is pending does not undo or repeat the write',() async {
    final p = testNetwork('easytier'),store = MemoryNetworkIdentity()..createWait = Completer<void>();
    final s = NetworkIdentitySession(profile:p,store:store,stillCurrent:() => true,closeAffected:() {});
    await s.refresh(); final bytes = Uint8List.fromList([65]);
    final pending = s.create('PRIVATE',bytes); s.dispose(); store.createWait!.complete(); await pending;
    expect(store.creates,1); expect(store.deletes,0); expect(bytes,[0]);
    final reopened = NetworkIdentitySession(profile:p,store:store,stillCurrent:() => true,closeAffected:() {});
    await reopened.refresh(); expect(reopened.record,isNotNull); reopened.dispose();
  });
  test('native channel admits only create/status/delete and never exposes secret reads',() async {
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    addTearDown(() { debugDefaultTargetPlatformOverride = null; });
    final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    final p = testNetwork('easytier'),methods = <String>[];
    messenger.setMockMethodCallHandler(NativeNetworkIdentityStore.channel,(call) async {
      methods.add(call.method);
      final args = call.arguments as Map;
      expect(args['profileId'],p.id); expect(args['provider'],'easytier');
      if (call.method == 'create') expect(args['secret'],[65]);
      return call.method == 'delete' ? null : identityReply(p);
    });
    addTearDown(() => messenger.setMockMethodCallHandler(NativeNetworkIdentityStore.channel,null));
    final store = NativeNetworkIdentityStore(); final record = await store.create(p,'PRIVATE',Uint8List.fromList([65]));
    await store.status(p); await store.delete(p,record);
    expect(methods,['create','status','delete']);
  });
}
