import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/host_tabs.dart';
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
  RemoteInputTarget? pausedTarget;
  RemoteDashboard? latestDashboard;
  int pauses = 0,resumes = 0;
  bool paused = false;
  @override
  Future<RemoteSnapshot> observe(RemoteConfig config,{required DashboardConsumer onDashboard,
      required FrameConsumer onFrame,RemoteProgress? onProgress}) {
    this.config = config; connection = Object(); onProgress?.call(generation+1,'snapshot');
    return super.observe(config,onDashboard:onDashboard,onFrame:onFrame,onProgress:onProgress);
  }
  @override
  void publish({bool empty=false}) {
    latestDashboard = RemoteDashboard(generation,config.session,
      empty ? const [] : const [RemotePane('w1:p1','term_abcd'),RemotePane('w1:p2','term_1234')],freshness:DashboardFreshness.fresh,revision:++boardRevision);
    dashboard!(latestDashboard!);
  }
  @override RemoteDashboard? get currentDashboard => latestDashboard;
  @override
  void selectPane(int expectedGeneration,String paneId) {
    super.selectPane(expectedGeneration,paneId);
    target = RemoteInputTarget(connection:connection,generation:expectedGeneration,host:config.host,port:config.port,
      username:config.username,hostFingerprint:config.expectedFingerprint,session:config.session,socketPath:config.socketPath,
      paneId:paneId,terminalId:paneId == 'w1:p1' ? 'term_abcd' : 'term_1234');
  }
  @override bool pauseObservation() {
    if (calls == 0) return false;
    if (!paused) { pauses++; paused = true; pausedTarget = target; target = null; }
    return true;
  }
  @override bool resumeObservation() {
    if (!paused) return false;
    paused = false; resumes++; final old = pausedTarget;
    if (old != null) target = RemoteInputTarget(connection:connection,generation:old.generation,host:old.host,port:old.port,
      username:old.username,hostFingerprint:old.hostFingerprint,session:old.session,socketPath:old.socketPath,paneId:old.paneId,terminalId:old.terminalId,route:old.route);
    return true;
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
Future<void> connectTab(WidgetTester tester,TabFixtureAdapter adapter,{String pane='w1:p1'}) async {
  await tapVisible(tester,'remote-review'); await tapVisible(tester,'remote-connect');
  adapter.publish(); await tester.pump(); await tapVisible(tester,'remote-pane-$pane');
  adapter.frame!(adapter.generation,pane,const RemoteFrame(0,true,'SYNTHETIC TAB FULL'));
  await tester.pump();
}
void main() {
  testWidgets('MT01 MT02 MT03 MT05 UI double: views stay independent and resume only by explicit new full',(tester) async {
    tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(390,844);
    addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final a = tabProfile('Host A','probeA','127.0.0.1','tailscale','opaque-a');
    final b = tabProfile('Host B','probeB','127.0.0.2','easytier','opaque-b');
    await catalog.add(a); await catalog.add(b);
    final adapters = <String,List<TabFixtureAdapter>>{},tabs = HostTabs(), tokens = (await tester.runAsync(DesignTokens.load))!;
    final keys = TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:HostCatalogPage(tokens:tokens,catalog:catalog,keys:keys,tabs:tabs,
      adapterFactory:(p) { final adapter = TabFixtureAdapter(); (adapters[p.id] ??= []).add(adapter); return adapter; },offlineBuilder:(_) => const SizedBox())));
    await tester.pumpAndSettle(); await tapVisible(tester,'host-open-${a.id}'); await tester.pumpAndSettle();
    final aTab = tabs.active!.id,aAdapter = adapters[a.id]!.single;
    await tapVisible(tester,'pair-connect'); await tester.pumpAndSettle();
    await connectTab(tester,aAdapter); await mode(tester,'draft');
    final draft = find.byKey(const ValueKey('remote-input-draft'));
    await tester.ensureVisible(draft); await tester.enterText(draft,'Host A unsent'); await tester.pump();
    final oldGeneration = aAdapter.generation;
    await tapVisible(tester,'hosts-board-tab');
    expect(aAdapter.pauses,1); expect(aAdapter.cancels,0);
    aAdapter.frame!(oldGeneration,'w1:p1',const RemoteFrame(1,false,'LATE FROM HIDDEN A'));
    await tapVisible(tester,'host-open-${b.id}'); await tester.pumpAndSettle();
    final bTab = tabs.active!.id,bAdapter = adapters[b.id]!.single;
    await tapVisible(tester,'pair-connect'); await tester.pumpAndSettle(); await connectTab(tester,bAdapter);
    expect(bAdapter.config.session,'probeB'); expect(aAdapter.config.session,'probeA');
    expect(identical(aAdapter,bAdapter),isFalse);
    await mode(tester,'draft'); await tester.ensureVisible(draft); await tester.enterText(draft,'Host B unsent');
    await tapVisible(tester,'host-tab-$aTab'); await tester.pump();
    expect(aAdapter.calls,1); expect(bAdapter.pauses,1); expect(bAdapter.cancels,0);
    expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-observe'))).selected,isTrue);
    expect(aAdapter.resumes,0); await tapVisible(tester,'remote-resume');
    expect(aAdapter.resumes,1); expect(find.textContaining('LATE FROM HIDDEN A'),findsNothing);
    await tapVisible(tester,'hosts-board-tab'); await tapVisible(tester,'host-tab-$aTab');
    expect(aAdapter.pauses,2); await tapVisible(tester,'remote-resume'); expect(aAdapter.resumes,2);
    aAdapter.frame!(aAdapter.generation,'w1:p1',const RemoteFrame(0,true,'LATE OLD FULL',observationEpoch:1)); await tester.pump();
    expect(find.textContaining('LATE OLD FULL'),findsNothing);
    aAdapter.frame!(aAdapter.generation,'w1:p1',const RemoteFrame(0,true,'NEW SAME TARGET FULL',observationEpoch:2)); await tester.pump(); await mode(tester,'draft');
    expect(tester.widget<TextField>(draft).controller!.text,'Host A unsent');
    expect(aAdapter.calls,1); expect(bAdapter.calls,1); expect(keys.creates,0); expect(keys.signCalls,0);
    // A terminal full does not refresh the board: the watch publishes its
    // own fresh snapshot before a new pane can be opened.
    aAdapter.publish(); await tester.pump();
    await tapVisible(tester,'remote-pane-new-tab-w1:p2'); await tester.pumpAndSettle();
    final secondATab = tabs.active!.id,secondA = adapters[a.id]!.last;
    expect(secondATab,isNot(aTab)); expect(tabs.forHost(a.id).length,2);
    expect(secondA.calls,0); // Opening a pane view never authenticates automatically.
    await tapVisible(tester,'pair-connect'); await tester.pumpAndSettle();
    await tapVisible(tester,'remote-review'); await tapVisible(tester,'remote-connect');
    secondA.publish(); await tester.pump();
    expect(secondA.selected,'w1:p2');
    secondA.frame!(secondA.generation,'w1:p2',const RemoteFrame(0,true,'SECOND TARGET FULL')); await tester.pump();
    await tapVisible(tester,'host-tab-close-$aTab');
    expect(find.byKey(ValueKey('host-tab-$aTab')),findsNothing);
    expect(find.byKey(ValueKey('host-tab-$bTab')),findsOneWidget);
    expect(tabs.active!.id,secondATab); expect(secondA.cancels,0);
    await tapVisible(tester,'hosts-board-tab');
    expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('hosts-board-tab'))).selected,isTrue);
    expect(bAdapter.calls,1); // Closing A must not resume B.
    // The list retains its previous scroll position. Its lazy children above
    // that position need scrolling back into view before they can be found.
    final board = find.byType(ListView);
    expect(board,findsOneWidget);
    final status = find.byKey(const ValueKey('hosts-status'));
    await tester.scrollUntilVisible(status,-300,
      scrollable:find.descendant(of:board,matching:find.byType(Scrollable)));
    expect(status,findsOneWidget);
    expect(tester.takeException(),isNull); await tester.pumpWidget(const SizedBox()); tabs.dispose(); catalog.dispose();
  });
}
