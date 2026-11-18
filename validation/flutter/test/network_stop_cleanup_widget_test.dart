import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/host_tabs.dart';
import 'package:herdr_flutter_probe/network_identity.dart';
import 'package:herdr_flutter_probe/network_runtime.dart';
import 'host_catalog_test.dart' show MemoryCatalogStorage;
import 'host_tabs_widget_test.dart' show TabFixtureAdapter,tabProfile,connectTab;
import 'network_profiles_test.dart' show testNetwork;
import 'network_profiles_widget_test.dart' show showNetworkDetails;
import 'pairing_gui_test.dart' show TestDeviceKeys,tapVisible;
import 'remote_test_data.dart';

class HeldCleanupAdapter extends TabFixtureAdapter {
  HeldCleanupAdapter(this.name,this.events);
  final String name;
  final List<String> events;
  final cleanup=Completer<void>();
  @override Future<void> cancel() {
    if (cancels++==0) {generation++;events.add('$name.cancel.started');}
    return cleanup.future.then((_) {events.add('$name.cancel.completed');});
  }
}
void main() {
  for (final outcome in ['complete','timeout','cleanup-error','stop-error']) {
  testWidgets('network stop coordinates only affected real tab cleanup: $outcome',(tester) async {
    tester.view.devicePixelRatio=1;tester.view.physicalSize=const Size(1200,1000);
    addTearDown(tester.view.resetDevicePixelRatio);addTearDown(tester.view.resetPhysicalSize);
    final previousPlatform=debugDefaultTargetPlatformOverride;debugDefaultTargetPlatformOverride=TargetPlatform.android;
    final catalog=HostCatalog(storage:MemoryCatalogStorage(),clock:()=>1000);await catalog.load();
    final networkA=testNetwork('tailscale'),networkB=testNetwork('easytier');
    await catalog.addNetwork(networkA);await catalog.addNetwork(networkB);
    final a=tabProfile('Host A','probeA','127.0.0.1','tailscale','opaque-a').change(networkProfileId:networkA.id,replaceNetwork:true,now:1000);
    final b=tabProfile('Host B','probeB','127.0.0.2','easytier','opaque-b').change(networkProfileId:networkB.id,replaceNetwork:true,now:1000);
    await catalog.add(a);await catalog.add(b);
    final identities={for(final p in [networkA,networkB])p.id:{'profileId':p.id,'provider':p.provider,'handle':'a0000000-0000-4000-8000-000000000001','instanceId':'b0000000-0000-4000-8000-000000000002','mode':p.provider=='tailscale'?'DEVICE_STATE':'PRIVATE'}};
    final bindings={for(final p in [networkA,networkB])p.id:NetworkNodeBinding.forProfile(p,NetworkIdentityRecord.checked(identities[p.id],p))};
    final events=<String>[];var stops=0;
    final messenger=TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(NativeNetworkIdentityStore.channel,(call) async=>identities[(call.arguments as Map)['profileId']]);
    messenger.setMockMethodCallHandler(NativeNetworkRuntime.channel,(call) async {
      if(call.method=='available')return {'available':true,'reason':null};
      if(call.method=='nodeStatus') {final binding=bindings[(call.arguments as Map)['profileId']]!;return {'state':binding.provider=='tailscale'?'running':'engine-started','binding':binding.toMap()};}
      if(call.method=='nodeStop') {stops++;events.add('provider.stop');if(outcome=='stop-error')throw StateError('synthetic unknown stop');return {'state':'stopped','binding':null};}
      throw StateError('unexpected fixture method');
    });
    addTearDown(() {messenger.setMockMethodCallHandler(NativeNetworkIdentityStore.channel,null);messenger.setMockMethodCallHandler(NativeNetworkRuntime.channel,null);});
    final adapters={a.id:HeldCleanupAdapter('A',events),b.id:HeldCleanupAdapter('B',events)};
    final tabs=HostTabs(),tokens=(await tester.runAsync(DesignTokens.load))!,keys=TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
    try {
      await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:HostCatalogPage(tokens:tokens,catalog:catalog,keys:keys,tabs:tabs,adapterFactory:(p)=>adapters[p.id]!,overlayAdapterFactory:(p,connector)=>adapters[p.id]!,offlineBuilder:(_)=>const SizedBox())));
      await tester.pumpAndSettle();
      for(final host in [a,b]) {
        await tapVisible(tester,'host-open-${host.id}');await tester.pumpAndSettle();
        await tapVisible(tester,'pair-connect');await tester.pumpAndSettle();
        await connectTab(tester,adapters[host.id]!);await tester.pump();
        await tapVisible(tester,'hosts-board-tab');
      }
      await tapVisible(tester,'hosts-networks');await tester.pumpAndSettle();
      await showNetworkDetails(tester,networkA.id);await tapVisible(tester,'network-node-refresh-${networkA.id}');await tester.pumpAndSettle();
      final stopFinder=find.byKey(ValueKey('network-node-stop-${networkA.id}'));
      final aTab=tabs.forHost(a.id).single, bConnection=adapters[b.id]!.connection;
      final previousGeneration=adapters[a.id]!.generation;
      tester.widget<TextButton>(stopFinder).onPressed!();
      // No frame/dispose may be needed to seal the old write generation.
      expect(aTab.inputEligible.value,isFalse);expect(adapters[a.id]!.generation,greaterThan(previousGeneration));
      expect(adapters[a.id]!.cancels,1);expect(stops,0);
      await tester.pump();
      expect(stops,0,reason:'native stop must not overtake SSH cleanup: $events');
      expect(adapters[a.id]!.cancels,1);expect(adapters[b.id]!.cancels,0);
      expect(tabs.forHost(a.id),isEmpty);expect(tabs.forHost(b.id).length,1);
      expect(events,contains('A.cancel.started'));
      expect(tester.widget<TextButton>(stopFinder).onPressed,isNull);
      if(outcome=='timeout') {await tester.pump(const Duration(seconds:5));}
      else if(outcome=='cleanup-error') {adapters[a.id]!.cleanup.completeError(StateError('synthetic unknown cleanup'));}
      else {adapters[a.id]!.cleanup.complete();}
      await tester.pump();await tester.pump();
      expect(stops,1);expect(adapters[a.id]!.cancels,1);
      if(outcome=='complete') {expect(events.indexOf('A.cancel.completed'),lessThan(events.indexOf('provider.stop')));}
      if(outcome=='timeout'||outcome=='cleanup-error') {expect(find.textContaining('SSH 清退尚未确认'),findsOneWidget);}
      if(outcome=='timeout') {
        adapters[a.id]!.cleanup.complete();await tester.pump();await tester.pump();
        expect(find.textContaining('SSH 清退尚未确认'),findsOneWidget);expect(stops,1);
      }
      if(outcome=='stop-error') {expect(find.textContaining('停止尚未确认'),findsWidgets);}
      expect(adapters[b.id]!.cancels,0);expect(adapters[b.id]!.calls,1);expect(identical(adapters[b.id]!.connection,bConnection),isTrue);
    } finally {
      for(final adapter in adapters.values) {if(!adapter.cleanup.isCompleted)adapter.cleanup.complete();}
      await tester.pumpWidget(const SizedBox());await tester.pump();tabs.dispose();catalog.dispose();debugDefaultTargetPlatformOverride=previousPlatform;
    }
  });
  }
}
