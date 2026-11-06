import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/config_transfer.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'host_catalog_test.dart' show MemoryCatalogStorage,saveCatalogProfile,catalogPairing;
import 'remote_test_data.dart';

Map<String,dynamic> transferGolden() {
  final asset = File('assets/shared/config-transfer-v1.json');
  return jsonDecode((asset.existsSync() ? asset : File('../shared/config-transfer-v1.json')).readAsStringSync()) as Map<String,dynamic>;
}
Uint8List unhex(String value) => Uint8List.fromList([for (var i = 0; i < value.length; i += 2) int.parse(value.substring(i,i+2),radix:16)]);
PortableHost portable({String label='Imported host',String host='fixture.invalid'}) => PortableHost.fromJson({
  'label':label,'provider':'easytier','target':{for (final key in transferTargetFields) key: key == 'host' ? host : fixtureConfig()[key]}});

class UnknownCommitStorage extends MemoryCatalogStorage {
  bool loseReply = false;
  @override Future<String> save(String expected,String contents) async {
    final revision = await super.save(expected,contents);
    if (loseReply) throw const RemoteFailure('catalog_write_unknown');
    return revision;
  }
}

void main() {
  test('fixed independent golden encrypts identically and decrypts with unchanged Unicode password', () async {
    final fixture = transferGolden(), password = fixture['password'] as String;
    final plaintext = Uint8List.fromList(utf8.encode(fixture['plaintext'] as String));
    final archive = unhex(fixture['archiveHex'] as String);
    expect(encryptTransferWithMaterial(password,plaintext,unhex(fixture['saltHex'] as String),unhex(fixture['nonceHex'] as String)),archive);
    final hosts = await decryptConfigTransfer(password,archive);
    expect(utf8.decode(encodePortableHosts(hosts)),fixture['plaintext']);
    final tampered = Uint8List.fromList(archive); tampered[34] ^= 1;
    await expectLater(decryptConfigTransfer(password,tampered),throwsA(isA<TransferFailure>()));
    await expectLater(decryptConfigTransfer('$password ',archive),throwsA(isA<TransferFailure>()));
  },timeout:const Timeout(Duration(minutes:4)));
  test('fresh export uses new salt/nonce; short legacy import works without weakening new password rules', () async {
    final fixture = transferGolden(), plaintext = Uint8List.fromList(utf8.encode(fixture['plaintext'] as String));
    final hosts = decodePortableHosts(plaintext), password = 'a secure 🔐 passphrase';
    final first = await encryptConfigTransfer(password,hosts), second = await encryptConfigTransfer(password,hosts);
    expect(first.sublist(6,34),isNot(second.sublist(6,34)));
    expect((await decryptConfigTransfer(password,first)).single.label,hosts.single.label);
    final legacy = encryptTransferWithMaterial('短',plaintext,unhex(fixture['saltHex'] as String),unhex(fixture['nonceHex'] as String),enforceNewPassword:false);
    expect((await decryptConfigTransfer('短',legacy)).single.provider,'easytier');
    expect(() => encryptConfigTransfer('12345678901',hosts),throwsA(isA<TransferFailure>()));
  },timeout:const Timeout(Duration(minutes:4)));
  test('invalid size/version/schema/duplicate decoded fields reject before expensive crypto or catalog writes', () {
    for (final archive in [Uint8List(50),Uint8List(maxTransferArchive+1),Uint8List.fromList([72,80,75,84,2,1,...List.filled(45,0)])]) {
      expect(() => validateTransferEnvelope(archive),throwsA(isA<TransferFailure>()));
    }
    final valid = {'version':1,'hosts':[portable().toJson()]};
    for (final raw in [jsonEncode({...valid,'privateKeyPem':'secret'}),
      jsonEncode(valid).replaceFirst('{','{"version":1,'),
      jsonEncode(valid).replaceFirst('"host":','"host":"x","\\u0068ost":'),
      jsonEncode({'version':1,'hosts':[]}),
      jsonEncode({'version':1,'hosts':[{...portable().toJson(),'pairing':{}}]}),
      jsonEncode({'version':1,'hosts':[{...portable().toJson(),'target':{...portable().target,'paneId':''}}]}),
    ]) { expect(() => decodePortableHosts(Uint8List.fromList(utf8.encode(raw))),throwsA(isA<TransferFailure>())); }
    for (final host in ['[::1]','bad_host','-start.invalid','end-.invalid','a..b','${'a'*64}.invalid',
      '1:2:3:4:5:6:7:8:9','1:2:3:4:5:6:7::8','::ffff:192.168.01.2','::1%zone','1::2::3','192.0.2.1::']) {
      expect(() => portable(host:host),throwsA(isA<TransferFailure>()),reason:host);
    }
    for (final host in ['localhost','example-1.invalid','127.0.0.1','::','::1','2001:DB8::1','::ffff:192.0.2.1','1:2:3:4:5:6:7:8']) {
      expect(portable(host:host).target['host'],host);
    }
  });
  test('replacing paired conflicts is one CAS; original identity retires and new ID has no pairing', () async {
    final disk = MemoryCatalogStorage();
    final active = HostCatalog(storage:disk,clock:() => 1000); await active.load();
    final old = await saveCatalogProfile(active), writes = disk.writes;
    final host = portable(label:old.label,host:'replacement.invalid');
    final plan = active.previewImport([host]); expect(plan.conflicts.single.single.id,old.id);
    var revoked = 0;
    await active.applyImport(plan,[const ConfigImportChoice(ConfigImportAction.replace)],beforeCommit:(ids) {
      revoked++; expect(ids,{old.id}); expect(disk.writes,writes);
    });
    expect(revoked,1);
    expect(disk.writes,writes+1); expect(active.profiles.length,2);
    final retained = active.profiles.singleWhere((p) => p.id == old.id);
    expect(retained.retired,isTrue); expect(retained.enabled,isFalse);
    expect(retained.target,old.target); expect(retained.pairingRecord,old.pairingRecord);
    final imported = active.profiles.singleWhere((p) => p.id != old.id);
    expect(imported.hasIdentity,isFalse); expect(imported.toJson()['pairing'],isNull);
    expect(imported.target['host'],'replacement.invalid');
    expect(() => retained.change(enabled:true,now:1000),throwsA(isA<RemoteFailure>()));
    final exported = active.exportProfiles({imported.id});
    final json = utf8.decode(encodePortableHosts(exported));
    for (final field in ['pairing','handle','public_key','request_id','paneId','enabled','retired','privateKeyPem']) { expect(json.contains('"$field"'),isFalse); }
    final reopened = HostCatalog(storage:disk,clock:() => 1001); await reopened.load();
    expect(reopened.ready,isTrue); expect(reopened.profiles.where((p) => p.retired).length,1);
    active.dispose(); reopened.dispose();
  });
  test('stale preview and pending creation cannot overwrite metadata, identities or resume an operation', () async {
    final disk = MemoryCatalogStorage();
    final catalog = HostCatalog(storage:disk,clock:() => 1000); await catalog.load();
    final old = await saveCatalogProfile(catalog), preview = catalog.previewImport([portable(label:'new')]);
    await catalog.update(old.change(label:'Changed after preview',now:1000)); final writes = disk.writes;
    expect(() => catalog.applyImport(preview,[const ConfigImportChoice(ConfigImportAction.add)]),throwsA(isA<RemoteFailure>()));
    expect(disk.writes,writes);
    final plan = catalog.previewImport([portable(label:'new')]);
    final creation = catalog.beginCreation(fixtureConfig(),'Pending explicit pairing');
    final importing = catalog.applyImport(plan,[const ConfigImportChoice(ConfigImportAction.add)]);
    final rejected = expectLater(importing,throwsA(isA<RemoteFailure>()));
    await creation; await rejected;
    expect(catalog.pendingCreation,isNotNull); expect(catalog.profiles.length,1); expect(disk.writes,writes+1);
    expect(catalog.ready,isTrue); // Queue-time preflight failure never began a save.
    catalog.dispose();
  });
  test('imported host begins ordinary explicit pairing with a durable intent; keep creates no identity', () async {
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final plan = catalog.previewImport([portable()]);
    await catalog.applyImport(plan,[const ConfigImportChoice(ConfigImportAction.add)]);
    final imported = catalog.profiles.single;
    await catalog.beginCreation(imported.target,imported.label,sourceProfileId:imported.id);
    expect(catalog.pendingCreation!['sourceProfileId'],imported.id);
    // Fixtures create no system identity; full device creation is exercised by
    // the ordinary PairingPage widget test with its explicit test key provider.
    await catalog.clearUnstartedCreation(catalog.pendingCreation!['id'] as String);
    final keep = catalog.previewImport([portable()]);
    await catalog.applyImport(keep,[const ConfigImportChoice(ConfigImportAction.keep)]);
    expect(catalog.profiles.single.id,imported.id); expect(catalog.profiles.single.hasIdentity,isFalse);
    catalog.dispose();
  });
  test('legacy v1/v2 catalogs migrate on explicit write while preserving original binding', () async {
    for (final version in [1,2]) {
      final disk = MemoryCatalogStorage(), first = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000);
      await first.load(); final profile = await saveCatalogProfile(first);
      final legacy = {...profile.toJson()}..remove('retired'); if (version == 1) legacy.remove('provider');
      disk.contents = jsonEncode({'schemaVersion':version,'profiles':[legacy],'pendingCreation':null}); disk.revision = 'a'*64;
      final catalog = HostCatalog(storage:disk,clock:() => 1000); await catalog.load();
      expect(catalog.ready,isTrue); expect(catalog.profiles.single.id,profile.id); expect(disk.writes,0);
      final plan = catalog.previewImport([portable()]); await catalog.applyImport(plan,[const ConfigImportChoice(ConfigImportAction.keep)]);
      final migrated = jsonDecode(disk.contents) as Map;
      expect(migrated['schemaVersion'],4);
      expect(migrated['networkProfiles'],isEmpty);
      expect(migrated['preferences'],{'terminalFontSize':14});
      expect(catalog.profiles.single.pairingRecord['handle'],profile.pairingRecord['handle']);
      catalog.dispose(); first.dispose();
    }
  });
  test('a committed import with lost reply locks further writes; reload reveals result without replay', () async {
    final disk = UnknownCommitStorage();
    final active = HostCatalog(storage:disk,clock:() => 1000); await active.load();
    final plan = active.previewImport([portable()]); disk.loseReply = true;
    await expectLater(active.applyImport(plan,[const ConfigImportChoice(ConfigImportAction.add)]),throwsA(isA<RemoteFailure>()));
    expect(active.ready,isFalse); expect(active.profiles,isEmpty); expect(disk.writes,1);
    expect(() => active.applyImport(plan,[const ConfigImportChoice(ConfigImportAction.add)]),throwsA(isA<RemoteFailure>()));
    expect(disk.writes,1);
    final reopened = HostCatalog(storage:disk,clock:() => 1000); await reopened.load();
    expect(reopened.ready,isTrue); expect(reopened.profiles.length,1); expect(reopened.profiles.single.hasIdentity,isFalse);
    active.dispose(); reopened.dispose();
  });
  test('reverse and shuffled legal target fields import and finish ordinary pairing without binding mismatch', () async {
    final original = portable(), keys = transferTargetFields.toList();
    final orders = [keys.reversed.toList(),for (var seed = 0; seed < 4; seed++) (List<String>.of(keys)..shuffle(Random(seed)))];
    for (final order in orders) {
      final raw = Uint8List.fromList(utf8.encode(jsonEncode({'version':1,'hosts':[
        {...original.toJson(),'target':{for (final key in order) key:original.target[key]}}
      ]})));
      final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
      final plan = catalog.previewImport(decodePortableHosts(raw));
      await catalog.applyImport(plan,[const ConfigImportChoice(ConfigImportAction.add)]);
      final imported = catalog.profiles.single;
      final differentOrder = <String,dynamic>{'paneId':'',for (final key in order.reversed) key:imported.target[key]};
      expect(sameHostTarget(imported.target,differentOrder),isTrue);
      await catalog.beginCreation(differentOrder,imported.label,sourceProfileId:imported.id);
      final pairing = catalogPairing(); await catalog.recordCreatedHandle(pairing.handle);
      final profile = HostProfile.create(imported.label,differentOrder,pairing,1000,provider:imported.provider);
      await catalog.completeCreation(profile);
      expect(catalog.ready,isTrue); expect(catalog.profiles.length,1); expect(catalog.pendingCreation,isNull);
      expect(catalog.profiles.single.hasIdentity,isTrue); expect(catalog.profiles.single.pairingRecord['handle'],pairing.handle);
      expect(sameHostTarget(catalog.profiles.single.target,differentOrder),isTrue);
      catalog.dispose();
    }
  });
  test('two replacements sharing one paired conflict fail whole-plan preflight without tab revocation, save, or lock', () async {
    final disk = MemoryCatalogStorage();
    final active = HostCatalog(storage:disk,clock:() => 1000); await active.load(); final old = await saveCatalogProfile(active);
    final plan = active.previewImport([portable(label:old.label,host:'one.invalid'),portable(label:old.label,host:'two.invalid')]);
    final writes = disk.writes; var revoked = 0;
    expect(() => active.applyImport(plan,[const ConfigImportChoice(ConfigImportAction.replace),const ConfigImportChoice(ConfigImportAction.replace)],
      beforeCommit:(_) { revoked++; }),throwsA(isA<RemoteFailure>()));
    expect(revoked,0); expect(disk.writes,writes); expect(active.ready,isTrue);
    expect(active.profiles.single.toJson(),old.toJson()); expect(active.status.contains('未知'),isFalse);
    await active.update(old.change(label:'Still editable after validation error',now:1000));
    expect(active.ready,isTrue); active.dispose();
  });
  test('expired and queue-expired plans never revoke tabs, write import bytes or lock the catalog', () async {
    final disk = MemoryCatalogStorage();
    final catalog = HostCatalog(storage:disk,clock:() => 1000); await catalog.load(); final old = await saveCatalogProfile(catalog);
    final expired = catalog.previewImport([portable(label:'new',host:'new.invalid')]);
    final updating = catalog.update(old.change(label:'A queued edit',now:1000));
    var revoked = 0;
    final importing = catalog.applyImport(expired,[const ConfigImportChoice(ConfigImportAction.add)],beforeCommit:(_) { revoked++; });
    final rejected = expectLater(importing,throwsA(isA<RemoteFailure>()));
    final writes = disk.writes; await updating; await rejected;
    expect(revoked,0); expect(disk.writes,writes+1); expect(catalog.ready,isTrue);
    final nowWrites = disk.writes;
    expect(() => catalog.applyImport(expired,[const ConfigImportChoice(ConfigImportAction.add)],beforeCommit:(_) { revoked++; }),throwsA(isA<RemoteFailure>()));
    expect(revoked,0); expect(disk.writes,nowWrites); expect(catalog.ready,isTrue); catalog.dispose();
  });
  test('whole-plan capacity failure leaves tabs and the writable catalog untouched', () async {
    final disk = MemoryCatalogStorage();
    final catalog = HostCatalog(storage:disk,clock:() => 1000); await catalog.load();
    for (var batch = 0; batch < 2; batch++) {
      final hosts = [for (var i = 0; i < 16; i++) portable(label:'host-${batch*16+i}',host:'host-${batch*16+i}.invalid')];
      await catalog.applyImport(catalog.previewImport(hosts),[for (var i = 0; i < 16; i++) const ConfigImportChoice(ConfigImportAction.add)]);
    }
    final plan = catalog.previewImport([portable(label:'overflow',host:'overflow.invalid')]), writes = disk.writes;
    var revoked = 0;
    expect(() => catalog.applyImport(plan,[const ConfigImportChoice(ConfigImportAction.add)],beforeCommit:(_) { revoked++; }),throwsA(isA<RemoteFailure>()));
    expect(revoked,0); expect(disk.writes,writes); expect(catalog.profiles.length,maxHostProfiles); expect(catalog.ready,isTrue);
    catalog.dispose();
  });
}
