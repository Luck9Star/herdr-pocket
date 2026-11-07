import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/pairing_page.dart';
import 'pairing_gui_test.dart' show TestDeviceKeys,tapVisible,fillPairTarget,authorizedResponse;
import 'remote_test_data.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const android = TargetPlatformVariant({TargetPlatform.android});
  const channel = MethodChannel('herdr.pocket/pair_scan');
  final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  String profile() {
    final cfg = fixtureConfig();
    return jsonEncode({'version':1,'type':'herdr-connection-profile',
      for (final key in ['host','port','username','session','socketPath','herdrPath','expectedHostKey']) key:cfg[key],
      'provider':'direct'});
  }
  void lifecycle(WidgetTester tester,List<AppLifecycleState> states) {
    for (final state in states) { tester.binding.handleAppLifecycleStateChanged(state); }
  }
  Future<void> screen(WidgetTester tester,Completer<Object?> pending) async {
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    messenger.setMockMethodCallHandler(channel,(_) => pending.future);
    await tester.pumpWidget(MaterialApp(home:PairingPage(tokens:tokens,keys:TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String))));
  }
  setUp(PairingPage.resetMemorySession);
  tearDown(() { messenger.setMockMethodCallHandler(channel,null); PairingPage.resetMemorySession(); });

  testWidgets('camera round trip previews only, and clears an earlier target review',(tester) async {
    final pending = Completer<Object?>(); await screen(tester,pending);
    await tapVisible(tester,'pair-target-review');
    expect(tester.widget<CheckboxListTile>(find.byKey(const ValueKey('pair-target-review'))).value,isTrue);
    await tapVisible(tester,'profile-scan');
    expect(tester.widget<CheckboxListTile>(find.byKey(const ValueKey('pair-target-review'))).value,isFalse);
    lifecycle(tester,[AppLifecycleState.inactive,AppLifecycleState.hidden,AppLifecycleState.paused,
      AppLifecycleState.hidden,AppLifecycleState.inactive,AppLifecycleState.resumed]);
    pending.complete(profile()); await tester.pump();
    expect(find.byKey(const ValueKey('profile-preview')),findsOneWidget);
    expect(tester.widget<TextField>(find.byKey(const ValueKey('pair-host'))).controller!.text,isEmpty);
    expect(tester.widget<CheckboxListTile>(find.byKey(const ValueKey('pair-target-review'))).value,isFalse);
    await tester.pumpWidget(const SizedBox());
  },variant:android);

  testWidgets('scanner callback while paused cannot immediately publish a candidate',(tester) async {
    final pending = Completer<Object?>(); await screen(tester,pending);
    await tapVisible(tester,'profile-scan');
    lifecycle(tester,[AppLifecycleState.inactive,AppLifecycleState.hidden,AppLifecycleState.paused]);
    pending.complete(profile()); await tester.pump();
    expect(find.byKey(const ValueKey('profile-preview')),findsNothing);
    expect(tester.widget<TextField>(find.byKey(const ValueKey('pair-host'))).controller!.text,isEmpty);
    expect(tester.widget<CheckboxListTile>(find.byKey(const ValueKey('pair-target-review'))).value,isFalse);
    lifecycle(tester,[AppLifecycleState.hidden,AppLifecycleState.inactive,AppLifecycleState.resumed]);
    await tester.pump();
    expect(find.byKey(const ValueKey('profile-preview')),findsOneWidget);
    expect(tester.widget<CheckboxListTile>(find.byKey(const ValueKey('pair-target-review'))).value,isFalse);
    await tester.pumpWidget(const SizedBox());
  },variant:android);
  testWidgets('response scan in background never accepts authorization or restores old review',(tester) async {
    final pending = Completer<Object?>();
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    messenger.setMockMethodCallHandler(channel,(_) => pending.future);
    Map<String,dynamic>? request;
    await tester.pumpWidget(MaterialApp(home:PairingPage(tokens:tokens,clock:() => 1000,
      keys:TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String),onRequest:(value) { request = value; })));
    await fillPairTarget(tester,fixtureConfig());
    await tapVisible(tester,'pair-target-review'); await tapVisible(tester,'pair-create');
    await tapVisible(tester,'pair-source-review');
    expect(tester.widget<CheckboxListTile>(find.byKey(const ValueKey('pair-source-review'))).value,isTrue);
    await tapVisible(tester,'pair-scan');
    expect(tester.widget<CheckboxListTile>(find.byKey(const ValueKey('pair-source-review'))).value,isFalse);
    lifecycle(tester,[AppLifecycleState.inactive,AppLifecycleState.hidden,AppLifecycleState.paused]);
    pending.complete(jsonEncode(authorizedResponse(request!))); await tester.pump();
    expect(tester.widget<TextField>(find.byKey(const ValueKey('pair-response'))).controller!.text,isEmpty);
    expect(find.byKey(const ValueKey('pair-response-preview')),findsNothing);
    expect(find.textContaining('awaiting-host'),findsOneWidget);
    lifecycle(tester,[AppLifecycleState.hidden,AppLifecycleState.inactive,AppLifecycleState.resumed]); await tester.pump();
    expect(find.byKey(const ValueKey('pair-response-preview')),findsOneWidget);
    expect(tester.widget<CheckboxListTile>(find.byKey(const ValueKey('pair-source-review'))).value,isFalse);
    expect(find.byKey(const ValueKey('pair-connect')),findsNothing);
    await tester.pumpWidget(const SizedBox());
  },variant:android);

  testWidgets('deferred scan is discarded if its tab hides before resume',(tester) async {
    final pending = Completer<Object?>(), visibility = ValueNotifier(true);
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    messenger.setMockMethodCallHandler(channel,(_) => pending.future);
    await tester.pumpWidget(MaterialApp(home:PairingPage(tokens:tokens,visibility:visibility,
      keys:TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String))));
    await tapVisible(tester,'profile-scan');
    lifecycle(tester,[AppLifecycleState.inactive,AppLifecycleState.hidden,AppLifecycleState.paused]);
    pending.complete(profile()); await tester.pump();
    visibility.value = false; await tester.pump();
    lifecycle(tester,[AppLifecycleState.hidden,AppLifecycleState.inactive,AppLifecycleState.resumed]);
    visibility.value = true; await tester.pump();
    expect(find.byKey(const ValueKey('profile-preview')),findsNothing);
    expect(tester.widget<TextField>(find.byKey(const ValueKey('pair-host'))).controller!.text,isEmpty);
    expect(tester.widget<CheckboxListTile>(find.byKey(const ValueKey('pair-target-review'))).value,isFalse);
    await tester.pumpWidget(const SizedBox()); visibility.dispose();
  },variant:android);

  testWidgets('reusing a page for another target invalidates a deferred scan',(tester) async {
    final pending = Completer<Object?>(), tokens = (await tester.runAsync(DesignTokens.load))!;
    final keys = TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
    messenger.setMockMethodCallHandler(channel,(_) => pending.future);
    await tester.pumpWidget(MaterialApp(home:PairingPage(tokens:tokens,keys:keys)));
    await tapVisible(tester,'profile-scan');
    await tester.pumpWidget(MaterialApp(home:PairingPage(tokens:tokens,keys:keys,profileId:'different-target')));
    pending.complete(profile()); await tester.pump();
    expect(find.byKey(const ValueKey('profile-preview')),findsNothing);
    expect(tester.widget<TextField>(find.byKey(const ValueKey('pair-host'))).controller!.text,isEmpty);
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('pair-create'))).onPressed,isNull);
    expect(find.textContaining('目标或本机身份来源已改变'),findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  },variant:android);

  testWidgets('a scanner result expires while app remains paused',(tester) async {
    final pending = Completer<Object?>(); await screen(tester,pending);
    await tapVisible(tester,'profile-scan');
    lifecycle(tester,[AppLifecycleState.inactive,AppLifecycleState.hidden,AppLifecycleState.paused]);
    pending.complete(profile()); await tester.pump();
    await tester.pump(const Duration(seconds:61));
    lifecycle(tester,[AppLifecycleState.hidden,AppLifecycleState.inactive,AppLifecycleState.resumed]); await tester.pump();
    expect(find.byKey(const ValueKey('profile-preview')),findsNothing);
    expect(tester.widget<TextField>(find.byKey(const ValueKey('pair-host'))).controller!.text,isEmpty);
    expect(tester.widget<CheckboxListTile>(find.byKey(const ValueKey('pair-target-review'))).value,isFalse);
    await tester.pumpWidget(const SizedBox());
  },variant:android);

  testWidgets('deferred response cannot outlive its original request',(tester) async {
    final pending = Completer<Object?>(); var now = 1000; Map<String,dynamic>? request;
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    messenger.setMockMethodCallHandler(channel,(_) => pending.future);
    await tester.pumpWidget(MaterialApp(home:PairingPage(tokens:tokens,clock:() => now,
      keys:TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String),onRequest:(value) { request = value; })));
    await fillPairTarget(tester,fixtureConfig());
    await tapVisible(tester,'pair-target-review'); await tapVisible(tester,'pair-create');
    now = 1599;
    await tapVisible(tester,'pair-scan');
    lifecycle(tester,[AppLifecycleState.inactive,AppLifecycleState.hidden,AppLifecycleState.paused]);
    pending.complete(jsonEncode(authorizedResponse(request!))); await tester.pump();
    now = 1600; await tester.pump(const Duration(seconds:2));
    lifecycle(tester,[AppLifecycleState.hidden,AppLifecycleState.inactive,AppLifecycleState.resumed]); await tester.pump();
    expect(find.byKey(const ValueKey('pair-response-preview')),findsNothing);
    expect(tester.widget<TextField>(find.byKey(const ValueKey('pair-response'))).controller!.text,isEmpty);
    expect(find.byKey(const ValueKey('pair-connect')),findsNothing);
    await tester.pumpWidget(const SizedBox());
  },variant:android);

}
