import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/pairing.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'package:herdr_flutter_probe/remote_input.dart';
import 'host_catalog_test.dart' show MemoryCatalogStorage;
import 'pairing_gui_test.dart' show TestDeviceKeys,tapVisible,authorizedResponse;
import 'remote_page_test.dart' show PendingAdapter;
import 'remote_input_widget_test.dart' show mode;
import 'remote_test_data.dart';
import 'dart:convert';

/// Explicit UI test transport; does not claim network, SSH or system-store proof.
class TabFixtureAdapter extends PendingAdapter {
  late RemoteConfig config;
  Object connection = Object();
  RemoteInputTarget? target;
  @override
  Future<RemoteSnapshot> observe(RemoteConfig config,{required DashboardConsumer onDashboard,
      required FrameConsumer onFrame,RemoteProgress? onProgress}) {
    this.config = config; connection = Object(); onProgress?.call(generation+1,'snapshot');
    return super.observe(config,onDashboard:onDashboard,onFrame:onFrame,onProgress:onProgress);
  }
  @override
  void publish({bool empty=false}) => dashboard!(RemoteDashboard(generation,config.session,
    empty ? const [] : const [RemotePane('w1:p1','term_abcd')]));
  @override
  void selectPane(int expectedGeneration,String paneId) {
    super.selectPane(expectedGeneration,paneId);
    target = RemoteInputTarget(connection:connection,generation:expectedGeneration,host:config.host,port:config.port,
      username:config.username,hostFingerprint:config.expectedFingerprint,session:config.session,socketPath:config.socketPath,
      paneId:paneId,terminalId:'term_abcd');
  }
  @override RemoteInputTarget? get inputTarget => target;
  @override RemoteInputCapability? get inputCapability => const RemoteInputCapability(4096);
}
HostProfile tabProfile(String label,String session,String host,String provider,String handle) {
  final config = fixtureConfig(), public = fixtureConfig()['expectedHostKey'] as String;
  final pairing = PendingDevicePairing(handle:handle,publicKey:public,account:config['username'] as String,
    hostKey:pairingFingerprint(public),device:'UI test phone',now:1000);
  pairing.accept(jsonEncode(authorizedResponse(pairing.request)),now:1000,reviewed:true);
  return HostProfile.create(label,{...config,'host':host,'session':session,
    'socketPath':'/tmp/fixture-config/herdr/sessions/$session/herdr.sock'},pairing,1000,provider:provider);
}
Future<void> connectTab(WidgetTester tester,TabFixtureAdapter adapter) async {
  await tapVisible(tester,'remote-review'); await tapVisible(tester,'remote-connect');
  adapter.publish(); await tester.pump(); await tapVisible(tester,'remote-pane-w1:p1');
  adapter.frame!(adapter.generation,'w1:p1',const RemoteFrame(0,true,'SYNTHETIC TAB FULL'));
  await tester.pump();
}
void main() {
  testWidgets('normal mobile host tabs isolate sessions and unsent drafts; hidden tabs stop and require explicit new full',(tester) async {
    tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(390,844);
    addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final a = tabProfile('Host A','probeA','127.0.0.1','tailscale','opaque-a');
    final b = tabProfile('Host B','probeB','127.0.0.2','easytier','opaque-b');
    await catalog.add(a); await catalog.add(b);
    final adapters = <String,TabFixtureAdapter>{}, tokens = (await tester.runAsync(DesignTokens.load))!;
    final keys = TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:HostCatalogPage(tokens:tokens,catalog:catalog,keys:keys,
      adapterFactory:(p) => adapters[p.id] = TabFixtureAdapter(),offlineBuilder:(_) => const SizedBox())));
    await tester.pumpAndSettle(); await tapVisible(tester,'host-open-${a.id}'); await tester.pumpAndSettle();
    await tapVisible(tester,'pair-connect'); await tester.pumpAndSettle();
    await connectTab(tester,adapters[a.id]!); await mode(tester,'draft');
    final draft = find.byKey(const ValueKey('remote-input-draft'));
    await tester.ensureVisible(draft); await tester.enterText(draft,'Host A unsent'); await tester.pump();
    final oldGeneration = adapters[a.id]!.generation;
    await tapVisible(tester,'hosts-board-tab');
    expect(adapters[a.id]!.cancels,greaterThan(0));
    adapters[a.id]!.frame!(oldGeneration,'w1:p1',const RemoteFrame(1,false,'LATE FROM HIDDEN A'));
    await tapVisible(tester,'host-open-${b.id}'); await tester.pumpAndSettle();
    await tapVisible(tester,'pair-connect'); await tester.pumpAndSettle(); await connectTab(tester,adapters[b.id]!);
    expect(adapters[b.id]!.config.session,'probeB'); expect(adapters[a.id]!.config.session,'probeA');
    expect(identical(adapters[a.id],adapters[b.id]),isFalse);
    await mode(tester,'draft'); await tester.ensureVisible(draft); await tester.enterText(draft,'Host B unsent');
    await tapVisible(tester,'host-tab-${a.id}'); await tester.pump();
    expect(adapters[a.id]!.calls,1); expect(adapters[b.id]!.cancels,greaterThan(0));
    expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-observe'))).selected,isTrue);
    await connectTab(tester,adapters[a.id]!); await mode(tester,'draft');
    expect(tester.widget<TextField>(draft).controller!.text,'Host A unsent');
    expect(adapters[a.id]!.calls,2); expect(adapters[b.id]!.calls,1); expect(keys.creates,0); expect(keys.signCalls,0);
    expect(find.textContaining('入网状态未知'),findsWidgets);
    await tapVisible(tester,'host-tab-close-${a.id}');
    expect(find.byKey(ValueKey('host-tab-${b.id}')),findsOneWidget); expect(find.byKey(const ValueKey('hosts-status')),findsOneWidget);
    expect(tester.takeException(),isNull); await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
}
