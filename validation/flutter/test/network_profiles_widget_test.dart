import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart' as foundation;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart' as services;
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/network_profiles.dart';
import 'package:herdr_flutter_probe/network_profiles_page.dart';
import 'package:herdr_flutter_probe/network_runtime.dart';
import 'package:herdr_flutter_probe/network_identity.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'package:herdr_flutter_probe/remote_page.dart';
import 'host_catalog_test.dart' show MemoryCatalogStorage,saveCatalogProfile;
import 'config_transfer_test.dart' show portable;
import 'network_profiles_test.dart' show testNetwork;
import 'pairing_gui_test.dart' show TestDeviceKeys,tapVisible,authorizedResponse;
import 'remote_page_test.dart' show PendingAdapter;
import 'remote_test_data.dart';
import 'network_identity_test.dart' show MemoryNetworkIdentity,identityReply;

typedef CatalogRead = ({String revision, String contents});

class GatedNetworkCatalogStorage extends MemoryCatalogStorage {
  final reads = <Completer<CatalogRead>>[];
  bool gate = false;

  @override
  Future<CatalogRead> load() {
    if (!gate) return super.load();
    final read = Completer<CatalogRead>();
    reads.add(read);
    return read.future;
  }
}

class CountingDeviceKeys extends TestDeviceKeys {
  CountingDeviceKeys(super.pem);
  int publicCalls = 0;
  @override Future<String> public(String handle) { publicCalls++; return super.public(handle); }
}

/// Explicit stopped Tailscale node; avoids relying on the host test platform or a real bridge.
class StoppedTailscaleRuntime extends NativeNetworkRuntime {
  int statusCalls = 0;
  @override bool get supported => true;
  @override Future<Object?> call(String method,Map<String,Object> args) async {
    if (method != 'nodeStatus' || args['provider'] != 'tailscale' || args['profileId'] is! String) {
      throw const RemoteFailure('unexpected_fixture_method');
    }
    statusCalls++;
    return {'state':'stopped','binding':null};
  }
}

class PendingNodeRuntime extends NativeNetworkRuntime {
  final pending = Completer<NetworkNodeSnapshot>();
  NetworkNodeBinding? binding;
  bool reportStopped = false;
  int starts = 0,stops = 0;
  @override bool get supported => true;
  @override Future<bool> available() async => true;
  @override Future<NetworkNodeSnapshot> status(String id) async => binding == null || reportStopped
    ? const NetworkNodeSnapshot('stopped',null) : NetworkNodeSnapshot('starting',binding);
  @override Future<NetworkNodeSnapshot> start(NetworkNodeBinding value,List<String> peers) {
    starts++; binding = value; return pending.future;
  }
  @override Future<NetworkNodeSnapshot> stop(NetworkNodeBinding value) async {
    expect(value.same(binding!),isTrue); stops++; return const NetworkNodeSnapshot('stopped',null);
  }
}

Future<void> showNetworkDetails(WidgetTester tester,String id) async {
  if (find.byKey(ValueKey('network-edit-$id')).evaluate().isNotEmpty) return;
  final details=find.byKey(PageStorageKey('network-details-$id'));
  await tester.ensureVisible(details); await tester.tap(details); await tester.pumpAndSettle();
}

void main() {
  testWidgets('desktop live network does not revive a superseded empty read and keeps the editor across widths', (tester) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(980, 780);
    addTearDown(tester.view.reset);
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    final storage = GatedNetworkCatalogStorage();
    final catalog = HostCatalog(storage: storage, clock: () => 1000);
    await catalog.load();
    final stored = HostCatalog(storage: MemoryCatalogStorage(), clock: () => 1000);
    await stored.load();
    final profile = testNetwork('tailscale');
    await stored.addNetwork(profile);
    final saved = await stored.storage.load();
    stored.dispose();
    await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: Builder(builder: (context) {
      final desktop = MediaQuery.sizeOf(context).width >= 700;
      return NetworkProfilesPage(catalog: catalog, closeTabs: (_) {},
        desktopSshSession: desktop ? (tokens: tokens, notice: const Text('普通 SSH 会话保持连接')) : null);
    })));
    await tester.pumpAndSettle();
    final empty = find.byKey(const ValueKey('network-empty-card'));
    expect(empty, findsOneWidget);

    storage.gate = true;
    final old = catalog.load(), failing = catalog.load();
    await tester.pump();
    expect(find.text('正在重新读取本机网络配置'), findsOneWidget);
    expect(empty, findsNothing);
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('networks-add'))).onPressed, isNull);
    storage.reads[1].completeError(StateError('test read failure'));
    await failing;
    await tester.pump();
    expect(catalog.reading, isFalse);
    expect(find.textContaining('资料损坏、存储锁定或不可用'), findsOneWidget);
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('networks-add'))).onPressed, isNull);
    storage.reads[0].complete((revision: '', contents: ''));
    await old;
    await tester.pump();
    expect(find.textContaining('资料损坏、存储锁定或不可用'), findsOneWidget);
    expect(empty, findsNothing);

    final superseded = catalog.load(), recovered = catalog.load();
    storage.reads[2].complete((revision: '', contents: ''));
    await superseded;
    tester.view.physicalSize = const Size(390, 844);
    await tester.pump();
    expect(catalog.reading, isTrue);
    expect(find.text('正在重新读取本机网络配置'), findsOneWidget);
    expect(find.textContaining('暂无网络配置'), findsNothing);
    storage.reads[3].complete(saved);
    await recovered;
    tester.view.physicalSize = const Size(980, 780);
    await tester.pumpAndSettle();
    expect(catalog.reading, isFalse);
    expect(find.byKey(ValueKey('network-card-${profile.id}')), findsOneWidget);
    expect(empty, findsNothing);

    await tapVisible(tester, 'networks-add');
    await tester.pumpAndSettle();
    final draft = find.byKey(const ValueKey('network-label'));
    await tester.enterText(draft, 'Uncommitted network');
    tester.view.physicalSize = const Size(390, 844);
    await tester.pumpAndSettle();
    expect(tester.widget<TextField>(draft).controller!.text, 'Uncommitted network');
    expect(catalog.networkProfiles.single.id, profile.id);
    expect(storage.writes, 0);
    await tester.pumpWidget(const SizedBox());
    catalog.dispose();
  });

  testWidgets('status read during pending start cannot clear an unknown start result',(tester) async {
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final profile = testNetwork('easytier'); await catalog.addNetwork(profile);
    final identities = MemoryNetworkIdentity()..current = NetworkIdentityRecord.checked(identityReply(profile),profile);
    final runtime = PendingNodeRuntime();
    await tester.pumpWidget(MaterialApp(home:NetworkProfilesPage(catalog:catalog,closeTabs:(_) {},identityStore:identities,runtime:runtime)));
    await showNetworkDetails(tester,profile.id); await tapVisible(tester,'network-node-refresh-${profile.id}'); await tester.pumpAndSettle();
    await showNetworkDetails(tester,profile.id); await tapVisible(tester,'network-node-start-${profile.id}'); await tester.pump(); await tester.pump();
    runtime.reportStopped = true;
    await showNetworkDetails(tester,profile.id); await tapVisible(tester,'network-node-refresh-${profile.id}'); await tester.pump();
    runtime.pending.completeError(StateError('unknown')); await tester.pump(); await tester.pump();
    final start = find.byKey(ValueKey('network-node-start-${profile.id}'));
    expect(tester.widget<TextButton>(start).onPressed,isNull);
    expect(find.textContaining('启动结果或期间状态未确认'),findsOneWidget);
    await showNetworkDetails(tester,profile.id); await tapVisible(tester,'network-node-refresh-${profile.id}'); await tester.pump();
    expect(tester.widget<TextButton>(start).onPressed,isNotNull);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('pending node start can be refreshed and stopped; late start cannot overwrite stopped',(tester) async {
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final profile = testNetwork('easytier'); await catalog.addNetwork(profile);
    final identities = MemoryNetworkIdentity()..current = NetworkIdentityRecord.checked(identityReply(profile),profile);
    final runtime = PendingNodeRuntime();
    await tester.pumpWidget(MaterialApp(home:NetworkProfilesPage(catalog:catalog,closeTabs:(_) {},identityStore:identities,runtime:runtime)));
    await showNetworkDetails(tester,profile.id); await tapVisible(tester,'network-node-refresh-${profile.id}'); await tester.pumpAndSettle();
    await showNetworkDetails(tester,profile.id); await tapVisible(tester,'network-node-start-${profile.id}'); await tester.pump(); await tester.pump();
    expect(runtime.starts,1); expect(find.textContaining('正在启动'),findsOneWidget);
    await showNetworkDetails(tester,profile.id); await tapVisible(tester,'network-node-refresh-${profile.id}'); await tester.pump();
    await showNetworkDetails(tester,profile.id); await tapVisible(tester,'network-node-stop-${profile.id}'); await tester.pump();
    expect(runtime.stops,1); expect(find.textContaining('已停止'),findsOneWidget);
    runtime.pending.complete(NetworkNodeSnapshot('engine-started',runtime.binding)); await tester.pump();
    expect(find.text('节点：已停止'),findsOneWidget); expect(find.text('节点：引擎已启动 · 入网与 SSH 未验证'),findsNothing);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('profile editing is re-enabled only after node start settles',(tester) async {
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final profile = testNetwork('easytier'); await catalog.addNetwork(profile);
    final identities = MemoryNetworkIdentity()..current = NetworkIdentityRecord.checked(identityReply(profile),profile);
    final runtime = PendingNodeRuntime();
    await tester.pumpWidget(MaterialApp(home:NetworkProfilesPage(catalog:catalog,closeTabs:(_) {},identityStore:identities,runtime:runtime)));
    await showNetworkDetails(tester,profile.id); await tapVisible(tester,'network-node-refresh-${profile.id}'); await tester.pumpAndSettle();
    await showNetworkDetails(tester,profile.id); await tapVisible(tester,'network-node-start-${profile.id}'); await tester.pump(); await tester.pump();
    final edit = find.byKey(ValueKey('network-edit-${profile.id}'));
    expect(tester.widget<TextButton>(edit).onPressed,isNull);
    expect(find.textContaining('正在启动'),findsOneWidget);
    runtime.pending.complete(NetworkNodeSnapshot('engine-started',runtime.binding));
    await tester.pump(); await tester.pump();
    expect(tester.widget<TextButton>(edit).onPressed,isNotNull);
    expect(find.text('节点：引擎已启动 · 入网与 SSH 未验证'),findsOneWidget);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('normal 360px host board exposes network manager and creates a reusable profile',(tester) async {
    tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(360,780);
    addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:HostCatalogPage(tokens:tokens,catalog:catalog,offlineBuilder:(_) => const SizedBox())));
    await tester.pumpAndSettle(); await tapVisible(tester,'hosts-networks'); await tester.pumpAndSettle();
    expect(find.byType(NetworkProfilesPage),findsOneWidget);
    await tapVisible(tester,'networks-add'); await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('network-label')),'Phone mesh');
    await tapVisible(tester,'network-save'); await tester.pumpAndSettle();
    expect(catalog.networkProfiles.single.label,'Phone mesh');
    expect(catalog.networkProfiles.single.provider,'tailscale');
    expect(catalog.networkProfiles.single.settings,{'controlUrl':'','hostname':''});
    expect(find.textContaining('网络组件暂不可用时，已绑定的主机会保持断开'),findsOneWidget);
    expect(find.textContaining('provider_unavailable'),findsNothing);
    expect(tester.takeException(),isNull); await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  for (final width in [320.0,390.0]) {
    testWidgets('network guidance stays readable at ${width.toInt()}px',(tester) async {
      tester.view.devicePixelRatio = 1; tester.view.physicalSize = Size(width,844);
      addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
      final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
      await tester.pumpWidget(MaterialApp(home:NetworkProfilesPage(catalog:catalog,closeTabs:(_) {})));
      final guidance = find.textContaining('网络组件暂不可用时，已绑定的主机会保持断开');
      await tester.ensureVisible(guidance); await tester.pumpAndSettle();
      expect(guidance,findsOneWidget);
      expect(find.textContaining('provider_unavailable'),findsNothing);
      expect(tester.takeException(),isNull);
      await tester.pumpWidget(const SizedBox()); catalog.dispose();
    });
  }
  testWidgets('network impact lists referenced host and refusing delete preserves its binding',(tester) async {
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final network = testNetwork(),original = await saveCatalogProfile(catalog); await catalog.addNetwork(network);
    await catalog.update(original.change(networkProfileId:network.id,replaceNetwork:true,now:1000));
    final closed = <String>{},runtime = StoppedTailscaleRuntime();
    await tester.pumpWidget(MaterialApp(home:NetworkProfilesPage(catalog:catalog,closeTabs:closed.addAll,runtime:runtime)));
    await showNetworkDetails(tester,network.id); await tapVisible(tester,'network-delete-${network.id}'); await tester.pumpAndSettle();
    expect(find.descendant(of:find.byType(AlertDialog),matching:find.textContaining('Fixture host')),findsOneWidget);
    await tapVisible(tester,'network-confirm'); await tester.pumpAndSettle();
    expect(catalog.networkProfiles.single.id,network.id); expect(closed,isEmpty);
    expect(find.textContaining('此网络仍被主机引用'),findsOneWidget);
    await showNetworkDetails(tester,network.id); await tapVisible(tester,'network-toggle-${network.id}'); await tester.pumpAndSettle();
    await tapVisible(tester,'network-confirm'); await tester.pumpAndSettle();
    expect(catalog.networkProfiles.single.enabled,isFalse); expect(closed,{original.id});
    expect(runtime.statusCalls,1);
    expect(catalog.profiles.single.networkProfileId,network.id);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('network deletion review preserves existing device identity and forbids automatic removal',(tester) async {
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final network = testNetwork('easytier'); await catalog.addNetwork(network);
    final identities = MemoryNetworkIdentity()..current = NetworkIdentityRecord.checked(identityReply(network),network);
    final closed = <String>{};
    await tester.pumpWidget(MaterialApp(home:NetworkProfilesPage(catalog:catalog,closeTabs:closed.addAll,identityStore:identities)));
    await showNetworkDetails(tester,network.id);
    await tapVisible(tester,'network-delete-${network.id}'); await tester.pumpAndSettle();
    await tapVisible(tester,'network-confirm'); await tester.pumpAndSettle();
    expect(catalog.networkProfiles.single.id,network.id);
    expect(identities.deletes,0); expect(identities.current,isNotNull); expect(closed,isEmpty);
    expect(find.textContaining('此配置仍有本机入网资料'),findsOneWidget);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('disabled overlay without a bridge still permits offline pairing and helper response review after reopening',(tester) async {
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final network = NetworkProfile.fromJson({...testNetwork().toJson(),'enabled':false}); await catalog.addNetwork(network);
    final imported = HostProfile.imported(portable(),1000,networkProfileId:network.id); await catalog.add(imported);
    final tokens = (await tester.runAsync(DesignTokens.load))!,keys = TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
    final adapters = <PendingAdapter>[];
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:HostCatalogPage(tokens:tokens,catalog:catalog,keys:keys,
      adapterFactory:(_) { final adapter = PendingAdapter(); adapters.add(adapter); return adapter; },offlineBuilder:(_) => const SizedBox())));
    await tester.pumpAndSettle(); await tapVisible(tester,'host-open-${imported.id}'); await tester.pumpAndSettle();
    await tapVisible(tester,'pair-target-review'); await tapVisible(tester,'pair-create'); await tester.pumpAndSettle();
    expect(keys.creates,1); expect(find.byKey(const ValueKey('pair-request')),findsOneWidget);
    final paired = catalog.profiles.single;
    await tester.pageBack(); await tester.pumpAndSettle();
    await tapVisible(tester,'host-open-${paired.id}'); await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('pair-request')),findsOneWidget);
    final response = jsonEncode(authorizedResponse(Map<String,dynamic>.from(paired.pairingRecord['request'] as Map)));
    final input = find.byKey(const ValueKey('pair-response')); await tester.ensureVisible(input); await tester.enterText(input,response); await tester.pump();
    expect(find.byKey(const ValueKey('pair-response-preview')),findsOneWidget);
    await tapVisible(tester,'pair-source-review'); await tapVisible(tester,'pair-accept'); await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('pair-connect')),findsOneWidget);
    await tapVisible(tester,'pair-connect'); await tester.pumpAndSettle();
    await tapVisible(tester,'remote-review'); await tapVisible(tester,'remote-connect'); await tester.pumpAndSettle();
    expect(find.textContaining('网络绑定已改变或停用'),findsOneWidget);
    expect(keys.creates,1); expect(keys.signCalls,0); expect(adapters.every((adapter) => adapter.calls == 0),isTrue);
    expect(catalog.profiles.single.networkProfileId,network.id); expect(catalog.networkProfiles.single.enabled,isFalse);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('every overlay stops before SSH adapter or device signing; explicit revision is displayed',(tester) async {
    final previousPlatform = foundation.debugDefaultTargetPlatformOverride;
    foundation.debugDefaultTargetPlatformOverride = foundation.TargetPlatform.linux;
    try {
      final tokens = (await tester.runAsync(DesignTokens.load))!;
      for (final provider in overlayProviders) {
        final adapter = PendingAdapter(),keys = CountingDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
        final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
        final network = testNetwork(provider),original = await saveCatalogProfile(catalog); await catalog.addNetwork(network);
        final bound = original.change(networkProfileId:network.id,replaceNetwork:true,now:1000); await catalog.update(bound);
        await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:RemotePage(tokens:tokens,adapter:adapter,
          pairedTarget:bound.target,deviceKeys:keys,keyHandle:bound.pairingRecord['handle'] as String,
          devicePublicKey:fixtureConfig()['expectedHostKey'] as String,networkBinding:catalog.freezeNetwork(bound))));
        await tapVisible(tester,'remote-review'); await tapVisible(tester,'remote-connect'); await tester.pumpAndSettle();
        expect(find.textContaining('provider_unavailable'),findsOneWidget);
        expect(find.textContaining(network.label),findsOneWidget);
        expect(adapter.calls,0); expect(keys.publicCalls,0); expect(keys.signCalls,0); expect(keys.creates,0);
        await tester.pumpWidget(const SizedBox()); catalog.dispose();
      }
    } finally {
      foundation.debugDefaultTargetPlatformOverride = previousPlatform;
    }
  });
  testWidgets('Android runtime channel failure stops overlay before credentials or system dial',(tester) async {
    final previousPlatform = foundation.debugDefaultTargetPlatformOverride;
    foundation.debugDefaultTargetPlatformOverride = foundation.TargetPlatform.android;
    try {
      final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
      final calls = <String>[];
      messenger.setMockMethodCallHandler(NativeNetworkRuntime.channel,(call) async {
        calls.add(call.method); throw services.PlatformException(code:'overlay_provider_unavailable');
      });
      addTearDown(() => messenger.setMockMethodCallHandler(NativeNetworkRuntime.channel,null));
      final tokens = (await tester.runAsync(DesignTokens.load))!;
      final adapter = PendingAdapter(),keys = CountingDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
      final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
      final network = testNetwork('easytier'),original = await saveCatalogProfile(catalog); await catalog.addNetwork(network);
      final bound = original.change(networkProfileId:network.id,replaceNetwork:true,now:1000); await catalog.update(bound);
      await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:RemotePage(tokens:tokens,adapter:adapter,
        pairedTarget:bound.target,deviceKeys:keys,keyHandle:bound.pairingRecord['handle'] as String,
        devicePublicKey:fixtureConfig()['expectedHostKey'] as String,networkBinding:catalog.freezeNetwork(bound))));
      await tapVisible(tester,'remote-review'); await tapVisible(tester,'remote-connect'); await tester.pumpAndSettle();
      expect(find.textContaining('节点状态或连接桥不可确认'),findsOneWidget);
      expect(calls,['available']); expect(adapter.calls,0); expect(keys.publicCalls,0); expect(keys.signCalls,0);
      await tester.pumpWidget(const SizedBox()); catalog.dispose();
    } finally {
      foundation.debugDefaultTargetPlatformOverride = previousPlatform;
    }
  });
}
