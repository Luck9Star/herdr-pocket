import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/config_transfer.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'config_transfer_test.dart' show unhex,portable,UnknownCommitStorage;
import 'host_catalog_test.dart' show MemoryCatalogStorage;
import 'network_profiles_test.dart' show testNetwork;

Future<Map<String,dynamic>> v2Golden() async => jsonDecode(await rootBundle.loadString('assets/shared/config-transfer-v2.json')) as Map<String,dynamic>;
Uint8List clear(String text) => Uint8List.fromList(utf8.encode(text));
PortableConfig v2Config({bool host=true,bool preferences=true}) => PortableConfig.fromJson({'version':2,
  'hosts':host ? [{...portable().toJson(),'networkKey':'mesh'}] : [],
  'networks':[{'key':'mesh','label':'Public mesh','provider':'easytier','settings':testNetwork('easytier').settings}],
  'preferences':preferences ? {'terminalFontSize':18} : null});
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test('independent v2 golden deterministically encrypts and decrypts using unchanged v1 envelope',() async {
    final fixture = await v2Golden(),archive = unhex(fixture['archiveHex'] as String);
    final bytes = clear(fixture['plaintext'] as String),password = fixture['password'] as String;
    expect(encryptTransferWithMaterial(password,bytes,unhex(fixture['saltHex'] as String),unhex(fixture['nonceHex'] as String)),archive);
    final config = await decryptPortableConfig(password,archive);
    expect(config.version,2); expect(utf8.decode(encodePortableConfig(config)),fixture['plaintext']);
    final tampered = Uint8List.fromList(archive); tampered[34] ^= 1;
    await expectLater(decryptPortableConfig(password,tampered),throwsA(isA<TransferFailure>()));
  },timeout:const Timeout(Duration(minutes:4)));
  test('shared v2 valid and malformed plaintexts enforce exact keys, references, duplicate rejection and preferences bounds',() async {
    final fixture = await v2Golden();
    for (final entry in fixture['validPlaintexts'] as List) {
      expect(decodePortableConfig(clear((entry as Map)['plaintext'] as String)).version,2,reason:entry['name'] as String);
    }
    for (final entry in fixture['invalidPlaintexts'] as List) {
      expect(() => decodePortableConfig(clear((entry as Map)['plaintext'] as String)),throwsA(isA<TransferFailure>()),reason:entry['name'] as String);
    }
  });
  test('v2 imports only applied dependencies or explicitly selected networks, fresh disabled IDs and opt-in preferences in one CAS',() async {
    final storage = MemoryCatalogStorage();
    final active = HostCatalog(storage:storage,clock:() => 1000); await active.load();
    final config = v2Config(),plan = active.previewConfigImport(config),writes = storage.writes;
    await active.applyConfigImport(plan,[const ConfigImportChoice(ConfigImportAction.add)]);
    expect(storage.writes,writes+1); expect(active.networkProfiles.single.enabled,isFalse);
    expect(active.networkProfiles.single.revision,1); expect(active.profiles.single.networkProfileId,active.networkProfiles.single.id);
    expect(active.profiles.single.hasIdentity,isFalse); expect(active.terminalFontSize,14);
    final keep = active.previewConfigImport(config),oldBinding = active.profiles.single.networkProfileId;
    await active.applyConfigImport(keep,[const ConfigImportChoice(ConfigImportAction.keep)],applyPreferences:true);
    expect(active.networkProfiles.length,1); expect(active.profiles.single.networkProfileId,oldBinding); expect(active.terminalFontSize,18);
    final extra = active.previewConfigImport(v2Config(host:false,preferences:false));
    await active.applyConfigImport(extra,[],selectedNetworks:{'mesh'});
    expect(active.networkProfiles.length,2); expect(active.networkProfiles.map((n) => n.id).toSet().length,2);
    expect(active.networkProfiles.every((n) => !n.enabled && n.revision == 1),isTrue);
    final reopened = HostCatalog(storage:storage,clock:() => 1000); await reopened.load();
    expect(reopened.ready,isTrue); expect(reopened.terminalFontSize,18); expect(reopened.networkProfiles.length,2);
    active.dispose(); reopened.dispose();
  });
  test('v2 export auto-includes dependency, supports network-only and preference-only, and never exports local identity/status',() async {
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final network = testNetwork('easytier'); await catalog.addNetwork(network);
    final imported = HostProfile.imported(portable(),1000,networkProfileId:network.id); await catalog.add(imported);
    final config = catalog.exportConfig({imported.id},{},includePreferences:true),text = utf8.decode(encodePortableConfig(config));
    expect(config.hosts.single.networkKey,config.networks.single.key); expect(config.networks.single.provider,'easytier');
    for (final field in ['id','revision','enabled','pairing','handle','privateKeyPem','request_id','paneId']) {
      expect(text.contains('"$field"'),isFalse,reason:field);
    }
    expect(catalog.exportConfig({}, {network.id}).hosts,isEmpty);
    expect(catalog.exportConfig({}, {},includePreferences:true).terminalFontSize,14);
    expect(() => catalog.exportConfig({}, {}),throwsA(isA<TransferFailure>())); catalog.dispose();
  });
  test('network capacity failure rejects the entire v2 plan before view revocation or storage writes',() async {
    final storage = MemoryCatalogStorage();
    final catalog = HostCatalog(storage:storage,clock:() => 1000); await catalog.load();
    for (var i = 0; i < 32; i++) { await catalog.addNetwork(testNetwork()); }
    final plan = catalog.previewConfigImport(v2Config()),writes = storage.writes; var revoked = false;
    expect(() => catalog.applyConfigImport(plan,[const ConfigImportChoice(ConfigImportAction.add)],applyPreferences:true,
      beforeCommit:(_) { revoked = true; }),throwsA(isA<RemoteFailure>().having((e) => e.code,'code','catalog_limit')));
    expect(revoked,isFalse); expect(storage.writes,writes); expect(catalog.networkProfiles.length,32);
    expect(catalog.profiles,isEmpty); expect(catalog.terminalFontSize,14); expect(catalog.ready,isTrue); catalog.dispose();
  });
  test('unknown v2 save never publishes partial host, network or preferences and cannot be replayed',() async {
    final storage = UnknownCommitStorage();
    final active = HostCatalog(storage:storage,clock:() => 1000); await active.load();
    final plan = active.previewConfigImport(v2Config()); storage.loseReply = true;
    await expectLater(active.applyConfigImport(plan,[const ConfigImportChoice(ConfigImportAction.add)],applyPreferences:true),throwsA(isA<RemoteFailure>()));
    expect(active.ready,isFalse); expect(active.profiles,isEmpty); expect(active.networkProfiles,isEmpty); expect(active.terminalFontSize,14);
    final written = jsonDecode(storage.contents) as Map;
    expect((written['profiles'] as List).length,1); expect((written['networkProfiles'] as List).length,1);
    expect((written['preferences'] as Map)['terminalFontSize'],18); final writes = storage.writes;
    expect(() => active.applyConfigImport(plan,[const ConfigImportChoice(ConfigImportAction.add)],applyPreferences:true),throwsA(isA<RemoteFailure>()));
    expect(storage.writes,writes);
    final reopened = HostCatalog(storage:storage,clock:() => 1000); await reopened.load();
    expect(reopened.ready,isTrue); expect(reopened.profiles.single.networkProfileId,reopened.networkProfiles.single.id);
    expect(reopened.networkProfiles.single.enabled,isFalse); expect(reopened.terminalFontSize,18);
    active.dispose(); reopened.dispose();
  });
  test('network-only and preference-only apply remains atomic; stale and unknown commits cannot replay',() async {
    final storage = UnknownCommitStorage();
    final active = HostCatalog(storage:storage,clock:() => 1000); await active.load();
    final prefs = PortableConfig.fromJson({'version':2,'hosts':[],'networks':[],'preferences':{'terminalFontSize':22}});
    final plan = active.previewConfigImport(prefs); await active.updateTerminalFontSize(16); var revoked = false;
    expect(() => active.applyConfigImport(plan,[],applyPreferences:true,beforeCommit:(_) { revoked = true; }),throwsA(isA<RemoteFailure>()));
    expect(revoked,isFalse); expect(active.terminalFontSize,16);
    final current = active.previewConfigImport(prefs); storage.loseReply = true; final writes = storage.writes;
    await expectLater(active.applyConfigImport(current,[],applyPreferences:true),throwsA(isA<RemoteFailure>()));
    expect(active.ready,isFalse); expect(active.terminalFontSize,16); expect(storage.writes,writes+1);
    expect(() => active.applyConfigImport(current,[],applyPreferences:true),throwsA(isA<RemoteFailure>()));
    expect(storage.writes,writes+1); active.dispose();
  });
}
