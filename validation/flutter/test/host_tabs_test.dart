import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_tabs.dart';
import 'host_catalog_test.dart' show catalogPairing,MemoryCatalogStorage;
import 'remote_test_data.dart';

void main() {
  HostProfile profile(String name,String provider) => HostProfile.create(name,fixtureConfig(),catalogPairing(authorized:true),1000,provider:provider);
  test('select hides old lease first; tabs own navigators and never activate a sibling on close',() {
    final first = profile('A','tailscale'), second = profile('B','easytier'), tabs = HostTabs();
    tabs.open(first); final a = tabs.active!; final events = <String>[];
    a.visible.addListener(() => events.add('A:${a.visible.value}'));
    tabs.open(second); final b = tabs.active!; b.visible.addListener(() => events.add('B:${b.visible.value}'));
    expect(a.visible.value,isFalse); expect(b.visible.value,isTrue); expect(identical(a.navigator,b.navigator),isFalse);
    events.clear(); tabs.select(a.id); expect(events,['B:false','A:true']);
    expect(tabs.tabs.length,2); expect(tabs.active!.provider,'tailscale');
    tabs.close(a.id); expect(tabs.active,isNull); expect(b.visible.value,isFalse); tabs.dispose();
  });
  test('MT01 MT06 same host has independent views; disabling it closes only its views',() {
    final p = profile('A','zerotier'), tabs = HostTabs(); tabs.open(p); final old = tabs.active;
    tabs.select(null); tabs.open(p); expect(identical(tabs.active,old),isFalse); expect(tabs.tabs.length,2);
    expect(tabs.active!.hostId,p.id); expect(tabs.active!.id,isNot(old!.id));
    final sibling = profile('B','easytier'); tabs.open(sibling); final siblingId = tabs.active!.id;
    tabs.reconcile([p.change(label:'Renamed',now:1000),sibling]); expect(tabs.forHost(p.id).every((t) => t.label == 'Renamed'),isTrue);
    tabs.reconcile([p.change(enabled:false,now:1000),sibling]); expect(tabs.tabs.length,1); expect(tabs.active!.id,siblingId); tabs.dispose();
  });
  test('MT06 view connection-status updates keep sibling tabs, but revoked authority closes them',() {
    final a = profile('A','tailscale'),b = profile('B','easytier'),tabs = HostTabs();
    tabs.open(a); tabs.open(a); tabs.open(b); final other = tabs.active!.id;
    final connected = a.restore(1000)..state = 'waiting-connectivity';
    final statusOnly = a.change(pairing:connected,now:1000);
    tabs.reconcile([statusOnly,b]); expect(tabs.forHost(a.id).length,2); expect(tabs.active!.id,other);
    final revoked = statusOnly.restore(1000)..authorization = 'revoked'..state = 'revoked'..consumed = true;
    tabs.reconcile([statusOnly.change(pairing:revoked,now:1000),b]);
    expect(tabs.forHost(a.id),isEmpty); expect(tabs.active!.id,other);
    tabs.dispose();
  });
  test('configured provider is an enum and old catalog v1 migrates to unknown network',() async {
    final p = profile('A','tailscale'); expect(p.toJson()['provider'],'tailscale');
    expect(() => p.change(provider:'connected',now:1000),throwsA(isA<Exception>()));
    final old = {...p.toJson()}..remove('provider');
    final storage = MemoryCatalogStorage()..contents = jsonEncode({'schemaVersion':1,'profiles':[old],'pendingCreation':null})..revision = List.filled(64,'a').join();
    final restored = HostCatalog(storage:storage,clock:() => 1000); await restored.load();
    expect(restored.ready,isTrue); expect(restored.profiles.single.provider,'unspecified'); expect(storage.writes,0); restored.dispose();
  });
  test('eight view limit and host-scoped close preserve other hosts',() {
    final a = profile('A','tailscale'),b = profile('B','easytier'),tabs = HostTabs();
    for (var i = 0; i < 7; i++) { expect(tabs.open(a),isTrue); }
    expect(tabs.open(b),isTrue); final bId = tabs.active!.id;
    expect(tabs.open(a),isFalse); expect(tabs.tabs.length,8);
    final ids = tabs.forHost(a.id).map((t) => t.id).toSet(); expect(ids.length,7);
    tabs.closeHost(a.id); expect(tabs.tabs.single.id,bId); expect(tabs.active!.id,bId);
    expect(tabs.open(a),isTrue); expect(ids.contains(tabs.active!.id),isFalse);
    tabs.dispose();
  });
}
