import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/pairing_page.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_tabs.dart';
import 'pairing_gui_test.dart' show TestDeviceKeys,tapVisible,fillPairTarget,acceptResponse,authorizedResponse;
import 'remote_test_data.dart';
import 'host_catalog_test.dart' show MemoryCatalogStorage;
import 'host_tabs_widget_test.dart' show tabProfile;
import 'host_task_summary_widget_test.dart' show SummaryWidgetAdapter,setup,connectHost;
import 'remote_page_test.dart' show PendingAdapter,prepare,field,fillRemoteFixture;

class DiagnosticAdapter extends PendingAdapter {
  RemoteProgress? progress;
  @override Future<RemoteSnapshot> observe(RemoteConfig config,{required DashboardConsumer onDashboard,
      required FrameConsumer onFrame,RemoteProgress? onProgress}) {
    final future=super.observe(config,onDashboard:onDashboard,onFrame:onFrame,onProgress:onProgress);
    progress=onProgress; progress?.call(generation,'connecting'); return future;
  }
  void step(String value) => progress!(generation,value);
}
class RetryDiagnosticAdapter extends PendingAdapter {
  final attempts=<Completer<RemoteSnapshot>>[];
  RemoteProgress? progress;
  @override Future<RemoteSnapshot> observe(RemoteConfig config,{required DashboardConsumer onDashboard,
      required FrameConsumer onFrame,RemoteProgress? onProgress}) {
    calls++; generation++; dashboard=onDashboard; frame=onFrame; progress=onProgress;
    final attempt=Completer<RemoteSnapshot>(); attempts.add(attempt);
    progress?.call(generation,'connecting'); return attempt.future;
  }
}
Future<void> connect(WidgetTester tester) async {
  await tester.ensureVisible(field('review')); await tester.tap(field('review')); await tester.pump();
  await tester.ensureVisible(field('connect')); await tester.tap(field('connect')); await tester.pump();
  final diagnostics=find.byKey(const ValueKey('remote-connection-diagnostics'));
  await tester.ensureVisible(diagnostics); await tester.tap(diagnostics); await tester.pump();
}
String row(WidgetTester tester,String name) => tester.widget<Text>(find.byKey(ValueKey('remote-diagnostic-$name'))).data!;
void main() {
  testWidgets('visible staged diagnosis records only callbacks and accepted full frame',(tester) async {
    final adapter=DiagnosticAdapter(); await prepare(tester,adapter,const Size(390,844)); await connect(tester);
    expect(row(tester,'network'),contains('目标连通尚未证实'));
    expect(row(tester,'host-key'),contains('尚未确认')); expect(row(tester,'first-frame'),contains('尚未确认'));
    adapter.step('snapshot'); await tester.pump();
    expect(row(tester,'host-key'),contains('已核验')); expect(row(tester,'authentication'),contains('已核验'));
    expect(row(tester,'dashboard'),contains('进行中'));
    adapter.step('snapshot_received'); adapter.publish(); await tester.pump();
    expect(row(tester,'dashboard'),contains('已核验')); expect(row(tester,'first-frame'),contains('尚未确认'));
    final pane=find.byKey(const ValueKey('remote-pane-w1:p1'));
    await tester.ensureVisible(pane); await tester.tap(pane); await tester.pump();
    adapter.step('observing'); adapter.step('full_received'); await tester.pump();
    expect(row(tester,'first-frame'),contains('进行中'));
    adapter.frame!(adapter.generation,'w1:p1',const RemoteFrame(0,true,'synthetic'));
    await tester.pump(); expect(row(tester,'first-frame'),contains('已核验'));
    await tester.pumpWidget(const SizedBox());
  });
  testWidgets('timeout does not claim host or authentication',(tester) async {
    final adapter=DiagnosticAdapter(); await prepare(tester,adapter,const Size(390,844)); await connect(tester);
    adapter.pending.completeError(const RemoteFailure('timeout')); await tester.pump(); await tester.pump();
    expect(row(tester,'network'),contains('结果未知')); expect(row(tester,'host-key'),contains('尚未确认'));
    expect(row(tester,'authentication'),contains('尚未确认'));
    expect(row(tester,'guidance'),contains('超时'));
    await tester.pumpWidget(const SizedBox());
  });
  testWidgets('a new explicit attempt clears prior success and ignores old progress',(tester) async {
    final adapter=RetryDiagnosticAdapter(); await prepare(tester,adapter,const Size(390,844)); await connect(tester);
    final oldProgress=adapter.progress!,oldGeneration=adapter.generation;
    oldProgress(oldGeneration,'snapshot'); await tester.pump();
    expect(row(tester,'authentication'),contains('已核验'));
    adapter.attempts.first.completeError(const RemoteFailure('timeout')); await tester.pump(); await tester.pump();
    await fillRemoteFixture(tester);
    await tester.ensureVisible(field('review')); await tester.tap(field('review')); await tester.pump();
    await tester.ensureVisible(field('connect')); await tester.tap(field('connect')); await tester.pump();
    expect(row(tester,'authentication'),contains('尚未确认'));
    oldProgress(oldGeneration,'snapshot_received'); await tester.pump();
    expect(row(tester,'dashboard'),contains('尚未确认')); expect(adapter.calls,2);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('new pairing route exposes diagnostics without a real SSH connection',(tester) async {
    final tokens=(await tester.runAsync(DesignTokens.load))!,adapter=DiagnosticAdapter();
    final keys=TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:PairingPage(tokens:tokens,keys:keys,adapter:adapter)));
    await fillPairTarget(tester,fixtureConfig()); await tapVisible(tester,'pair-target-review'); await tapVisible(tester,'pair-create');
    await tester.pumpAndSettle();
    final request=jsonDecode(tester.widget<SelectableText>(find.byKey(const ValueKey('pair-request'))).data!) as Map<String,dynamic>;
    await acceptResponse(tester,authorizedResponse(request)); await tapVisible(tester,'pair-connect'); await tester.pumpAndSettle();
    await tapVisible(tester,'remote-review'); await tapVisible(tester,'remote-connect');
    expect(find.byKey(const ValueKey('remote-connection-diagnostics')),findsOneWidget); expect(adapter.calls,1);
    await tester.pumpWidget(const SizedBox());
  });
  testWidgets('saved host route exposes diagnostics for its own new attempt',(tester) async {
    final catalog=HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final profile=tabProfile('Host','probe','127.0.0.1','direct','diagnostic'); await catalog.add(profile);
    final tabs=HostTabs(),adapters=<String,SummaryWidgetAdapter>{}; await setup(tester,catalog,tabs,adapters);
    final adapter=await connectHost(tester,profile,adapters);
    expect(find.byKey(const ValueKey('remote-connection-diagnostics')),findsOneWidget); expect(adapter.calls,1);
    await tester.pumpWidget(const SizedBox()); tabs.dispose(); catalog.dispose();
  });

}
