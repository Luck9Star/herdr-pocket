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
    events.clear(); tabs.select(first.id); expect(events,['B:false','A:true']);
    expect(tabs.tabs.length,2); expect(tabs.active!.provider,'tailscale');
    tabs.close(first.id); expect(tabs.active,isNull); expect(b.visible.value,isFalse); tabs.dispose();
  });
  test('same profile reuses its tab; disable/delete or changed binding closes it',() {
    final p = profile('A','zerotier'), tabs = HostTabs(); tabs.open(p); final old = tabs.active;
    tabs.select(null); tabs.open(p); expect(identical(tabs.active,old),isTrue); expect(tabs.tabs.length,1);
    tabs.reconcile([p.change(label:'Renamed',now:1000)]); expect(tabs.active!.label,'Renamed');
    tabs.reconcile([p.change(enabled:false,now:1000)]); expect(tabs.tabs,isEmpty); expect(tabs.active,isNull); tabs.dispose();
  });
  test('configured provider is an enum and old catalog v1 migrates to unknown network',() async {
    final p = profile('A','tailscale'); expect(p.toJson()['provider'],'tailscale');
    expect(() => p.change(provider:'connected',now:1000),throwsA(isA<Exception>()));
    final old = {...p.toJson()}..remove('provider');
    final storage = MemoryCatalogStorage()..contents = jsonEncode({'schemaVersion':1,'profiles':[old],'pendingCreation':null})..revision = List.filled(64,'a').join();
    final restored = HostCatalog(storage:storage,clock:() => 1000); await restored.load();
    expect(restored.ready,isTrue); expect(restored.profiles.single.provider,'unspecified'); expect(storage.writes,0); restored.dispose();
  });
}
