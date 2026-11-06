import 'dart:typed_data';
import 'package:flutter/foundation.dart' as foundation;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart' as services;
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/network_identity.dart';
import 'package:herdr_flutter_probe/network_profiles_page.dart';
import 'package:herdr_flutter_probe/network_runtime.dart';
import 'package:herdr_flutter_probe/remote_page.dart';
import 'host_catalog_test.dart' show MemoryCatalogStorage,saveCatalogProfile;
import 'network_profiles_test.dart' show testNetwork;
import 'network_profiles_widget_test.dart' show CountingDeviceKeys;
import 'network_tailscale_test.dart';
import 'pairing_gui_test.dart' show tapVisible;
import 'remote_page_test.dart' show PendingAdapter;
import 'remote_test_data.dart';

void main() {
  testWidgets('missing Android TS bridge fails before device-key access, SSH or system fallback',(tester) async {
    final previous = foundation.debugDefaultTargetPlatformOverride;
    foundation.debugDefaultTargetPlatformOverride = foundation.TargetPlatform.android;
    addTearDown(() { foundation.debugDefaultTargetPlatformOverride = previous; });
    final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger,calls = <services.MethodCall>[];
    messenger.setMockMethodCallHandler(NativeNetworkRuntime.channel,(call) async {
      calls.add(call); throw services.PlatformException(code:'overlay_provider_unavailable');
    });
    addTearDown(() => messenger.setMockMethodCallHandler(NativeNetworkRuntime.channel,null));
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final profile = testNetwork(),host = await saveCatalogProfile(catalog); await catalog.addNetwork(profile);
    final bound = host.change(networkProfileId:profile.id,replaceNetwork:true,now:1000); await catalog.update(bound);
    final tokens = (await tester.runAsync(DesignTokens.load))!,adapter = PendingAdapter();
    final keys = CountingDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:RemotePage(tokens:tokens,adapter:adapter,
      pairedTarget:bound.target,deviceKeys:keys,keyHandle:bound.pairingRecord['handle'] as String,
      devicePublicKey:fixtureConfig()['expectedHostKey'] as String,networkBinding:catalog.freezeNetwork(bound))));
    await tapVisible(tester,'remote-review'); await tapVisible(tester,'remote-connect'); await tester.pumpAndSettle();
    expect(calls.map((c) => c.method),['available']); expect(calls.single.arguments,{'provider':'tailscale'});
    expect(keys.publicCalls,0); expect(keys.signCalls,0); expect(adapter.calls,0);
    expect(find.textContaining('节点状态或连接桥不可确认'),findsOneWidget);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('320px Tailscale node and explicit browser authorization return to Running without SSH/input',(tester) async {
    tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(320,760);
    addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
    final storage = MemoryCatalogStorage();
    final catalog = HostCatalog(storage:storage,clock:() => 1000); await catalog.load();
    final profile = testNetwork(); await catalog.addNetwork(profile);
    final saved = storage.contents,writes = storage.writes;
    final runtime = TailscaleRuntimeFixture(profile),identities = TailscaleIdentityFixture();
    identities.record = NetworkIdentityRecord.checked(tailscaleIdentityReply(profile),profile);
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:NetworkProfilesPage(
      catalog:catalog,closeTabs:(_) {},identityStore:identities,runtime:runtime)));
    await tapVisible(tester,'network-node-refresh-${profile.id}'); await tester.pumpAndSettle();
    await tapVisible(tester,'network-node-start-${profile.id}'); await tester.pumpAndSettle();
    expect(find.text('节点：等待本设备授权'),findsOneWidget);
    expect(runtime.calls.where((c) => c.$1 == 'nodeLogin'),isEmpty);
    await tapVisible(tester,'network-node-login-${profile.id}'); await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('tailscale-login-url')),findsNothing);
    final authorize = find.byKey(const ValueKey('tailscale-login-authorize'));
    expect(tester.widget<FilledButton>(authorize).onPressed,isNull);
    await tapVisible(tester,'tailscale-login-review'); await tapVisible(tester,'tailscale-login-authorize');
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('tailscale-login-url')),findsOneWidget);
    expect(runtime.calls.where((c) => c.$1 == 'openLogin'),isEmpty);
    await tapVisible(tester,'tailscale-login-open'); await tester.pumpAndSettle();
    expect(runtime.calls.where((c) => c.$1 == 'openLogin').length,1);
    expect(find.byKey(const ValueKey('tailscale-login-url')),findsNothing);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive); await tester.pump();
    runtime.state = 'needs-machine-auth'; runtime.url = null; runtime.reviewToken = null;
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed); await tester.pumpAndSettle();
    expect(find.textContaining('等待网络管理员批准此设备'),findsWidgets);
    expect(runtime.calls.where((c) => c.$1 == 'nodeLogin').length,1);
    runtime.state = 'running'; await tapVisible(tester,'tailscale-login-refresh'); await tester.pumpAndSettle();
    expect(find.textContaining('回到主机列表'),findsOneWidget);
    await tapVisible(tester,'tailscale-login-close'); await tester.pumpAndSettle();
    expect(find.text('节点：Tailscale 已就绪 · SSH 与 herdr 仍需核验'),findsOneWidget);
    expect(runtime.calls.where((c) => c.$1 == 'nodeStart').length,1);
    expect(runtime.calls.where((c) => c.$1.startsWith('stream')),isEmpty);
    expect(storage.contents,saved); expect(storage.writes,writes);
    expect(storage.contents, isNot(contains('login.example.test')));
    expect(storage.contents, isNot(contains('reviewToken')));
    expect(identities.creates,0); expect(identities.deletes,0); expect(tester.takeException(),isNull);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('TS local identity UI creates DEVICE_STATE without a password field and removes only reviewed identity',(tester) async {
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final profile = testNetwork(); await catalog.addNetwork(profile);
    final runtime = TailscaleRuntimeFixture(profile),identities = TailscaleIdentityFixture();
    await tester.pumpWidget(MaterialApp(home:NetworkProfilesPage(
      catalog:catalog,closeTabs:(_) {},identityStore:identities,runtime:runtime)));
    await tapVisible(tester,'network-identity-${profile.id}'); await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('network-identity-secret')),findsNothing);
    expect(find.byKey(const ValueKey('network-identity-mode')),findsNothing);
    await tapVisible(tester,'network-identity-review'); await tapVisible(tester,'network-identity-create');
    await tester.pumpAndSettle();
    expect(identities.creates,1); expect(identities.record?.mode,'DEVICE_STATE');
    expect(find.text('模式：本机设备状态 · 原生加密保管'),findsOneWidget);
    expect(runtime.calls.where((c) => c.$1 == 'nodeStart' || c.$1 == 'nodeLogin'),isEmpty);
    await tapVisible(tester,'network-identity-delete'); await tester.pumpAndSettle();
    await tapVisible(tester,'network-identity-delete-confirm'); await tester.pumpAndSettle();
    expect(identities.deletes,1); expect(identities.record,isNull);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('unknown TS stop blocks public edit and disables new start until fresh Stopped read',(tester) async {
    final storage = MemoryCatalogStorage();
    final catalog = HostCatalog(storage:storage,clock:() => 1000);
    await catalog.load(); final profile = testNetwork(); await catalog.addNetwork(profile);
    final runtime = TailscaleRuntimeFixture(profile)..state = 'running'..failStop = true;
    final identities = TailscaleIdentityFixture();
    await tester.pumpWidget(MaterialApp(home:NetworkProfilesPage(
      catalog:catalog,closeTabs:(_) {},identityStore:identities,runtime:runtime)));
    await tapVisible(tester,'network-node-refresh-${profile.id}'); await tester.pumpAndSettle();
    final revision = catalog.revision,writes = storage.writes;
    await tapVisible(tester,'network-toggle-${profile.id}'); await tester.pumpAndSettle();
    await tapVisible(tester,'network-confirm'); await tester.pumpAndSettle();
    expect(catalog.revision,revision); expect(catalog.networkProfiles.single.enabled,isTrue);
    expect(runtime.calls.where((c) => c.$1 == 'nodeStop').length,1);
    expect(tester.widget<TextButton>(find.byKey(ValueKey('network-node-start-${profile.id}'))).onPressed,isNull);
    expect(storage.writes,writes);
    runtime.state = 'stopped'; await tapVisible(tester,'network-node-refresh-${profile.id}'); await tester.pumpAndSettle();
    expect(tester.widget<TextButton>(find.byKey(ValueKey('network-node-start-${profile.id}'))).onPressed,isNotNull);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('stale catalog review clears TS login link and cannot open old authorization',(tester) async {
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final profile = testNetwork(); await catalog.addNetwork(profile);
    final runtime = TailscaleRuntimeFixture(profile)..state = 'needs-login';
    final identities = TailscaleIdentityFixture();
    await identities.create(profile,'DEVICE_STATE',Uint8List(0));
    await tester.pumpWidget(MaterialApp(home:NetworkProfilesPage(
      catalog:catalog,closeTabs:(_) {},identityStore:identities,runtime:runtime)));
    await tapVisible(tester,'network-node-refresh-${profile.id}'); await tester.pumpAndSettle();
    await tapVisible(tester,'network-node-login-${profile.id}'); await tester.pumpAndSettle();
    await tapVisible(tester,'tailscale-login-review'); await tapVisible(tester,'tailscale-login-authorize'); await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('tailscale-login-url')),findsOneWidget);
    await catalog.addNetwork(testNetwork('zerotier')); await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('tailscale-login-url')),findsNothing);
    expect(find.byKey(const ValueKey('tailscale-login-open')),findsNothing);
    expect(runtime.calls.where((c) => c.$1 == 'openLogin'),isEmpty);
    expect(tester.takeException(),isNull); await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
}
