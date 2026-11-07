import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/config_transfer.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_tabs.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'host_catalog_test.dart' show MemoryCatalogStorage,catalogPairing;
import 'network_profiles_test.dart' show testNetwork;
import 'remote_test_data.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test('pending QR overlay survives restart; wrong or missing binding fails before write',() async {
    final disk = MemoryCatalogStorage(), catalog = HostCatalog(storage:disk,clock:() => 1000); await catalog.load();
    final profile = HostProfile.create('QR',fixtureConfig(),catalogPairing(),1000,provider:'tailscale',requiresNetworkBinding:true);
    await catalog.add(profile);
    final reopened = HostCatalog(storage:disk,clock:() => 1000); await reopened.load();
    var current = reopened.profiles.single;
    expect(current.requiresNetworkBinding,isTrue);
    expect(() => reopened.freezeNetwork(current),throwsA(isA<RemoteFailure>()));
    final tabs = HostTabs(); expect(tabs.open(current),isFalse);
    expect(() => current.change(provider:'direct',now:1000),throwsA(isA<RemoteFailure>()));
    expect(() => current.change(networkProfileId:null,replaceNetwork:true,now:1000),throwsA(isA<RemoteFailure>()));
    final wrong = testNetwork('easytier'), right = testNetwork('tailscale');
    await reopened.addNetwork(wrong); await reopened.addNetwork(right);
    final writes = disk.writes;
    await expectLater(reopened.update(current.change(networkProfileId:wrong.id,replaceNetwork:true,now:1000)),throwsA(isA<RemoteFailure>()));
    expect(disk.writes,writes); expect(reopened.profiles.single.requiresNetworkBinding,isTrue);
    current = reopened.profiles.single;
    await reopened.update(current.change(networkProfileId:right.id,replaceNetwork:true,now:1000));
    current = reopened.profiles.single;
    expect(current.requiresNetworkBinding,isFalse); expect(current.networkProfileId,right.id);
    expect(tabs.open(current,networks:reopened.networkProfiles),isTrue);
    await reopened.update(current.change(networkProfileId:null,replaceNetwork:true,now:1000));
    expect(reopened.profiles.single.requiresNetworkBinding,isFalse);
    expect(reopened.freezeNetwork(reopened.profiles.single).profile,isNull);
    tabs.dispose(); catalog.dispose(); reopened.dispose();
  });
  test('v2 export and import preserve guard; v1 downgrade rejected and old records unchanged',() async {
    final disk = MemoryCatalogStorage(), catalog = HostCatalog(storage:disk,clock:() => 1000); await catalog.load();
    final profile = HostProfile.create('QR',fixtureConfig(),catalogPairing(),1000,provider:'zerotier',requiresNetworkBinding:true);
    await catalog.add(profile);
    final config = catalog.exportConfig({profile.id},{});
    expect(config.toJson()['hosts'].single['requiresNetworkBinding'],isTrue);
    expect(() => encodePortableHosts(config.hosts),throwsA(isA<TransferFailure>()));
    final other = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await other.load();
    final plan = other.previewConfigImport(config);
    await other.applyConfigImport(plan,[const ConfigImportChoice(ConfigImportAction.add)]);
    expect(other.profiles.single.requiresNetworkBinding,isTrue);
    expect(() => other.freezeNetwork(other.profiles.single),throwsA(isA<RemoteFailure>()));
    final legacy = HostProfile.create('Legacy',fixtureConfig(),catalogPairing(),1000,provider:'tailscale');
    expect(legacy.toJson().containsKey('requiresNetworkBinding'),isFalse);
    expect(HostProfile.fromJson(legacy.toJson(),1000).requiresNetworkBinding,isFalse);
    final entry = Map<String,dynamic>.from(config.toJson()['hosts'].single as Map);
    for (final invalid in [{...entry,'provider':'direct'},{...entry,'networkKey':'mesh'},{...entry,'requiresNetworkBinding':'true'}]) {
      expect(() => PortableHost.fromJson(invalid,version:2),throwsA(isA<TransferFailure>()));
    }
    catalog.dispose(); other.dispose();
  });
}
