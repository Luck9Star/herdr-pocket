import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/foundation.dart' show TargetPlatform,debugDefaultTargetPlatformOverride;
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/network_identity.dart';
import 'package:herdr_flutter_probe/network_identity_dialog.dart';
import 'package:herdr_flutter_probe/network_profiles.dart';
import 'package:herdr_flutter_probe/network_runtime.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'package:herdr_flutter_probe/remote_input.dart';
import 'host_catalog_test.dart' show MemoryCatalogStorage;
import 'network_profiles_test.dart' show testNetwork;

Map<String,Object> tailscaleIdentityReply(NetworkProfile profile) => {
  'profileId':profile.id,'provider':'tailscale','handle':'a0000000-0000-4000-8000-000000000001',
  'instanceId':'b0000000-0000-4000-8000-000000000002','mode':'DEVICE_STATE',
};
NetworkNodeBinding tailscaleBinding(NetworkProfile profile) =>
  NetworkNodeBinding.forProfile(profile,NetworkIdentityRecord.checked(tailscaleIdentityReply(profile),profile));

class TailscaleIdentityFixture implements NetworkIdentityStore {
  @override bool get supported => true;
  NetworkIdentityRecord? record;
  bool unknownWrite = false,failRead = false;
  int creates = 0,deletes = 0,reads = 0;
  @override Future<NetworkIdentityRecord?> status(NetworkProfile profile) async {
    reads++; if (failRead) throw const RemoteFailure('fixture_read_failed'); return record;
  }
  @override Future<NetworkIdentityRecord> create(NetworkProfile profile,String mode,Uint8List secret) async {
    validateNetworkIdentityInput(profile,mode,secret); creates++;
    record = NetworkIdentityRecord.checked(tailscaleIdentityReply(profile),profile);
    if (unknownWrite) throw const RemoteFailure('fixture_unknown'); return record!;
  }
  @override Future<void> delete(NetworkProfile profile,NetworkIdentityRecord identity) async {
    expect(identity.handle,record?.handle); deletes++; record = null;
    if (unknownWrite) throw const RemoteFailure('fixture_unknown');
  }
}

class PendingTailscaleIdentityFixture extends TailscaleIdentityFixture {
  final pending = <Completer<NetworkIdentityRecord?>>[];
  @override Future<NetworkIdentityRecord?> status(NetworkProfile profile) {
    reads++; final result = Completer<NetworkIdentityRecord?>(); pending.add(result); return result.future;
  }
}

class TailscaleRuntimeFixture extends NativeNetworkRuntime {
  TailscaleRuntimeFixture(this.profile) : binding = tailscaleBinding(profile);
  final NetworkProfile profile;
  final NetworkNodeBinding binding;
  final calls = <(String,Map<String,Object>)>[];
  String state = 'stopped',routeProvider = 'tailscale';
  bool failStop = false,bridgeAvailable = true;
  Object? statusReply;
  String? url,reviewToken;
  @override bool get supported => true;
  @override Future<Object?> call(String method,Map<String,Object> args) async {
    calls.add((method,args));
    switch (method) {
      case 'available': return {'available':bridgeAvailable,'reason':null};
      case 'nodeStatus': return statusReply ?? {'state':state,'binding':state == 'stopped' ? null : binding.toMap()};
      case 'nodeStart': state = 'needs-login'; return {'state':state,'binding':binding.toMap()};
      case 'nodeStop':
        if (failStop) throw const RemoteFailure('fixture_unknown_stop');
        state = 'stopped'; return {'state':state,'binding':null};
      case 'nodeLogin':
        url = 'https://login.example.test/device/fixture'; reviewToken = 'review-1';
        return {'state':state,'binding':binding.toMap(),'authUrl':url,'reviewToken':reviewToken};
      case 'nodeLoginStatus': return {'state':state,'binding':binding.toMap(),'authUrl':url,'reviewToken':reviewToken};
      case 'openLogin': return {'opened':true};
      case 'streamOpen': return {'streamId':'ts-fixture','route':{'provider':routeProvider,
        'profile_id':binding.profileId,'profile_revision':binding.profileRevision,'identity_ref':binding.identityRef}};
      case 'streamClose': return {'closed':true};
    }
    throw const RemoteFailure('unexpected_fixture_method');
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test('shared Tailscale settings vectors keep defaults and exact reviewed URL bytes',() async {
    final fixture = jsonDecode(await rootBundle.loadString('assets/shared/tailscale-settings-v1.json')) as Map;
    for (final value in fixture['vectors'] as List) {
      final profile = NetworkProfile.create('Synthetic tailnet','tailscale',{
        'controlUrl':value['controlUrl'],'hostname':value['hostname']});
      expect(tailscaleEffectiveSettings(profile),{'controlUrl':value['effectiveControlUrl'],'hostname':value['effectiveHostname']});
      expect(tailscaleNetworkName(profile),value['networkName']);
    }
    final a = NetworkProfile.create('A','tailscale',{'controlUrl':'https://control.example/path%20name','hostname':'Phone-2'});
    final b = NetworkProfile.create('B','tailscale',{'controlUrl':'https://control.example/path%20name/','hostname':'Phone-2'});
    expect(tailscaleNetworkName(a),isNot(tailscaleNetworkName(b)));
  });
  test('shared invalid Tailscale settings are rejected at both creation and catalog import',() async {
    final fixture = jsonDecode(await rootBundle.loadString('assets/shared/tailscale-settings-v1.json')) as Map;
    final template = testNetwork().toJson();
    for (final value in fixture['invalid'] as List) {
      final settings = <String,dynamic>{'controlUrl':value['controlUrl'],'hostname':value['hostname']};
      expect(() => NetworkProfile.create('Invalid tailnet','tailscale',settings),throwsA(isA<RemoteFailure>()),reason:value['name']?.toString());
      expect(() => NetworkProfile.fromJson({...template,'settings':settings}),throwsA(isA<RemoteFailure>()),reason:value['name']?.toString());
    }
  });
  test('control URL and DNS limits are checked before URI normalization without changing ET IPv6 peers',() {
    const prefix = 'https://control.example/';
    final boundary = prefix + 'a' * (2048-prefix.length);
    for (final url in [boundary,'https://control.example:1','https://control.example:65535/path%20name',
      'https://${'a'*63}.${'b'*63}.${'c'*63}.${'d'*61}']) {
      expect(NetworkProfile.create('Valid','tailscale',{'controlUrl':url,'hostname':'a'*63}).settings['controlUrl'],url);
    }
    for (final url in [boundary+'a','https://${'a'*64}.example','https://${'a'*63}.${'b'*63}.${'c'*63}.${'d'*62}',
      'https://control.example:','https://control.example:00','https://control.example:1:2',
      'https://control.example.','https://control_.example','https://control.example/%0','https://control.example/%gg']) {
      expect(() => NetworkProfile.create('Invalid','tailscale',{'controlUrl':url,'hostname':''}),throwsA(isA<RemoteFailure>()),reason:url);
    }
    expect(NetworkProfile.create('ET','easytier',{'networkName':'fixture','peers':['udp://[2001:db8::1]:11010']}).provider,'easytier');
  });
  test('TS binding is explicit and ET four-field format stays compatible',() {
    final profile = testNetwork(),binding = tailscaleBinding(profile);
    expect(binding.toMap()['provider'],'tailscale'); expect(binding.toMap().length,5);
    expect(NetworkNodeBinding.fromMap(binding.toMap()).same(binding),isTrue);
    const et = NetworkNodeBinding('0123456789abcdef0123456789abcdef',1,'fixture','a0000000-0000-4000-8000-000000000001');
    expect(et.toMap().length,4); expect(NetworkNodeBinding.fromMap(et.toMap()).provider,'easytier');
    expect(() => NetworkNodeBinding.fromMap({...binding.toMap()}..remove('provider')),throwsA(anything));
    expect(() => NetworkNodeBinding.fromMap({...binding.toMap(),'provider':'zerotier'}),throwsA(anything));
    expect(binding.same(NetworkNodeBinding(binding.profileId,binding.profileRevision,binding.networkName,binding.identityRef)),isFalse);
  });
  test('native TS identity create sends only profile/provider and never accepts secret modes',() async {
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    addTearDown(() { debugDefaultTargetPlatformOverride = null; });
    final profile = testNetwork(),calls = <String>[];
    final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(NativeNetworkIdentityStore.channel,(call) async {
      calls.add(call.method); final args = call.arguments as Map;
      expect(args['profileId'],profile.id); expect(args['provider'],'tailscale');
      expect(args.keys.toSet(),call.method == 'delete' ? {'profileId','provider','handle'} : {'profileId','provider'});
      if (call.method == 'delete') expect(args['handle'],tailscaleIdentityReply(profile)['handle']);
      return call.method == 'delete' ? null : tailscaleIdentityReply(profile);
    });
    addTearDown(() => messenger.setMockMethodCallHandler(NativeNetworkIdentityStore.channel,null));
    final store = NativeNetworkIdentityStore();
    for (final pair in <(String,Uint8List)>[('PRIVATE',Uint8List(0)),('DEVICE_STATE',Uint8List.fromList([65]))]) {
      await expectLater(store.create(profile,pair.$1,pair.$2),throwsA(anything));
    }
    expect(calls,isEmpty);
    final record = await store.create(profile,'DEVICE_STATE',Uint8List(0));
    expect(record.mode,'DEVICE_STATE'); await store.status(profile); await store.delete(profile,record);
    expect(calls,['create','status','delete']);
    expect(() => NetworkIdentityRecord.checked({...tailscaleIdentityReply(profile),'mode':'PRIVATE'},profile),throwsA(anything));
    final et = testNetwork('easytier');
    expect(() => NetworkIdentityRecord.checked({...tailscaleIdentityReply(et),'provider':'easytier'},et),throwsA(anything));
  });
  test('unknown TS identity mutation is followed only by reads and never replayed',() async {
    final profile = testNetwork(),store = TailscaleIdentityFixture()..unknownWrite = true;
    final session = NetworkIdentitySession(profile:profile,store:store,stillCurrent:() => true,closeAffected:() {});
    await session.refresh(); await session.create('DEVICE_STATE',Uint8List(0));
    expect(store.creates,1); expect(store.reads,2); expect(session.record,isNotNull); expect(session.notice,contains('未确认'));
    await session.refresh(); expect(store.creates,1); await session.delete();
    expect(store.deletes,1); expect(session.record,isNull); await session.refresh();
    expect(store.creates,1); expect(store.deletes,1); session.dispose();
  });
  test('identity status begun before background cannot become the app-return review',() async {
    final profile = testNetwork(),store = PendingTailscaleIdentityFixture();
    final session = NetworkIdentitySession(profile:profile,store:store,stillCurrent:() => true,closeAffected:() {});
    final old = session.refresh(); session.suspend(); await session.resume();
    expect(session.canCreate,isFalse); expect(session.canDelete,isFalse);
    store.pending.first.complete(NetworkIdentityRecord.checked(tailscaleIdentityReply(profile),profile)); await old;
    expect(store.pending.length,2); expect(session.record,isNull); expect(session.known,isFalse);
    store.pending.last.complete(null); await Future<void>.delayed(Duration.zero);
    expect(session.known,isTrue); expect(session.canCreate,isTrue); expect(session.canDelete,isFalse);
    expect(store.creates,0); expect(store.deletes,0); session.dispose();
  });
  test('TS starts with effective settings and cannot enter ET peers or ET login',() async {
    final profile = testNetwork(),runtime = TailscaleRuntimeFixture(profile),binding = tailscaleBinding(profile);
    await runtime.startTailscale(binding,profile);
    final args = runtime.calls.single.$2;
    expect(args.keys.toSet(),{'binding','settings'});
    expect(args['settings'],{'controlUrl':defaultTailscaleControlUrl,'hostname':defaultTailscaleHostname});
    await expectLater(runtime.start(binding,['tcp://fixture:22']),throwsA(anything));
    final et = NetworkNodeBinding(binding.profileId,binding.profileRevision,'fixture',binding.identityRef);
    await expectLater(runtime.login(et),throwsA(anything)); await expectLater(runtime.loginStatus(et),throwsA(anything));
    expect(runtime.calls.length,1);
  });
  test('only Running with exact TS identity freezes an SSH route; missing bridge and unreadable identity fail closed',() async {
    final profile = testNetwork(),runtime = TailscaleRuntimeFixture(profile);
    final identities = TailscaleIdentityFixture()..record = NetworkIdentityRecord.checked(tailscaleIdentityReply(profile),profile);
    for (final state in ['stopped','starting','needs-login','needs-machine-auth']) {
      runtime.state = state; await expectLater(runtime.freeze(profile,identities),throwsA(anything));
    }
    runtime.state = 'running'; expect((await runtime.freeze(profile,identities)).same(runtime.binding),isTrue);
    expect(runtime.calls.where((c) => c.$1 == 'available').every((c) => c.$2['provider'] == 'tailscale'),isTrue);
    expect(runtime.calls.where((c) => c.$1 == 'nodeStatus').every((c) => c.$2['provider'] == 'tailscale'),isTrue);
    identities.failRead = true; await expectLater(runtime.freeze(profile,identities),throwsA(anything)); identities.failRead = false;
    runtime.bridgeAvailable = false; await expectLater(runtime.freeze(profile,identities),throwsA(anything));
    expect(runtime.calls.where((c) => c.$1 == 'streamOpen'),isEmpty);
  });
  test('TS SSHSocket retains verified native route and rejects overlapping ET route',() async {
    final profile = testNetwork(),runtime = TailscaleRuntimeFixture(profile),binding = tailscaleBinding(profile);
    final socket = await runtime.open(binding,'100.64.0.1',22);
    final route = 'tailscale:${binding.profileId}:${binding.profileRevision}:${binding.identityRef}';
    expect(connectedSocketRoute(socket),route); expect(isValidOverlayRoute(route),isTrue);
    expect(isValidOverlayRoute(route.replaceFirst('tailscale:','easytier:')),isFalse);
    socket.destroy(); await Future<void>.delayed(Duration.zero);
    runtime.routeProvider = 'easy-tier';
    await expectLater(runtime.open(binding,'100.64.0.1',22),throwsA(anything));
    await Future<void>.delayed(Duration.zero);
    expect(runtime.calls.where((c) => c.$1 == 'streamClose').length,2);
  });
  test('overlapping TS and ET targets stay separate for input and recovery keys',() {
    final binding = tailscaleBinding(testNetwork());
    RemoteInputTarget target(String provider) => RemoteInputTarget(connection:Object(),generation:1,
      host:'100.64.0.1',port:22,username:'fixture',hostFingerprint:'SHA256:fixture',session:'fixture',
      socketPath:'/fixture.sock',paneId:'pane-1',terminalId:'terminal-1',
      route:'$provider:${binding.profileId}:${binding.profileRevision}:${binding.identityRef}');
    final ts = target('tailscale'),et = target('easy-tier');
    expect(ts.sameEndpoint(et),isFalse); expect(ts.endpointKey,isNot(et.endpointKey));
  });
  test('foreign provider status cannot clear an unknown TS stop',() async {
    final profile = testNetwork(),runtime = TailscaleRuntimeFixture(profile)..state = 'running'..failStop = true;
    final binding = runtime.binding;
    await expectLater(runtime.stop(binding),throwsA(anything));
    final et = NetworkNodeBinding(binding.profileId,binding.profileRevision,'fixture',binding.identityRef);
    runtime.statusReply = {'state':'stopped','binding':et.toMap()};
    await expectLater(runtime.profileStatus(profile),throwsA(anything)); expect(runtime.stopUncertain(profile.id),isTrue);
    runtime.statusReply = {'state':'stopped','binding':null}; await runtime.profileStatus(profile);
    expect(runtime.stopUncertain(profile.id),isFalse);
  });
  for (final deleting in [false,true]) {
    test('unknown TS node stop blocks guarded identity ${deleting ? 'delete' : 'create'} and catalog mutation',() async {
      final storage = MemoryCatalogStorage();
      final catalog = HostCatalog(storage:storage,clock:() => 1000);
      await catalog.load(); final profile = testNetwork(); await catalog.addNetwork(profile);
      final runtime = TailscaleRuntimeFixture(profile)..state = 'running'..failStop = true;
      final store = TailscaleIdentityFixture();
      if (deleting) store.record = NetworkIdentityRecord.checked(tailscaleIdentityReply(profile),profile);
      var closed = 0;
      final guarded = CatalogNetworkIdentityStore(catalog:catalog,profile:profile,expectedRevision:catalog.revision,
        closeAffected:() { closed++; },delegate:store,runtime:runtime);
      final revision = catalog.revision,writes = storage.writes;
      Future<void> mutate() async {
        if (deleting) { await guarded.delete(profile,store.record!); }
        else { await guarded.create(profile,'DEVICE_STATE',Uint8List(0)); }
      }
      await expectLater(mutate(),throwsA(anything)); await expectLater(mutate(),throwsA(anything));
      expect(runtime.calls.where((c) => c.$1 == 'nodeStop').length,1);
      expect(store.creates,0); expect(store.deletes,0); expect(closed,2); expect(catalog.revision,revision);
      expect(storage.writes,writes);
      await expectLater(runtime.freeze(profile,store),throwsA(anything));
      runtime.state = 'stopped'; await runtime.profileStatus(profile); expect(runtime.stopUncertain(profile.id),isFalse);
      catalog.dispose();
    });
  }
  test('login URL and transient token must be paired and attached to the exact provider binding',() async {
    final profile = testNetwork(),binding = tailscaleBinding(profile),runtime = TailscaleRuntimeFixture(profile)..state = 'needs-login';
    final valid = {'state':'needs-login','binding':binding.toMap(),'authUrl':'https://login.example.test/a?key=fixture','reviewToken':'review-1'};
    expect(NetworkLoginSnapshot.fromMap(valid,binding).authUrl,valid['authUrl']);
    for (final invalid in [
      {...valid,'reviewToken':null},{...valid,'authUrl':null},{...valid,'state':'running'},
      {...valid,'authUrl':'http://login.example.test/a'},{...valid,'authUrl':'https://user:pass@login.example.test/a'},
      {...valid,'authUrl':'https://login.example.test/a\n'},{...valid,'reviewToken':'bad token'},
      {...valid,'binding':{...binding.toMap(),'profileRevision':binding.profileRevision+1}},
    ]) { expect(() => NetworkLoginSnapshot.fromMap(invalid,binding),throwsA(anything)); }
    expect(NetworkLoginSnapshot.fromMap({...valid,'state':'needs-machine-auth'},binding).state,'needs-machine-auth');
    await runtime.openLogin(binding,valid['authUrl'] as String,'review-1');
    expect(runtime.calls.single.$2,{'binding':binding.toMap(),'url':valid['authUrl'],'reviewToken':'review-1'});
  });
  test('authorization URL accepts native 4096-byte boundary and rejects out-of-policy authority',() {
    final binding = tailscaleBinding(testNetwork()); const prefix = 'https://login.example.test/';
    for (final length in [2048,2049,4096]) {
      final url = prefix + 'a' * (length-prefix.length);
      expect(isValidTailscaleAuthUrl(url),isTrue);
      expect(NetworkLoginSnapshot.fromMap({'state':'needs-login','binding':binding.toMap(),
        'authUrl':url,'reviewToken':'review-1'},binding).authUrl,url);
    }
    for (final url in [prefix + 'a' * (4097-prefix.length),'https://[::1]/a','https://login..example.test/a',
      'https://-login.example.test/a','https://login.example.test:0/a','https://login.example.test:65536/a',
      'https://%6cogin.example.test/a','https://login.example.test/a#fragment','https://login.example.test/中']) {
      expect(isValidTailscaleAuthUrl(url),isFalse,reason:url);
    }
  });
}
