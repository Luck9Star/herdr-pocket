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
  setUp(PairingPage.resetMemorySession); tearDown(PairingPage.resetMemorySession);
  final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  const android = TargetPlatformVariant({TargetPlatform.android});
  Future<Map<String,dynamic>> prepare(WidgetTester tester,ValueNotifier<bool> visibility,int Function() clock) async {
    expect(defaultTargetPlatform,TargetPlatform.android);
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    Map<String,dynamic>? request;
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:PairingPage(tokens:tokens,
      keys:TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String),visibility:visibility,clock:clock,onRequest:(value) { request = value; })));
    await fillPairTarget(tester,{...fixtureConfig(),'username':'fixture_user'});
    await tapVisible(tester,'pair-target-review'); await tapVisible(tester,'pair-create'); await tester.pump();
    return request!;
  }
  void resumed(WidgetTester tester) {
    final path = switch (tester.binding.lifecycleState) {
      AppLifecycleState.paused => const [AppLifecycleState.hidden,AppLifecycleState.inactive,AppLifecycleState.resumed],
      AppLifecycleState.hidden => const [AppLifecycleState.inactive,AppLifecycleState.resumed],
      AppLifecycleState.inactive => const [AppLifecycleState.resumed],
      AppLifecycleState.resumed => const <AppLifecycleState>[],
      _ => const [AppLifecycleState.resumed],
    };
    for (final state in path) { tester.binding.handleAppLifecycleStateChanged(state); }
  }
  testWidgets('own camera pause preserves request; scanned text only enters unreviewed manual preview',(tester) async {
    final visibility = ValueNotifier(true), pending = Completer<Object?>();
    final request = await prepare(tester,visibility,() => 1000);
    messenger.setMockMethodCallHandler(const MethodChannel('herdr.pocket/pair_scan'),(call) {
      expect(call.method,'scan'); return pending.future;
    });
    addTearDown(() { messenger.setMockMethodCallHandler(const MethodChannel('herdr.pocket/pair_scan'),null); resumed(tester); visibility.dispose(); });
    await tapVisible(tester,'pair-scan'); resumed(tester);
    for (final state in [AppLifecycleState.inactive,AppLifecycleState.hidden,AppLifecycleState.paused]) {
      tester.binding.handleAppLifecycleStateChanged(state);
    }
    pending.complete(jsonEncode(authorizedResponse(request))); resumed(tester); await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('pair-response-preview')),findsOneWidget);
    expect(tester.widget<CheckboxListTile>(find.byKey(const ValueKey('pair-source-review'))).value,isFalse);
    expect(find.byKey(const ValueKey('pair-connect')),findsNothing);
    expect(find.textContaining('awaiting-host'),findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  },variant:android);
  testWidgets('background clipboard round trip keeps the same pending request and requires fresh source review',(tester) async {
    final visibility = ValueNotifier(true);
    addTearDown(visibility.dispose);
    final request = await prepare(tester,visibility,() => 1000);
    final review = find.byKey(const ValueKey('pair-source-review'));
    await tapVisible(tester,'pair-source-review');
    resumed(tester);
    for (final state in [AppLifecycleState.inactive,AppLifecycleState.hidden,AppLifecycleState.paused]) {
      tester.binding.handleAppLifecycleStateChanged(state);
    }
    resumed(tester); await tester.pump();
    final public = tester.widget<SelectableText>(find.byKey(const ValueKey('pair-request')));
    expect(jsonDecode(public.data!),request);
    expect(tester.widget<CheckboxListTile>(review).value,isFalse);
    expect(find.textContaining('awaiting-host'),findsOneWidget);
    expect(find.byKey(const ValueKey('pair-connect')),findsNothing);
    await acceptResponse(tester,authorizedResponse(request));
    expect(find.textContaining('authorized-unverified'),findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  },variant:android);
  testWidgets('hidden-tab late scan cannot refill response or trust; return never accepts it',(tester) async {
    final visibility = ValueNotifier(true), pending = Completer<Object?>();
    final request = await prepare(tester,visibility,() => 1000);
    messenger.setMockMethodCallHandler(const MethodChannel('herdr.pocket/pair_scan'),(_) => pending.future);
    addTearDown(() { messenger.setMockMethodCallHandler(const MethodChannel('herdr.pocket/pair_scan'),null); visibility.dispose(); });
    await tapVisible(tester,'pair-scan'); visibility.value = false;
    pending.complete(jsonEncode(authorizedResponse(request))); await tester.pump(); visibility.value = true; await tester.pump();
    expect(tester.widget<TextField>(find.byKey(const ValueKey('pair-response'))).controller!.text,isEmpty);
    expect(find.byKey(const ValueKey('pair-response-preview')),findsNothing); expect(find.byKey(const ValueKey('pair-connect')),findsNothing);
    await tester.pumpWidget(const SizedBox());
  },variant:android);
  testWidgets('denied camera keeps manual path; expired request cannot launch another scan',(tester) async {
    final visibility = ValueNotifier(true); var time = 1000, calls = 0;
    await prepare(tester,visibility,() => time);
    messenger.setMockMethodCallHandler(const MethodChannel('herdr.pocket/pair_scan'),(_) async { calls++; throw PlatformException(code:'denied'); });
    addTearDown(() { messenger.setMockMethodCallHandler(const MethodChannel('herdr.pocket/pair_scan'),null); visibility.dispose(); });
    await tapVisible(tester,'pair-scan'); await tester.pump();
    expect(find.textContaining('可继续手动输入'),findsOneWidget);
    expect(tester.widget<TextField>(find.byKey(const ValueKey('pair-response'))).enabled,isTrue);
    time = 1600; await tester.pump(const Duration(seconds:1));
    expect(tester.widget<TextButton>(find.byKey(const ValueKey('pair-scan'))).onPressed,isNull); expect(calls,1);
    await tester.pumpWidget(const SizedBox());
  },variant:android);
}
