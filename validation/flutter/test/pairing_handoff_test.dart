import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/pairing_page.dart';
import 'pairing_gui_test.dart' show TestDeviceKeys,fillPairTarget,tapVisible,authorizedResponse,acceptResponse;
import 'remote_test_data.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const android = TargetPlatformVariant({TargetPlatform.android});
  const channel = MethodChannel('herdr.pocket/pair_scan');
  final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  setUp(PairingPage.resetMemorySession);
  tearDown(() { messenger.setMockMethodCallHandler(channel,null); messenger.setMockMethodCallHandler(SystemChannels.platform,null); PairingPage.resetMemorySession(); });
  Future<Map<String,dynamic>> prepare(WidgetTester tester,int Function() clock) async {
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    Map<String,dynamic>? request;
    await tester.pumpWidget(MaterialApp(home:PairingPage(tokens:tokens,clock:clock,
      keys:TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String),onRequest:(value) { request = value; })));
    await fillPairTarget(tester,fixtureConfig()); await tapVisible(tester,'pair-target-review'); await tapVisible(tester,'pair-create');
    return request!;
  }
  Map<String,dynamic> revoked(Map<String,dynamic> request,int time) => {...authorizedResponse(request),
    'status':'revoked','issued_at':time,'expires_at':time+600};
  testWidgets('copy is exact public request, failures retain manual selection; expiry prevents late success',(tester) async {
    var now = 1000; final request = await prepare(tester,() => now);
    final raw = tester.widget<SelectableText>(find.byKey(const ValueKey('pair-request'))).data!;
    expect(jsonDecode(raw),request); expect(raw.contains('privateKeyPem'),isFalse); expect(raw.contains('test-opaque-handle'),isFalse);
    expect(tester.widget<SelectableText>(find.byKey(const ValueKey('pair-handoff-summary'))).data,contains(request['request_id']));
    final pending = Completer<Object?>();
    messenger.setMockMethodCallHandler(SystemChannels.platform,(call) { if (call.method == 'Clipboard.setData') { expect(call.arguments['text'],raw); return pending.future; } return Future.value(null); });
    await tapVisible(tester,'pair-copy'); now = 1600; await tester.pump(const Duration(seconds:1));
    pending.complete(null); await tester.pump();
    expect(find.textContaining('公开请求已复制'),findsNothing);
    expect(find.byKey(const ValueKey('pair-request')),findsNothing);
    expect(tester.widget<TextButton>(find.byKey(const ValueKey('pair-copy'))).onPressed,isNull);
    await tester.pumpWidget(const SizedBox());
  },variant:android);
  testWidgets('clipboard failure gives manual fallback for the same still valid request',(tester) async {
    final request = await prepare(tester,() => 1000);
    messenger.setMockMethodCallHandler(SystemChannels.platform,(call) async { if (call.method == 'Clipboard.setData') throw PlatformException(code:'unavailable'); return null; });
    await tapVisible(tester,'pair-copy'); await tester.pump();
    expect(find.textContaining('可手动选择下方公开请求全文'),findsOneWidget);
    expect(jsonDecode(tester.widget<SelectableText>(find.byKey(const ValueKey('pair-request'))).data!),request);
    await tester.pumpWidget(const SizedBox());
  },variant:android);
  testWidgets('cancelled request rejects late authorization but accepts fresh matching manual revocation',(tester) async {
    final request = await prepare(tester,() => 1000);
    await tapVisible(tester,'pair-cancel');
    await acceptResponse(tester,authorizedResponse(request)); await tester.pump();
    expect(find.textContaining('authorized-unverified'),findsNothing); expect(find.byKey(const ValueKey('pair-connect')),findsNothing);
    await acceptResponse(tester,revoked(request,1000)); await tester.pump();
    expect(find.textContaining('revoked'),findsOneWidget); expect(find.byKey(const ValueKey('pair-connect')),findsNothing);
    await tester.pumpWidget(const SizedBox());
  },variant:android);
  testWidgets('expired request can scan and review a fresh revocation without creating another identity',(tester) async {
    var time = 1000; final request = await prepare(tester,() => time); time = 1600; await tester.pump(const Duration(seconds:1));
    final record = revoked(request,time);
    messenger.setMockMethodCallHandler(channel,(_) async => jsonEncode(record));
    await tapVisible(tester,'pair-scan'); await tester.pump();
    expect(find.byKey(const ValueKey('pair-response-preview')),findsOneWidget);
    expect(tester.widget<CheckboxListTile>(find.byKey(const ValueKey('pair-source-review'))).value,isFalse);
    await tapVisible(tester,'pair-source-review'); await tapVisible(tester,'pair-accept'); await tester.pump();
    expect(find.textContaining('revoked'),findsOneWidget); expect(find.byKey(const ValueKey('pair-connect')),findsNothing);
    await tester.pumpWidget(const SizedBox());
  },variant:android);
  testWidgets('authorized identity rejects mismatched revocation, then accepts matching one',(tester) async {
    final request = await prepare(tester,() => 1000);
    await acceptResponse(tester,authorizedResponse(request)); await tester.pump();
    expect(find.byKey(const ValueKey('pair-connect')),findsOneWidget);
    await acceptResponse(tester,{...revoked(request,1000),'account':'wrong'}); await tester.pump();
    expect(find.textContaining('不匹配'),findsOneWidget);
    expect(find.textContaining('authorized-unverified'),findsOneWidget);
    await acceptResponse(tester,revoked(request,1000)); await tester.pump();
    expect(find.textContaining('revoked'),findsOneWidget);
    expect(find.byKey(const ValueKey('pair-connect')),findsNothing);
    await tester.pumpWidget(const SizedBox());
  },variant:android);

}
