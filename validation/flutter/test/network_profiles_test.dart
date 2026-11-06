import 'dart:convert';
import 'dart:async';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_tabs.dart';
import 'package:herdr_flutter_probe/network_profiles.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'host_catalog_test.dart' show MemoryCatalogStorage,catalogPairing;
import 'remote_test_data.dart';

NetworkProfile testNetwork([String provider='tailscale']) => NetworkProfile.create('Test $provider',provider,switch (provider) {
  'tailscale' => {'controlUrl':'','hostname':''},
  'easytier' => {'networkName':'test-public','peers':['tcp://relay.example.test:11010']},
  _ => {'networkId':'0123456789abcdef'},
});
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test('shared public network fixture accepts valid profiles and rejects every invalid profile',() async {
    final fixture = jsonDecode(await rootBundle.loadString('assets/shared/network-profiles-v1.json')) as Map;
    for (final entry in fixture['validProfiles'] as List) {
      final profile = Map<String,dynamic>.from((entry as Map)['profile'] as Map);
      expect(NetworkProfile.fromJson(profile).toJson(),profile,reason:entry['name'] as String);
    }
    for (final entry in fixture['invalidProfiles'] as List) {
      expect(() => NetworkProfile.fromJson(Map<String,dynamic>.from((entry as Map)['profile'] as Map)),
        throwsA(isA<RemoteFailure>()),reason:entry['name'] as String);
    }
  });
  test('profile revisions advance for edits and toggles; settings are immutable and overflow fails',() {
    final original = testNetwork('easytier'),changed = original.change(enabled:false);
    expect(changed.revision,2); expect(changed.id,original.id);
    expect(() => changed.settings['networkName'] = 'changed',throwsUnsupportedError);
    expect(() => (changed.settings['peers'] as List).add('tcp://another:10'),throwsUnsupportedError);
    final maximum = NetworkProfile.fromJson({...original.toJson(),'revision':maxNetworkRevision});
    expect(() => maximum.change(label:'Next'),throwsA(isA<RemoteFailure>()));
  });
  test('catalog CAS preserves networks across host operations and restart; binding is explicit',() async {
    final storage = MemoryCatalogStorage();
    final first = HostCatalog(storage:storage,clock:() => 1000); await first.load();
    final network = testNetwork(); await first.addNetwork(network);
    final legacy = HostProfile.create('Legacy metadata',fixtureConfig(),catalogPairing(),1000,provider:'tailscale');
    await first.add(legacy); expect(first.freezeNetwork(legacy).profile,isNull);
    final bound = legacy.change(networkProfileId:network.id,replaceNetwork:true,now:1000); await first.update(bound);
    expect(() => first.freezeNetwork(bound).requireTransport(),throwsA(isA<RemoteFailure>().having((e) => e.code,'code','provider_unavailable')));
    expect(() => first.exportProfiles({bound.id}),throwsA(isA<RemoteFailure>().having((e) => e.code,'code','transfer_network_unavailable')));
    await first.update(bound.change(label:'Renamed',now:1000));
    final restarted = HostCatalog(storage:storage,clock:() => 1000); await restarted.load();
    expect(restarted.ready,isTrue); expect(restarted.networkProfiles.single.toJson(),network.toJson());
    expect(restarted.profiles.single.networkProfileId,network.id);
    expect(jsonDecode(storage.contents)['schemaVersion'],4);
    await expectLater(first.removeNetwork(network),throwsA(isA<RemoteFailure>().having((e) => e.code,'code','network_in_use')));
    first.dispose(); restarted.dispose();
  });
  test('editing one shared network revokes its frozen binding and only its dependent tabs',() async {
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final a = testNetwork(),b = testNetwork('easytier'); await catalog.addNetwork(a); await catalog.addNetwork(b);
    HostProfile host(String label,NetworkProfile network,String handle) {
      final pairing = catalogPairing();
      final profile = HostProfile.create(label,fixtureConfig(),pairing,1000,networkProfileId:network.id);
      return HostProfile.fromJson({...profile.toJson(),'pairing':{...profile.pairingRecord,'handle':handle}},1000);
    }
    final one = host('A',a,'opaque-a'),two = host('B',b,'opaque-b'); await catalog.add(one); await catalog.add(two);
    final frozen = catalog.freezeNetwork(one),tabs = HostTabs();
    tabs.open(one,networks:catalog.networkProfiles); tabs.open(two,networks:catalog.networkProfiles);
    final unaffected = tabs.find(two.id);
    await catalog.updateNetwork(a.change(label:'Changed'));
    tabs.reconcile(catalog.profiles,catalog.networkProfiles);
    expect(tabs.find(one.id),isNull); expect(identical(tabs.find(two.id),unaffected),isTrue);
    expect(frozen.stillCurrent(),isFalse);
    await catalog.updateNetwork(b.change(enabled:false)); tabs.reconcile(catalog.profiles,catalog.networkProfiles);
    expect(tabs.tabs,isEmpty); tabs.dispose(); catalog.dispose();
  });
  test('stale impact preview rejects before revoking a view or writing',() async {
    final storage = MemoryCatalogStorage();
    final active = HostCatalog(storage:storage,clock:() => 1000); await active.load();
    final network = testNetwork(); await active.addNetwork(network); final captured = active.revision;
    await active.addNetwork(testNetwork('zerotier')); var revoked = false; final writes = storage.writes;
    await expectLater(active.updateNetwork(network.change(enabled:false),expectedRevision:captured,beforeCommit:() { revoked = true; }),throwsA(isA<RemoteFailure>()));
    expect(revoked,isFalse); expect(storage.writes,writes); expect(active.networkProfiles.first.enabled,isTrue); active.dispose();
  });
  test('unknown network save locks the whole catalog and never retries the mutation',() async {
    final storage = MemoryCatalogStorage();
    final active = HostCatalog(storage:storage,clock:() => 1000); await active.load();
    final network = testNetwork(); await active.addNetwork(network);
    storage.beforeWrite = Completer<void>(); var stopped = false;
    final pending = active.updateNetwork(network.change(enabled:false),beforeCommit:() { stopped = true; });
    final rejected = expectLater(pending,throwsA(isA<RemoteFailure>()));
    await Future<void>.delayed(Duration.zero);
    expect(stopped,isTrue); storage.revision = List.filled(64,'f').join();
    storage.beforeWrite!.complete(); await rejected;
    expect(active.ready,isFalse); expect(active.networkProfiles.single.enabled,isTrue);
    final writes = storage.writes;
    await expectLater(active.updateNetwork(network.change(label:'Do not replay')),throwsA(isA<RemoteFailure>()));
    expect(storage.writes,writes); active.dispose();
  });
  test('missing network reference or secret-bearing network catalog is rejected without overwriting',() async {
    final storage = MemoryCatalogStorage(),network = testNetwork();
    final host = HostProfile.create('Bound',fixtureConfig(),catalogPairing(),1000,networkProfileId:network.id);
    for (final networks in [<dynamic>[],[{...network.toJson(),'privateKeyPem':'synthetic-rejected'}]]) {
      storage.contents = jsonEncode({'schemaVersion':4,'profiles':[host.toJson()],'pendingCreation':null,'networkProfiles':networks});
      storage.revision = List.filled(64,'a').join();
      final catalog = HostCatalog(storage:storage,clock:() => 1000); await catalog.load();
      expect(catalog.ready,isFalse); expect(storage.writes,0); catalog.dispose();
    }
  });
}
