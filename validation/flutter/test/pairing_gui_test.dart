import 'dart:async';
import 'dart:convert';
import 'package:dartssh2/dartssh2.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:terminal_view/terminal_view.dart';
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
  int frameCols = 80,frameRows = 24;
  RemoteConfig? observedConfig;
  @override
  Future<RemoteSnapshot> observe(RemoteConfig config,{required DashboardConsumer onDashboard,
    required FrameConsumer onFrame,RemoteProgress? onProgress}) {
    expect(config.privateKeyPem,isEmpty); expect(config.deviceIdentity,isNotNull);
    observedConfig = config;
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
    frame!(generation,paneId,RemoteFrame(1,true,'MEMORY UI FULL',cols:frameCols,rows:frameRows));
    frame!(generation,paneId,RemoteFrame(2,false,'MEMORY UI DELTA',cols:frameCols,rows:frameRows));
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
  testWidgets('pairing labels identify the editable fields and expose the full reviewed fingerprint', (tester) async {
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    final config = fixtureConfig();
    final keys = TestDeviceKeys(config['privateKeyPem'] as String);
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:PairingPage(tokens:tokens,keys:keys)));
    const labels = {'host':'SSH 主机 / IP', 'port':'SSH 端口', 'username':'主机账号',
      'session':'命名会话（非 default）', 'socketPath':'命名会话 socket 绝对路径',
      'herdrPath':'herdr 可执行文件绝对路径', 'expectedHostKey':'可信渠道核验的 Ed25519 主机公钥',
      'device':'设备名称（英文、数字、空格）'};
    final macos = defaultTargetPlatform == TargetPlatform.macOS;
    for (final entry in labels.entries) {
      final field = find.byKey(ValueKey('pair-${entry.key}'));
      await tester.ensureVisible(field);
      await tester.pumpAndSettle();
      expect(field.hitTestable(), findsOneWidget);
      final editable = tester.getSemantics(find.descendant(of:field,matching:find.byType(EditableText)));
      final named = <SemanticsNode>[];
      bool collect(SemanticsNode node) {
        if (node.getSemanticsData().label == entry.value) named.add(node);
        node.visitChildren(collect);
        return true;
      }
      collect(tester.binding.renderViews.first.owner!.semanticsOwner!.rootSemanticsNode!);
      expect(named, hasLength(1), reason:entry.key);
      if (macos) {
        expect(named.single, editable.parent, reason:entry.key);
        expect(editable.getSemanticsData().label, isEmpty);
      } else {
        expect(named.single, editable, reason:entry.key);
      }
      expect(editable.getSemanticsData().flagsCollection.isTextField, isTrue);
      expect(editable.getSemanticsData().flagsCollection.isReadOnly, isFalse);
    }

    final key = find.byKey(const ValueKey('pair-expectedHostKey'));
    await tester.ensureVisible(key);
    await tester.enterText(key,config['expectedHostKey'] as String);
    await tester.pumpAndSettle();
    final fingerprint = find.byKey(const ValueKey('pair-target-fingerprint'));
    await tester.ensureVisible(fingerprint);
    await tester.pumpAndSettle();
    final visibleFingerprint = tester.getSemantics(
      find.descendant(of:fingerprint,matching:find.byType(EditableText))).getSemanticsData();
    expect(visibleFingerprint.flagsCollection.isReadOnly, isTrue);
    expect(visibleFingerprint.value, pairingFingerprint(config['expectedHostKey'] as String));
    expect(keys.creates,0);
  }, variant:const TargetPlatformVariant({TargetPlatform.macOS,TargetPlatform.android,TargetPlatform.iOS}));

  for (final width in [320.0,390.0]) {
    testWidgets('first pairing at ${width}px ends editing and checks the actual target checkbox once before create',(tester) async {
      tester.view.devicePixelRatio = 1; tester.view.physicalSize = Size(width,844);
      addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
      final config = fixtureConfig(),keys = TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
      final tokens = (await tester.runAsync(DesignTokens.load))!;
      await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:PairingPage(tokens:tokens,keys:keys,clock:() => 1000)));
      final names = ['host','port','username','session','socketPath','herdrPath','expectedHostKey'];
      for (final name in names) {
        final field = find.byKey(ValueKey('pair-$name')); await tester.ensureVisible(field);
        await tester.enterText(field,config[name].toString()); await tester.pump();
      }
      final original = {for (final name in names) name:tester.widget<TextField>(find.byKey(ValueKey('pair-$name'))).controller!.text};
      expect(keys.creates,0);
      await tester.testTextInput.receiveAction(TextInputAction.done); await tester.pumpAndSettle();
      final tile = find.byKey(const ValueKey('pair-target-review'));
      final checkbox = find.descendant(of:tile,matching:find.byType(Checkbox));
      await tester.ensureVisible(checkbox); await tester.pumpAndSettle();
      expect(checkbox.hitTestable(),findsOneWidget); expect(tester.widget<Checkbox>(checkbox).value,isFalse);
      expect(tester.widget<FilledButton>(find.byKey(const ValueKey('pair-create'))).onPressed,isNull);
      await tester.tap(checkbox.hitTestable()); await tester.pumpAndSettle();
      expect(tester.widget<Checkbox>(checkbox).value,isTrue);
      for (final entry in original.entries) {
        expect(tester.widget<TextField>(find.byKey(ValueKey('pair-${entry.key}'))).controller!.text,entry.value);
      }
      expect(tester.widget<FilledButton>(find.byKey(const ValueKey('pair-create'))).onPressed,isNotNull);
      await tapVisible(tester,'pair-create'); expect(keys.creates,1);
      expect(tester.takeException(),isNull); await tester.pumpWidget(const SizedBox());
    });
  }
  testWidgets('memory double UI: public review -> board -> explicit observe -> stale; not SSH evidence',(tester) async {
    tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(390,844);
    addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
    final config = fixtureConfig(); final keys = TestDeviceKeys(config['privateKeyPem'] as String);
    final adapter = GuiMemoryAdapter()..frameCols = 119..frameRows = 40; Map<String,dynamic>? request;
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
    await tapVisible(tester,'remote-canvas-size'); await tester.pumpAndSettle();
    await tester.tap(find.text('120×40').last); await tester.pumpAndSettle();
    await tapVisible(tester,'remote-review'); await tapVisible(tester,'remote-connect'); await tester.pump();
    expect(adapter.observedConfig!.observationCols,120); expect(adapter.observedConfig!.observationRows,40);
    expect(adapter.observedConfig!.observeCommand('term_abcd'),endsWith('--cols 120 --rows 40'));
    expect(adapter.chosen,isNull);
    await tapVisible(tester,'remote-pane-w1:p1');
    expect(find.textContaining('只读观察中'),findsOneWidget);
    final actual = tester.widget<TerminalView>(find.byType(TerminalView)).terminal;
    expect(actual.viewWidth,119); expect(actual.viewHeight,40);
    expect(find.textContaining('观察画布 119×40'),findsOneWidget);
    expect(tester.widget<DropdownButtonFormField<int>>(find.byKey(const ValueKey('remote-canvas-size'))).onChanged,isNull);
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
