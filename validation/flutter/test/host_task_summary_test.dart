import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_task_summary.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'host_catalog_test.dart' show MemoryCatalogStorage,catalogPairing;
import 'network_profiles_test.dart' show testNetwork;
import 'remote_test_data.dart';

HostProfile summaryProfile(String label) {
  final profile=HostProfile.create(label,fixtureConfig(),catalogPairing(authorized:true),1000);
  return HostProfile.fromJson({...profile.toJson(),'pairing':{...profile.pairingRecord,'handle':'fixture-$label'}},1000);
}
RemoteDashboardSource summarySource(HostProfile profile,{String route='system',String? host,String? session,String? socketPath,String? fingerprint,String? herdrPath}) {
  final config = RemoteConfig.fromJson({...profile.target,'schemaVersion':1,'reviewConfirmed':true,'privateKeyPem':fixtureConfig()['privateKeyPem']});
  return RemoteDashboardSource(host:host ?? config.host,port:config.port,username:config.username,
    hostFingerprint:fingerprint ?? config.expectedFingerprint,session:session ?? config.session,socketPath:socketPath ?? config.socketPath,
    herdrPath:herdrPath ?? config.herdrPath,route:route);
}
RemoteDashboard summaryBoard(HostProfile profile,{int blocked=1,int revision=1,int generation=1,DashboardFreshness freshness=DashboardFreshness.fresh,
  RemoteDashboardSource? source,DateTime? at,bool empty=false}) => RemoteDashboard(generation,profile.target['session'] as String,
    empty ? const [] : [for (var i=0;i<blocked;i++) RemotePane('w1:p$i','term_abcd$i',agentStatus:'blocked'),const RemotePane('w1:p99','term_unknown',agentStatus:'unknown')],
    freshness:freshness,revision:revision,syncedAt:at ?? DateTime.utc(2026,11,7,10),source:source ?? summarySource(profile));

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  Future<HostCatalog> catalogWith(HostProfile profile) async {
    final catalog=HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load(); await catalog.add(profile); return catalog;
  }
  test('no report is unknown, validated empty is zero, and only current blocked owns priority',() async {
    final profile=summaryProfile('A'),catalog=await catalogWith(profile),summaries=HostTaskSummaries(catalog);
    expect(summaries.forHost(profile.id),isNull);
    final lease=summaries.open(profile),attempt=lease.begin()!;
    attempt.publish(summaryBoard(profile,empty:true));
    expect(summaries.forHost(profile.id)!.paneCount,0); expect(summaries.forHost(profile.id)!.blockedCount,0);
    expect(summaries.forHost(profile.id)!.label,contains('快照确认为空')); expect(summaries.forHost(profile.id)!.priority,isFalse);
    attempt.publish(summaryBoard(profile,blocked:2,revision:2)); final value=summaries.forHost(profile.id)!;
    expect(value.blockedCount,2); expect(value.paneCount,3); expect(value.priority,isTrue);
    expect(value.unknownCount,1); expect(value.label,contains('受阻至少 2 个＋1 个状态未知'));
    lease.invalidate(); expect(summaries.forHost(profile.id)!.priority,isFalse);
    expect(summaries.forHost(profile.id)!.blockedCount,2); expect(summaries.forHost(profile.id)!.syncedAt,value.syncedAt);
    summaries.dispose(); catalog.dispose();
  });
  test('blocked selection binds the exact report and rejects replaced, changed or retired targets',() async {
    final profile=summaryProfile('A'),catalog=await catalogWith(profile),summaries=HostTaskSummaries(catalog);
    final lease=summaries.open(profile),attempt=lease.begin()!;
    attempt.publish(summaryBoard(profile,blocked:2));
    final first=summaries.forHost(profile.id)!,pane=first.blockedPanes.first;
    expect(summaries.blockedTarget(profile.id,first,pane),isA<BlockedSummaryTarget>());
    expect(summaries.blockedTarget(profile.id,first,const RemotePane('w1:p99','term_unknown')),isNull);
    lease.invalidate();
    expect(summaries.blockedTarget(profile.id,first,pane),isNull);
    final stale=summaries.forHost(profile.id)!;
    expect(summaries.blockedTarget(profile.id,stale,pane),isA<BlockedSummaryTarget>());
    lease.begin()!.publish(summaryBoard(profile,blocked:0));
    expect(summaries.blockedTarget(profile.id,stale,pane),isNull);
    final refreshed=summaries.forHost(profile.id)!; expect(refreshed.blockedPanes,isEmpty);
    await catalog.update(profile.change(enabled:false,now:1000));
    expect(summaries.blockedTarget(profile.id,refreshed,pane),isNull);
    summaries.dispose(); catalog.dispose();
  });
  test('duplicate exact identities are never admitted as a blocked target',() async {
    final profile=summaryProfile('A'),catalog=await catalogWith(profile),summaries=HostTaskSummaries(catalog);
    final attempt=summaries.open(profile).begin()!;
    const pane=RemotePane('w1:p1','term_a',agentStatus:'blocked');
    attempt.publish(RemoteDashboard(1,'probe',const [pane,pane],freshness:DashboardFreshness.fresh,
      revision:1,source:summarySource(profile),syncedAt:DateTime.utc(2026,11,7)));
    final value=summaries.forHost(profile.id)!;
    expect(summaries.blockedTarget(profile.id,value,pane),isNull);
    summaries.dispose(); catalog.dispose();
  });
  test('missing provenance or snapshot time never turns unknown into zero',() async {
    final profile=summaryProfile('A'),catalog=await catalogWith(profile),summaries=HostTaskSummaries(catalog),attempt=summaries.open(profile).begin()!;
    attempt.publish(const RemoteDashboard(1,'probe',[],freshness:DashboardFreshness.fresh));
    attempt.publish(RemoteDashboard(1,'probe',const [],source:summarySource(profile),freshness:DashboardFreshness.fresh));
    expect(summaries.forHost(profile.id),isNull); summaries.dispose(); catalog.dispose();
  });
  test('duplicate labels replace one source snapshot instead of summing, and old sibling cannot stale new owner',() async {
    final profile=summaryProfile('A'),catalog=await catalogWith(profile),summaries=HostTaskSummaries(catalog);
    var firstVisible=true;
    final first=summaries.open(profile,visible:() => firstVisible),one=first.begin()!;
    one.publish(summaryBoard(profile,blocked:2)); firstVisible=false; first.invalidate();
    final second=summaries.open(profile),two=second.begin()!; two.publish(summaryBoard(profile,blocked:3));
    one.publish(summaryBoard(profile,blocked:99,revision:99)); first.close();
    expect(summaries.forHost(profile.id)!.blockedCount,3); expect(summaries.forHost(profile.id)!.current,isTrue);
    two.publish(summaryBoard(profile,blocked:9,revision:0)); expect(summaries.forHost(profile.id)!.blockedCount,3);
    summaries.dispose(); catalog.dispose();
  });
  test('starting a sibling attempt revokes prior owner before any replacement snapshot arrives',() async {
    final profile=summaryProfile('A'),catalog=await catalogWith(profile),summaries=HostTaskSummaries(catalog);
    final first=summaries.open(profile).begin()!; first.publish(summaryBoard(profile,blocked:2));
    summaries.open(profile).begin();
    first.publish(summaryBoard(profile,blocked:99,revision:9));
    expect(summaries.forHost(profile.id)!.blockedCount,2); expect(summaries.forHost(profile.id)!.current,isFalse);
    summaries.dispose(); catalog.dispose();
  });
  test('new sibling authoritative single snapshot replaces old owner without gaining priority',() async {
    final profile=summaryProfile('A'),catalog=await catalogWith(profile),summaries=HostTaskSummaries(catalog);
    final old=summaries.open(profile).begin()!; old.publish(summaryBoard(profile,blocked:2));
    final next=summaries.open(profile).begin()!;
    final at=DateTime.utc(2026,11,7,11); next.publish(summaryBoard(profile,blocked:1,freshness:DashboardFreshness.unavailable,at:at));
    old.publish(summaryBoard(profile,blocked:99,revision:99));
    expect(summaries.forHost(profile.id)!.blockedCount,1); expect(summaries.forHost(profile.id)!.syncedAt,at);
    expect(summaries.forHost(profile.id)!.label,contains('单次快照')); expect(summaries.forHost(profile.id)!.priority,isFalse);
    summaries.dispose(); catalog.dispose();
  });
  test('initial stale or refreshing notifications cannot manufacture an authoritative zero or count',() async {
    final profile=summaryProfile('A'),catalog=await catalogWith(profile),summaries=HostTaskSummaries(catalog),attempt=summaries.open(profile).begin()!;
    attempt.publish(summaryBoard(profile,blocked:2,freshness:DashboardFreshness.stale,revision:1));
    attempt.publish(summaryBoard(profile,empty:true,freshness:DashboardFreshness.refreshing,revision:2));
    expect(summaries.forHost(profile.id),isNull);
    attempt.publish(summaryBoard(profile,blocked:1,freshness:DashboardFreshness.unavailable,revision:3));
    expect(summaries.forHost(profile.id)!.blockedCount,1); summaries.dispose(); catalog.dispose();
  });
  test('stale and refreshing invalidations preserve exact previous count and snapshot time',() async {
    final profile=summaryProfile('A'),catalog=await catalogWith(profile),summaries=HostTaskSummaries(catalog),attempt=summaries.open(profile).begin()!;
    final at=DateTime.utc(2026,11,7,8); attempt.publish(summaryBoard(profile,blocked:2,at:at));
    attempt.publish(summaryBoard(profile,blocked:99,revision:2,at:DateTime.utc(2026,11,7,9),freshness:DashboardFreshness.refreshing));
    attempt.publish(summaryBoard(profile,blocked:99,revision:3,at:DateTime.utc(2026,11,7,10),freshness:DashboardFreshness.stale));
    expect(summaries.forHost(profile.id)!.blockedCount,2); expect(summaries.forHost(profile.id)!.syncedAt,at);
    expect(summaries.forHost(profile.id)!.priority,isFalse); summaries.dispose(); catalog.dispose();
  });
  test('all unknown statuses do not advertise an exact zero, unlike a validated all-known snapshot',() async {
    final profile=summaryProfile('A'),catalog=await catalogWith(profile),summaries=HostTaskSummaries(catalog),attempt=summaries.open(profile).begin()!;
    attempt.publish(summaryBoard(profile,blocked:0)); expect(summaries.forHost(profile.id)!.label,contains('受阻至少 0 个＋1 个状态未知'));
    attempt.publish(RemoteDashboard(1,'probe',const [RemotePane('w1:p1','term_abcd',agentStatus:'idle')],freshness:DashboardFreshness.fresh,
      revision:2,source:summarySource(profile),syncedAt:DateTime.utc(2026,11,7,10)));
    expect(summaries.forHost(profile.id)!.unknownCount,0); expect(summaries.forHost(profile.id)!.label,contains('受阻 0 个'));
    expect(summaries.forHost(profile.id)!.priority,isFalse); summaries.dispose(); catalog.dispose();
  });
  test('single authoritative snapshot keeps data and time but cannot get continuous-update priority',() async {
    final profile=summaryProfile('A'),catalog=await catalogWith(profile),summaries=HostTaskSummaries(catalog),attempt=summaries.open(profile).begin()!;
    final at=DateTime.utc(2026,11,7,9);
    attempt.publish(summaryBoard(profile,blocked:2,at:at,freshness:DashboardFreshness.unavailable));
    expect(summaries.forHost(profile.id)!.blockedCount,2); expect(summaries.forHost(profile.id)!.syncedAt,at);
    expect(summaries.forHost(profile.id)!.label,contains('持续更新不可用（单次快照）')); expect(summaries.forHost(profile.id)!.priority,isFalse);
    summaries.dispose(); catalog.dispose();
  });
  test('only current confirmed blocked rows gain stable priority; stale rows return to source order',() async {
    final a=summaryProfile('A'),b=summaryProfile('B'),catalog=await catalogWith(a); await catalog.add(b);
    final summaries=HostTaskSummaries(catalog),lease=summaries.open(b); lease.begin()!.publish(summaryBoard(b));
    expect(summaries.orderedHosts.map((p) => p.id),[b.id,a.id]); lease.invalidate();
    expect(summaries.orderedHosts.map((p) => p.id),[a.id,b.id]); summaries.dispose(); catalog.dispose();
  });
  test('host, endpoint, session, executable, fingerprint and actual route mismatches are refused',() async {
    final profile=summaryProfile('A'),catalog=await catalogWith(profile),summaries=HostTaskSummaries(catalog);
    for (final source in [summarySource(profile,host:'other.test'),summarySource(profile,session:'other'),
      summarySource(profile,socketPath:'/tmp/other.sock'),summarySource(profile,herdrPath:'/tmp/other-herdr'),
      summarySource(profile,fingerprint:'SHA256:wrong'),summarySource(profile,route:'tailscale:unproved')]) {
      final attempt=summaries.open(profile).begin()!; attempt.publish(summaryBoard(profile,source:source));
      expect(summaries.forHost(profile.id),isNull);
    }
    final original=summaryProfile('B'),other=HostProfile.fromJson({...original.toJson(),'target':{...original.target,'host':'other.test'}},1000); await catalog.add(other);
    summaries.open(other).begin()!.publish(summaryBoard(profile)); expect(summaries.forHost(other.id),isNull);
    summaries.dispose(); catalog.dispose();
  });
  test('background revokes old attempt even after resume; explicit new attempt is needed',() async {
    final profile=summaryProfile('A'),catalog=await catalogWith(profile),summaries=HostTaskSummaries(catalog),lease=summaries.open(profile),first=lease.begin()!;
    first.publish(summaryBoard(profile,blocked:2)); final at=summaries.forHost(profile.id)!.syncedAt;
    summaries.setForeground(false); first.publish(summaryBoard(profile,blocked:99,revision:3)); summaries.setForeground(true);
    first.publish(summaryBoard(profile,blocked:99,revision:4)); expect(summaries.forHost(profile.id)!.blockedCount,2);
    expect(summaries.forHost(profile.id)!.current,isFalse); expect(summaries.forHost(profile.id)!.syncedAt,at);
    lease.begin()!.publish(summaryBoard(profile,blocked:1)); expect(summaries.forHost(profile.id)!.priority,isTrue);
    summaries.dispose(); catalog.dispose();
  });
  test('new page lease and deleted/recreated row reject original callbacks',() async {
    final profile=summaryProfile('A'),catalog=await catalogWith(profile),summaries=HostTaskSummaries(catalog),lease=summaries.open(profile),old=lease.begin()!;
    old.publish(summaryBoard(profile,blocked:2)); lease.close();
    final next=summaries.open(profile).begin()!; next.publish(summaryBoard(profile,blocked:1));
    old.publish(summaryBoard(profile,blocked:99,revision:9)); expect(summaries.forHost(profile.id)!.blockedCount,1);
    await catalog.remove(profile.id); await catalog.add(profile);
    expect(summaries.forHost(profile.id),isNull); next.publish(summaryBoard(profile,blocked:99,revision:9));
    expect(summaries.forHost(profile.id),isNull); summaries.dispose(); catalog.dispose();
  });
  test('rename retains valid source but disabling or changing configured route removes it',() async {
    final profile=summaryProfile('A'),catalog=await catalogWith(profile),summaries=HostTaskSummaries(catalog);
    summaries.open(profile).begin()!.publish(summaryBoard(profile));
    final renamed=profile.change(label:'Renamed',now:1000); await catalog.update(renamed);
    expect(summaries.forHost(profile.id)!.current,isTrue);
    final network=testNetwork('tailscale'); await catalog.addNetwork(network);
    await catalog.update(renamed.change(networkProfileId:network.id,replaceNetwork:true,now:1000));
    expect(summaries.forHost(profile.id),isNull); summaries.dispose(); catalog.dispose();
  });
  test('actual overlay identity cannot change inside one attempt or blend routes',() async {
    var profile=summaryProfile('A'); final catalog=await catalogWith(profile),network=testNetwork('tailscale'); await catalog.addNetwork(network);
    await catalog.update(profile.change(networkProfileId:network.id,replaceNetwork:true,now:1000)); profile=catalog.profiles.single;
    final summaries=HostTaskSummaries(catalog),lease=summaries.open(profile),attempt=lease.begin()!;
    final route='tailscale:${network.id}:${network.revision}:a0000000-0000-4000-8000-000000000001';
    attempt.publish(summaryBoard(profile,source:summarySource(profile,route:route),blocked:2));
    final changed=route.replaceFirst('a0000000','b0000000');
    attempt.publish(summaryBoard(profile,source:summarySource(profile,route:changed),blocked:9,revision:2));
    expect(summaries.forHost(profile.id)!.blockedCount,2); expect(summaries.forHost(profile.id)!.current,isFalse);
    lease.begin()!.publish(summaryBoard(profile,source:summarySource(profile,route:changed),blocked:1));
    expect(summaries.forHost(profile.id)!.blockedCount,1); expect(summaries.forHost(profile.id)!.source.route,changed);
    summaries.dispose(); catalog.dispose();
  });
}
