import 'dart:async';
import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/pairing.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'remote_test_data.dart';

class MemoryCatalogStorage implements HostCatalogStorage {
  String contents = '',revision = '';
  int writes = 0;
  Completer<void>? beforeWrite;
  @override
  Future<({String revision,String contents})> load() async => (revision:revision,contents:contents);
  @override
  Future<String> save(String expected,String contents) async {
    writes++; await beforeWrite?.future;
    if (expected != revision) throw const RemoteFailure('catalog_conflict');
    this.contents = contents; revision = writes.toRadixString(16).padLeft(64,'0'); return revision;
  }
}
PendingDevicePairing catalogPairing({bool authorized = false}) {
  final config = fixtureConfig(), key = fixtureConfig()['expectedHostKey'] as String;
  final p = PendingDevicePairing(handle:'test-opaque-handle',publicKey:key,account:config['username'] as String,
    hostKey:pairingFingerprint(key),device:'Test phone',now:1000);
  if (authorized) p.accept(jsonEncode({'version':2,'type':'pairing-binding-response','request_id':p.request['request_id'],
    'account':p.request['account'],'host_key':p.request['host_key'],'fingerprint':pairingFingerprint(key),
    'issued_at':1000,'expires_at':1600,'status':'authorized','authorization_added':true}),now:1000,reviewed:true);
  return p;
}
Future<HostProfile> saveCatalogProfile(HostCatalog catalog,{bool authorized = true}) async {
  final p = catalogPairing(authorized:authorized), profile = HostProfile.create('Fixture host',fixtureConfig(),catalogPairing(authorized:authorized),1000);
  // Use the same pending object for the persisted identity/request.
  final bound = HostProfile.fromJson({...profile.toJson(),'pairing':p.toPublicRecord()},1000);
  await catalog.beginCreation(fixtureConfig(),'Fixture host');
  await catalog.recordCreatedHandle(p.handle); await catalog.completeCreation(bound); return bound;
}
void main() {
  test('creation intent and key binding survive process restart; trust and live connection do not',() async {
    final disk = MemoryCatalogStorage();
    final first = HostCatalog(storage:disk,clock:() => 1000); await first.load();
    final profile = await saveCatalogProfile(first);
    final live = profile.restore(1000); final ticket = live.connect(); live.connectionResult(ticket,true);
    await first.update(profile.change(pairing:live,now:1000));
    final restarted = HostCatalog(storage:disk,clock:() => 1001); await restarted.load();
    expect(restarted.ready,isTrue); expect(restarted.profiles.single.id,profile.id);
    expect(restarted.profiles.single.restore(1001).state,'waiting-connectivity');
    expect(restarted.profiles.single.restore(1001).handle,live.handle);
    expect(disk.contents.contains('privateKeyPem'),isFalse); expect(disk.contents.contains('reviewConfirmed'),isFalse);
    expect(restarted.pendingCreation,isNull); first.dispose(); restarted.dispose();
  });
  test('unknown create persists a blocking intent; known handle can be explicitly cleaned',() async {
    final disk = MemoryCatalogStorage();
    final catalog = HostCatalog(storage:disk,clock:() => 1000); await catalog.load();
    await catalog.beginCreation(fixtureConfig(),'Pending phone');
    expect(catalog.pendingCreation!['target'],isA<Map<String,dynamic>>());
    final restarted = HostCatalog(storage:disk,clock:() => 1000); await restarted.load();
    expect(restarted.pendingCreation!['handle'],'');
    expect(restarted.pendingCreation!['target'],isA<Map<String,dynamic>>());
    expect(() => restarted.beginCreation(fixtureConfig(),'Replacement'),throwsA(isA<RemoteFailure>()));
    await restarted.recordCreatedHandle('known-handle');
    expect(restarted.pendingCreation!['handle'],'known-handle');
    expect(restarted.pendingCreation!['target'],catalog.pendingCreation!['target']);
    await restarted.clearDeletedCreation('known-handle'); expect(restarted.pendingCreation,isNull);
    catalog.dispose(); restarted.dispose();
  });
  test('pending intent remains typed and immutable through repeated in-memory validation',() {
    final config = fixtureConfig();
    Map<String,dynamic> pending = {
      'id':List.filled(32,'a').join(),'label':'Pending phone','handle':'',
      'target':<String,dynamic>{for (final name in HostProfile.targetFields) name:config[name]},
    };
    for (var pass = 0; pass < 3; pass++) {
      pending = validatePendingCreation(pending)!;
      expect(pending,isA<Map<String,dynamic>>());
      expect(pending['target'],isA<Map<String,dynamic>>());
      expect(() => pending['handle'] = 'changed',throwsUnsupportedError);
      expect(() => (pending['target'] as Map<String,dynamic>)['host'] = 'changed',throwsUnsupportedError);
      pending = {...pending,'handle':'known-handle'};
    }
    expect(pending['handle'],'known-handle');
  });
  test('typed pending normalization still rejects extra fields and malformed target maps',() {
    final config = fixtureConfig();
    final target = <String,dynamic>{for (final name in HostProfile.targetFields) name:config[name]};
    final pending = <String,dynamic>{'id':List.filled(32,'a').join(),'label':'Pending phone','handle':'','target':target};
    for (final invalid in <Map<String,dynamic>>[
      {...pending,'privateKeyPem':'forbidden'},
      {...pending,'target':<String,dynamic>{...target,'privateKeyPem':'forbidden'}},
      {...pending,'target':<dynamic,dynamic>{...target}},
      {...pending,'target':<String,dynamic>{...target}..remove('host')},
    ]) {
      expect(() => validatePendingCreation(invalid),throwsA(isA<RemoteFailure>()));
    }
  });
  test('corruption, duplicate decoded fields, secret fields and wrong account binding fail closed',() async {
    final disk = MemoryCatalogStorage();
    final profile = HostProfile.create('Fixture',fixtureConfig(),catalogPairing(),1000);
    final valid = {'schemaVersion':1,'profiles':[profile.toJson()],'pendingCreation':null};
    for (final raw in [jsonEncode(valid).replaceFirst('{','{"schemaVersion":1,'),jsonEncode({...valid,'privateKeyPem':'forbidden'}),
      jsonEncode({...valid,'profiles':[{...profile.toJson(),'target':{...profile.target,'username':'other'}}]}),
      jsonEncode({...valid,'profiles':[{...profile.toJson(),'pairing':{...profile.pairingRecord,'handle':''}}]}),
      '{"schemaVersion":1,"profiles":[],"pendingCreation":null,"\\u0070rofiles":[]}']) {
      disk.contents = raw; disk.revision = List.filled(64,'a').join();
      final reopened = HostCatalog(storage:disk,clock:() => 1000); await reopened.load();
      expect(reopened.ready,isFalse); expect(reopened.profiles,isEmpty); expect(disk.writes,0); reopened.dispose();
    }
  });
  test('stale CAS failure locks writes and does not replay queued operations',() async {
    final disk = MemoryCatalogStorage();
    final active = HostCatalog(storage:disk,clock:() => 1000); await active.load(); final profile = await saveCatalogProfile(active);
    disk.beforeWrite = Completer<void>();
    final changed = active.update(profile.change(label:'Renamed',now:1000));
    final checked = expectLater(changed,throwsA(isA<RemoteFailure>()));
    await Future<void>.delayed(Duration.zero); disk.revision = List.filled(64,'f').join();
    disk.beforeWrite!.complete(); await checked;
    expect(active.ready,isFalse); expect(active.profiles.single.label,'Fixture host');
    final count = disk.writes;
    await expectLater(active.update(profile.change(label:'Other',now:1000)),throwsA(isA<RemoteFailure>())); expect(disk.writes,count); active.dispose();
  });
  test('a delayed profile snapshot cannot undo a newer local change',() async {
    final disk = MemoryCatalogStorage();
    final active = HostCatalog(storage:disk,clock:() => 1000); await active.load();
    final original = await saveCatalogProfile(active);
    await active.update(original.change(enabled:false,now:1000));
    final writes = disk.writes;
    await expectLater(active.update(original.change(label:'Late name',now:1000)),throwsA(isA<RemoteFailure>()));
    expect(active.profiles.single.enabled,isFalse); expect(disk.writes,writes); active.dispose();
  });
  test('rename and enable preserve key and pinned target; target replacement is rejected',() async {
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final original = await saveCatalogProfile(catalog);
    await catalog.update(original.change(label:'My phone host',enabled:false,now:1000));
    final edited = catalog.profiles.single; expect(edited.enabled,isFalse); expect(edited.label,'My phone host');
    expect(edited.target,original.target); expect(edited.pairingRecord['handle'],original.pairingRecord['handle']); catalog.dispose();
  });
}
