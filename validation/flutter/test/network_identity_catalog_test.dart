import 'dart:async';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/network_identity.dart';
import 'package:herdr_flutter_probe/network_identity_dialog.dart';
import 'package:herdr_flutter_probe/network_profiles.dart';
import 'package:herdr_flutter_probe/network_runtime.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'host_catalog_test.dart' show MemoryCatalogStorage,catalogPairing;
import 'network_identity_test.dart' show MemoryNetworkIdentity,identityReply;
import 'network_profiles_test.dart' show testNetwork;
import 'remote_test_data.dart' show fixtureConfig;

Future<void> requireAbsent(MemoryNetworkIdentity store,NetworkProfile profile) async {
  if (await store.status(profile) != null) throw const RemoteFailure('network_identity_present');
}

class FixtureNodeRuntime extends NativeNetworkRuntime {
  FixtureNodeRuntime(this.profile,{this.failStop=false});
  final NetworkProfile profile;
  final bool failStop;
  int statusCalls = 0,stopCalls = 0;
  @override bool get supported => true;
  @override Future<Object?> call(String method,Map<String,Object> args) async {
    if (method == 'nodeStatus') {
      statusCalls++;
      return failStop ? {'state':'engine-started','binding':{
        'profileId':profile.id,'profileRevision':profile.revision,'networkName':profile.settings['networkName'],
        'identityRef':'a0000000-0000-4000-8000-000000000001',
      }} : {'state':'stopped','binding':null};
    }
    if (method == 'nodeStop') { stopCalls++; throw const RemoteFailure('network_stop_unknown'); }
    throw const RemoteFailure('unexpected_fixture_method');
  }
}

CatalogNetworkIdentityStore guarded(HostCatalog catalog,NetworkProfile profile,
    MemoryNetworkIdentity store,void Function() closeAffected,{NativeNetworkRuntime? runtime}) => CatalogNetworkIdentityStore(
  catalog:catalog,profile:profile,expectedRevision:catalog.revision,
  closeAffected:closeAffected,delegate:store,runtime:runtime ?? FixtureNodeRuntime(profile));

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test('pending identity create serializes deletion and its native status check',() async {
    final storage = MemoryCatalogStorage();
    final active = HostCatalog(storage:storage,clock:() => 1000); await active.load();
    final profile = testNetwork('easytier'); await active.addNetwork(profile);
    final captured = active.revision,writes = storage.writes;
    final store = MemoryNetworkIdentity()..createWait = Completer<void>(); var closed = 0;
    final session = NetworkIdentitySession(profile:profile,store:guarded(active,profile,store,() { closed++; }),
      stillCurrent:() => active.ready && active.revision == captured,closeAffected:() {});
    await session.refresh();
    final bytes = Uint8List.fromList([65]),creating = session.create('PRIVATE',bytes);
    await Future<void>.delayed(Duration.zero);
    expect(store.creates,1); expect(active.writing,isTrue); expect(closed,1);
    final removing = active.removeNetwork(profile,expectedRevision:captured,
      beforeRemove:() => requireAbsent(store,profile));
    final rejected = expectLater(removing,throwsA(isA<RemoteFailure>().having((e) => e.code,'code','network_identity_present')));
    await Future<void>.delayed(Duration.zero);
    expect(store.reads,1); expect(storage.writes,writes);
    store.createWait!.complete(); await creating; await rejected;
    expect(active.networkProfiles.single.id,profile.id); expect(storage.writes,writes);
    expect(session.record,isNotNull); expect(session.canDelete,isTrue); expect(active.writing,isFalse);
    expect(store.creates,1); expect(store.deletes,0); expect(bytes,[0]);
    session.dispose(); active.dispose();
  });
  test('catalog change before queued identity dispatch rejects without native mutation or tab closure',() async {
    final storage = MemoryCatalogStorage();
    final active = HostCatalog(storage:storage,clock:() => 1000); await active.load();
    final profile = testNetwork('easytier'); await active.addNetwork(profile);
    final store = MemoryNetworkIdentity(); var closed = 0;
    final session = NetworkIdentitySession(profile:profile,store:guarded(active,profile,store,() { closed++; }),
      stillCurrent:() => true,closeAffected:() {});
    await session.refresh();
    storage.beforeWrite = Completer<void>();
    final host = HostProfile.create('Newly referenced host',fixtureConfig(),catalogPairing(),1000,networkProfileId:profile.id);
    final changing = active.add(host);
    final bytes = Uint8List.fromList([65]),creating = session.create('PRIVATE',bytes);
    await Future<void>.delayed(Duration.zero);
    expect(active.writing,isTrue); expect(store.creates,0); expect(closed,0);
    storage.beforeWrite!.complete(); await changing; await creating;
    expect(store.creates,0); expect(store.deletes,0); expect(closed,0); expect(bytes,[0]);
    expect(active.networkProfiles.single.revision,profile.revision);
    expect(active.networkImpact(profile.id).single.id,host.id);
    expect(session.record,isNull); expect(session.notice,contains('未确认'));
    session.dispose(); active.dispose();
  });
  test('same profile without local identity can be deleted after its serialized check',() async {
    final storage = MemoryCatalogStorage();
    final catalog = HostCatalog(storage:storage,clock:() => 1000);
    await catalog.load(); final profile = testNetwork('easytier'); await catalog.addNetwork(profile);
    final store = MemoryNetworkIdentity(),events = <String>[]; final writes = storage.writes;
    await catalog.removeNetwork(profile,expectedRevision:catalog.revision,beforeRemove:() async {
      events.add('status'); await requireAbsent(store,profile);
    },beforeCommit:() { events.add('close'); });
    expect(events,['status','close']); expect(store.reads,1); expect(catalog.networkProfiles,isEmpty);
    expect(storage.writes,writes+1); expect(store.creates,0); expect(store.deletes,0); catalog.dispose();
  });
  test('unreadable identity status refuses public deletion before tabs or storage change',() async {
    final storage = MemoryCatalogStorage();
    final catalog = HostCatalog(storage:storage,clock:() => 1000);
    await catalog.load(); final profile = testNetwork('easytier'); await catalog.addNetwork(profile);
    final store = MemoryNetworkIdentity()..failRead = true; var closed = false; final writes = storage.writes;
    await expectLater(catalog.removeNetwork(profile,expectedRevision:catalog.revision,
      beforeRemove:() => requireAbsent(store,profile),beforeCommit:() { closed = true; }),throwsA(isA<RemoteFailure>()));
    expect(closed,isFalse); expect(storage.writes,writes); expect(catalog.networkProfiles.single.id,profile.id);
    expect(catalog.ready,isTrue); expect(catalog.writing,isFalse); catalog.dispose();
  });
  test('unknown guarded write is followed only by status reads and never replayed or cleaned up',() async {
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final profile = testNetwork('easytier'); await catalog.addNetwork(profile); final captured = catalog.revision;
    final store = MemoryNetworkIdentity()..unknownWrite = true; var closed = 0;
    final session = NetworkIdentitySession(profile:profile,store:guarded(catalog,profile,store,() { closed++; }),
      stillCurrent:() => catalog.ready && catalog.revision == captured,closeAffected:() {});
    await session.refresh(); final bytes = Uint8List.fromList([65]); await session.create('PRIVATE',bytes);
    expect(store.creates,1); expect(store.reads,2); expect(store.deletes,0); expect(closed,1);
    expect(session.record,isNotNull); expect(session.notice,contains('未确认')); expect(bytes,[0]);
    expect(catalog.writing,isFalse); expect(catalog.revision,captured);
    await session.refresh(); expect(store.creates,1); expect(store.deletes,0); expect(store.reads,3);
    session.dispose(); catalog.dispose();
  });
  test('unknown guarded delete only reads status and never repeats or recreates',() async {
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final profile = testNetwork('easytier'); await catalog.addNetwork(profile); final captured = catalog.revision;
    final store = MemoryNetworkIdentity()..unknownWrite = true
      ..current = NetworkIdentityRecord.checked(identityReply(profile),profile);
    final session = NetworkIdentitySession(profile:profile,store:guarded(catalog,profile,store,() {}),
      stillCurrent:() => catalog.ready && catalog.revision == captured,closeAffected:() {});
    await session.refresh(); await session.delete();
    expect(store.deletes,1); expect(store.creates,0); expect(store.reads,2);
    expect(session.record,isNull); expect(session.notice,contains('未确认')); expect(catalog.writing,isFalse);
    await session.refresh(); expect(store.deletes,1); expect(store.creates,0); expect(store.reads,3);
    session.dispose(); catalog.dispose();
  });
  for (final deleting in [false,true]) {
    test('unknown node stop blocks identity ${deleting ? 'delete' : 'create'} without retry or catalog write',() async {
      final storage = MemoryCatalogStorage();
      final active = HostCatalog(storage:storage,clock:() => 1000); await active.load();
      final profile = testNetwork('easytier'); await active.addNetwork(profile);
      final record = NetworkIdentityRecord.checked(identityReply(profile),profile);
      final store = MemoryNetworkIdentity()..current = deleting ? record : null;
      final runtime = FixtureNodeRuntime(profile,failStop:true); var closed = 0;
      final reviewed = guarded(active,profile,store,() { closed++; },runtime:runtime);
      final writes = storage.writes,revision = active.revision;
      Future<void> mutation() async {
        if (deleting) { await reviewed.delete(profile,record); }
        else { await reviewed.create(profile,'PRIVATE',Uint8List.fromList([65])); }
      }
      await expectLater(mutation(),throwsA(isA<RemoteFailure>()));
      expect(runtime.stopCalls,1); expect(store.creates,0); expect(store.deletes,0);
      expect(closed,1); expect(storage.writes,writes); expect(active.revision,revision);
      await expectLater(mutation(),throwsA(isA<RemoteFailure>()));
      expect(runtime.stopCalls,1); expect(store.creates,0); expect(store.deletes,0);
      expect(storage.writes,writes); expect(active.revision,revision);
      active.dispose();
    });
  }
  test('exact profile mismatch rejects at dispatch even with a matching catalog revision',() async {
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final profile = testNetwork('easytier'); await catalog.addNetwork(profile); var dispatched = false,closed = false;
    await expectLater(catalog.guardedNetworkOperation<void>(profile.change(label:'Foreign snapshot'),
      expectedRevision:catalog.revision,beforeDispatch:() { closed = true; },operation:() async { dispatched = true; }),
      throwsA(isA<RemoteFailure>().having((e) => e.code,'code','network_profile_stale')));
    expect(dispatched,isFalse); expect(closed,isFalse); expect(catalog.writing,isFalse); catalog.dispose();
  });
  testWidgets('backgrounding clears the secret and review without dispatching on resume',(tester) async {
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final profile = testNetwork('easytier'); await catalog.addNetwork(profile);
    final store = MemoryNetworkIdentity(); var closed = 0;
    await tester.pumpWidget(MaterialApp(home:Scaffold(body:NetworkIdentityDialog(
      profile:profile,catalog:catalog,store:store,closeTabs:(_) { closed++; }))));
    await tester.pumpAndSettle();
    addTearDown(() => tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed));
    final field = find.byKey(const ValueKey('network-identity-secret'));
    final review = find.byKey(const ValueKey('network-identity-review'));
    await tester.ensureVisible(field); await tester.enterText(field,'synthetic-local-secret');
    final controller = tester.widget<TextField>(field).controller!;
    await tester.ensureVisible(review); await tester.tap(review); await tester.pump();
    expect(tester.widget<CheckboxListTile>(review).value,isTrue);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive); await tester.pump();
    expect(controller.text,isEmpty);
    expect(field,findsNothing); expect(review,findsNothing);
    expect(store.creates,0); expect(store.deletes,0);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed); await tester.pumpAndSettle();
    expect(tester.widget<TextField>(field).controller!.text,isEmpty);
    expect(tester.widget<CheckboxListTile>(review).value,isFalse);
    expect(store.creates,0); expect(store.deletes,0); expect(closed,0);
    await tester.pumpWidget(const SizedBox.shrink()); catalog.dispose();
  });
}
