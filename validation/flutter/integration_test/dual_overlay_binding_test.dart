import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/pairing_page.dart';
import 'package:herdr_flutter_probe/pairing_public_key.dart';
import 'dual_overlay_ui_steps.dart';
import 'android_pairing_observe_test.dart' as existing;
import '../test/host_catalog_test.dart' show MemoryCatalogStorage;
import '../test/pairing_gui_test.dart' show TestDeviceKeys;
import '../test/remote_test_data.dart' show fixtureConfig;
import '../test/network_profiles_test.dart' show testNetwork;

void main() {
  for (final width in [320.0, 390.0]) {
  testWidgets('two hosts bind consecutively at ${width}px', (tester) async {
   tester.view.devicePixelRatio=1; tester.view.physicalSize=Size(width,844);
   addTearDown(tester.view.resetPhysicalSize); addTearDown(tester.view.resetDevicePixelRatio);
   final root=Directory.systemTemp.createTempSync('pairing-full-'); addTearDown(() => root.deleteSync(recursive:true));
   final disk=MemoryCatalogStorage(); final now=DateTime.now().millisecondsSinceEpoch ~/ 1000;
   final catalog=HostCatalog(storage:disk,clock:()=>now); await catalog.load();
   final networks={'et':testNetwork('easytier'),'ts':testNetwork('tailscale')};
   for (final network in networks.values) { await catalog.addNetwork(network); }
   final keys=TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
   tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(const MethodChannel('dev.herdr/device-keys'), (call) async {
    if (call.method=='create') { await keys.create(); return 'test-handle-${keys.creates}'; }
    if (call.method=='public') return keys.public((call.arguments as Map)['handle'] as String);
    if (call.method=='delete') { await keys.delete((call.arguments as Map)['handle'] as String); return true; }
    throw StateError('unexpected_key_call');
   });
   addTearDown(() => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(const MethodChannel('dev.herdr/device-keys'),null));
   final tokens=(await tester.runAsync(DesignTokens.load))!;
   await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:HostCatalogPage(tokens:tokens,catalog:catalog,offlineBuilder:(_) => const SizedBox()))); await tester.pumpAndSettle();
   final steps=DualOverlayUiSteps(tester,root);
   for (final role in ['et','ts']) {
   final network=networks[role]!; final raw=fixtureConfig();
   if (role=='ts') raw['port']=2223;
   final profile={'version':1,'type':'herdr-connection-profile','provider':role=='et'?'easytier':'tailscale',
     for (final name in ['host','port','username','session','socketPath','herdrPath','expectedHostKey']) name:raw[name]};
   await steps.openPairingFromCatalog();
   final page=tester.widget<PairingPage>(find.byType(PairingPage)); expect(page.keys,isNull); expect(page.adapter,isNull);
   final before=catalog.profiles.map((p)=>p.id).toSet(); final fingerprint=pairingFingerprint(profile['expectedHostKey'] as String);
   await steps.enter('profile-input',jsonEncode(profile));
   await existing.until(tester,()=>find.byKey(const ValueKey('profile-preview')).evaluate().length==1);
   final preview=tester.widget<SelectableText>(find.byKey(const ValueKey('profile-preview'))).data!;
   expect(preview,contains(fingerprint));
   for(final field in ['host','port','username','session','socketPath','herdrPath']) { expect(preview,contains(profile[field].toString())); }
   await existing.tapKey(tester,'profile-fill');
   expect(tester.widget<SelectableText>(find.byKey(const ValueKey('pair-target-fingerprint'))).data,fingerprint);
   await tester.testTextInput.receiveAction(TextInputAction.done); await tester.pump();
   final review=await existing.stableReviewCheckbox(tester,'pair-target-review'); await tester.tap(review); await tester.pump();
   await existing.tapStablePointer(tester,find.byKey(const ValueKey('pair-create')));
   await existing.until(tester,()=>find.byKey(const ValueKey('pair-request')).evaluate().length==1);
   final wire=tester.widget<SelectableText>(find.byKey(const ValueKey('pair-request'))).data!;
   final request=jsonDecode(wire) as Map<String,dynamic>;
   final req=File('${root.path}/request.json')..writeAsStringSync(wire); final pub=File('${root.path}/host.pub')..writeAsStringSync(profile['expectedHostKey'] as String);
   final script='''import json,pathlib,sys
from herdr_pocket_helper.store import Host
root=pathlib.Path(sys.argv[1]); raw=pathlib.Path(sys.argv[2]).read_bytes(); r=json.loads(raw)
h=Host(root,r['account'],pathlib.Path(sys.argv[3]).read_text());sys.stdout.write(h.authorize(raw,r['request_id'],now=int(sys.argv[4])).decode())''';
   final python=Platform.environment['HP_PAIRING_PYTHON'], repo=Platform.environment['HP_PAIRING_REPO'];
   if (python == null || repo == null) throw StateError('isolated_fixture_environment_required');
   final result=await tester.runAsync(()=>Process.run(python,['-c',script,root.path,req.path,pub.path,'$now'],environment:{...Platform.environment,'PYTHONPATH':'$repo/helper'}));
   expect(result!.exitCode,0,reason:'isolated host approval');
   await steps.acceptPairResponse(role,result.stdout as String,request,fingerprint);
   final added=catalog.profiles.where((p)=>!before.contains(p.id)).toList(); expect(added.length,1);
   expect(added.single.requiresNetworkBinding,isTrue); expect(added.single.provider,role=='et'?'easytier':'tailscale');
   expect(added.single.restore(now).state,'authorized-unverified'); expect(keys.signCalls,0);
   await tester.pageBack(); await tester.pumpAndSettle(); expect(find.byType(HostCatalogPage),findsOneWidget);
   await steps.bindHost(added.single.id,network.id,network.label,network.provider);
   expect(catalog.profiles.singleWhere((p)=>p.id==added.single.id).networkProfileId,network.id);
   await steps.openPairingFromCatalog();
   await tester.pageBack(); await tester.pumpAndSettle();
   }
   expect(catalog.profiles.length,2);
   for (final host in catalog.profiles) {
     await steps.showHostControl('host-open-${host.id}');
     expect(find.byKey(ValueKey('host-open-${host.id}')),findsOneWidget);
   }
   await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  }
}
