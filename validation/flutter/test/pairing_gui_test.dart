import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'package:dartssh2/dartssh2.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/device_keys.dart';
import 'package:herdr_flutter_probe/pairing.dart';
import 'package:herdr_flutter_probe/pairing_page.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'remote_test_data.dart';

/// Explicit test double only. Never selected by production code or platform fallback.
class TestDeviceKeys implements DeviceKeys {
  TestDeviceKeys(String pem) : key = SSHKeyPair.fromPem(pem).single;
  final SSHKeyPair key;
  bool locked = false, deleted = false;
  int signCalls = 0, creates = 0;
  void ready() { if (locked || deleted) throw StateError('test storage unavailable'); }
  @override
  Future<String> create() async { ready(); creates++; return 'test-opaque-handle'; }
  @override
  Future<String> public(String handle) async { ready(); return 'ssh-ed25519 ${base64Encode(key.toPublicKey().encode())}'; }
  @override
  Future<Uint8List> sign(String handle,Uint8List payload) async {
    ready(); signCalls++;
    final encoded = key.sign(payload).encode();
    return Uint8List.fromList(encoded.sublist(19));
  }
  @override
  Future<void> delete(String handle) async { ready(); deleted = true; }
}
class GuiMemoryAdapter extends RemoteReadOnlyAdapter {
  final pending = Completer<RemoteSnapshot>();
  DashboardConsumer? board; FrameConsumer? frame;
  String? chosen;
  int calls = 0;
  @override
  Future<RemoteSnapshot> observe(RemoteConfig config,{required DashboardConsumer onDashboard,
    required FrameConsumer onFrame,RemoteProgress? onProgress}) {
    expect(config.privateKeyPem,isEmpty); expect(config.deviceIdentity,isNotNull);
    calls++; generation++; board = onDashboard; frame = onFrame;
    onProgress?.call(generation,'snapshot');
    onDashboard(RemoteDashboard(generation,'probe',const [RemotePane('w1:p1','term_abcd')],freshness:DashboardFreshness.fresh));
    return pending.future;
  }
  @override
  void selectTarget(int expectedGeneration,RemotePane target) { selectPane(expectedGeneration,target.paneId); }
  @override
  void selectPane(int expectedGeneration,String paneId) {
    chosen = paneId;
    frame!(generation,paneId,const RemoteFrame(1,true,'MEMORY UI FULL'));
    frame!(generation,paneId,const RemoteFrame(2,false,'MEMORY UI DELTA'));
  }
  @override
  Future<void> cancel() async { generation++; }
}
Future<void> tapVisible(WidgetTester tester,String key) async {
  final f = find.byKey(ValueKey(key)); await tester.ensureVisible(f); await tester.pumpAndSettle();
  await tester.tap(f); await tester.pump();
}
Future<void> fillPairTarget(WidgetTester tester,Map<String,dynamic> values) async {
  for (final entry in values.entries) {
    final f = find.byKey(ValueKey('pair-${entry.key}'));
    if (f.evaluate().isEmpty) continue;
    await tester.ensureVisible(f); await tester.enterText(f,entry.value.toString()); await tester.pump();
  }
}
Map<String,dynamic> authorizedResponse(Map<String,dynamic> request) => {
  'version':2,'type':'pairing-binding-response','request_id':request['request_id'],
  'account':request['account'],'host_key':request['host_key'],'issued_at':request['issued_at'],
  'expires_at':request['expires_at'],'fingerprint':pairingFingerprint(request['public_key'] as String),
  'status':'authorized','authorization_added':true,
};
Future<void> acceptResponse(WidgetTester tester,Map<String,dynamic> response) async {
  final f = find.byKey(const ValueKey('pair-response')); await tester.ensureVisible(f);
  await tester.enterText(f,jsonEncode(response)); await tester.pump();
  await tapVisible(tester,'pair-source-review'); await tapVisible(tester,'pair-accept');
}
void main() {
  setUp(PairingPage.resetMemorySession);
  tearDown(PairingPage.resetMemorySession);
  testWidgets('memory double UI: public review -> board -> explicit observe -> stale; not SSH evidence',(tester) async {
    tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(390,844);
    addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
    final config = fixtureConfig(); final keys = TestDeviceKeys(config['privateKeyPem'] as String);
    final adapter = GuiMemoryAdapter(); Map<String,dynamic>? request;
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:PairingPage(tokens:tokens,keys:keys,adapter:adapter,
      onRequest:(r) { request = r; },clock:() => 1000)));
    await fillPairTarget(tester,{...config,'username':'fixture_user'});
    await tapVisible(tester,'pair-target-review'); await tapVisible(tester,'pair-create'); await tester.pump();
    expect(request,isNotNull); expect(keys.creates,1); expect(request!.containsKey('privateKeyPem'),isFalse);
    final response = authorizedResponse(request!);
    await acceptResponse(tester,{...response,'account':'other'});
    expect(find.textContaining('响应无效'),findsOneWidget);
    await acceptResponse(tester,response);
    expect(find.textContaining('authorized-unverified'),findsOneWidget);
    await tapVisible(tester,'pair-connect'); await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('remote-privateKeyPem')),findsNothing);
    await tapVisible(tester,'remote-review'); await tapVisible(tester,'remote-connect'); await tester.pump();
    expect(adapter.chosen,isNull);
    await tapVisible(tester,'remote-pane-w1:p1');
    expect(find.textContaining('只读观察中'),findsOneWidget);
    await tapVisible(tester,'remote-cancel');
    expect(find.textContaining('旧画面 · 已停止'),findsOneWidget); expect(adapter.calls,1);
    expect(keys.signCalls,0); // Fake transport did not authenticate; never call this SSH evidence.
    await tester.pumpWidget(const SizedBox());
  });
  testWidgets('locked device store stops explicit identity creation without fallback',(tester) async {
    final keys = TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String)..locked = true;
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:PairingPage(tokens:tokens,keys:keys)));
    await fillPairTarget(tester,{...fixtureConfig(),'username':'fixture_user'});
    await tapVisible(tester,'pair-target-review'); await tapVisible(tester,'pair-create');
    expect(find.textContaining('设备安全存储不可用'),findsOneWidget);
    expect(keys.creates,0); expect(find.byKey(const ValueKey('pair-request')),findsNothing);
    await tester.pumpWidget(const SizedBox());
  });
}
