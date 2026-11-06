import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/pairing_page.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'host_catalog_test.dart' show MemoryCatalogStorage,saveCatalogProfile;
import 'pairing_gui_test.dart' show TestDeviceKeys,authorizedResponse,acceptResponse,tapVisible;
import 'remote_test_data.dart';

class ControlledPairingStorage extends MemoryCatalogStorage {
  bool loseReply = false;
  @override Future<String> save(String expected,String contents) async {
    final result = await super.save(expected,contents);
    if (loseReply) throw const RemoteFailure('catalog_write_unknown');
    return result;
  }
}

Future<({HostProfile profile,TestDeviceKeys keys,Map<String,dynamic> request})> openPending(
    WidgetTester tester,HostCatalog catalog,{ValueNotifier<bool>? visibility}) async {
  final profile = await saveCatalogProfile(catalog,authorized:false);
  final keys = TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
  final tokens = (await tester.runAsync(DesignTokens.load))!;
  await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:PairingPage(tokens:tokens,
    catalog:catalog,profileId:profile.id,keys:keys,visibility:visibility)));
  await tester.pumpAndSettle();
  final request = jsonDecode(tester.widget<SelectableText>(find.byKey(const ValueKey('pair-request'))).data!) as Map<String,dynamic>;
  return (profile:profile,keys:keys,request:request);
}

void main() {
  setUp(PairingPage.resetMemorySession); tearDown(PairingPage.resetMemorySession);
  testWidgets('a committed response with lost save reply never publishes authorization or permits retry', (tester) async {
    final disk = ControlledPairingStorage();
    final active = HostCatalog(storage:disk,clock:() => 1000); await active.load();
    final fixture = await openPending(tester,active), writes = disk.writes;
    disk.beforeWrite = Completer<void>(); disk.loseReply = true;
    await acceptResponse(tester,authorizedResponse(fixture.request)); await tester.pump();
    expect(active.writing,isTrue);
    expect(find.textContaining('authorized-unverified'),findsNothing);
    expect(find.byKey(const ValueKey('pair-connect')),findsNothing);
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('pair-accept'))).onPressed,isNull);
    disk.beforeWrite!.complete(); await tester.pumpAndSettle();
    expect(active.ready,isFalse); expect(disk.writes,writes+1);
    expect(find.textContaining('本机保存未确认'),findsOneWidget);
    expect(find.textContaining('authorized-unverified'),findsNothing);
    await tapVisible(tester,'pair-source-review');
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('pair-accept'))).onPressed,isNull);
    expect(fixture.keys.signCalls,0); expect(disk.writes,writes+1);
    final reopened = HostCatalog(storage:disk,clock:() => 1000); await reopened.load();
    expect(reopened.profiles.single.restore(1000).state,'authorized-unverified');
    await tester.pumpWidget(const SizedBox()); active.dispose(); reopened.dispose();
  });
  testWidgets('a response save completing after view cancellation cannot approve the old page or replay a save', (tester) async {
    final disk = ControlledPairingStorage(), visibility = ValueNotifier(true);
    final catalog = HostCatalog(storage:disk,clock:() => 1000); await catalog.load();
    final fixture = await openPending(tester,catalog,visibility:visibility), writes = disk.writes;
    disk.beforeWrite = Completer<void>();
    await acceptResponse(tester,authorizedResponse(fixture.request)); await tester.pump();
    visibility.value = false; await tester.pump(); visibility.value = true; await tester.pump();
    expect(tester.widget<TextField>(find.byKey(const ValueKey('pair-response'))).enabled,isFalse);
    expect(find.textContaining('authorized-unverified'),findsNothing);
    disk.beforeWrite!.complete(); await tester.pumpAndSettle();
    expect(catalog.ready,isTrue); expect(disk.writes,writes+1);
    expect(catalog.profiles.single.restore(1000).state,'authorized-unverified');
    expect(find.textContaining('响应审查期间页面已变化'),findsOneWidget);
    expect(find.textContaining('authorized-unverified'),findsNothing);
    expect(find.byKey(const ValueKey('pair-connect')),findsNothing);
    await tapVisible(tester,'pair-source-review');
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('pair-accept'))).onPressed,isNull);
    expect(fixture.keys.signCalls,0); expect(disk.writes,writes+1);
    await tester.pumpWidget(const SizedBox()); catalog.dispose(); visibility.dispose();
  });
  testWidgets('finishing the narrow-screen response editor preserves text and requires the actual source checkbox before acceptance', (tester) async {
    tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(390,844);
    addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize); addTearDown(tester.view.resetViewInsets);
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final fixture = await openPending(tester,catalog), response = jsonEncode(authorizedResponse(fixture.request));
    tester.view.viewInsets = const FakeViewPadding(bottom:320); await tester.pump();
    final field = find.byKey(const ValueKey('pair-response'));
    await tester.ensureVisible(field); await tester.enterText(field,response); await tester.pump();
    await tester.testTextInput.receiveAction(TextInputAction.done); await tester.pump();
    tester.view.viewInsets = const FakeViewPadding(); await tester.pump();
    expect(tester.widget<TextField>(field).controller!.text == response,isTrue);
    expect(tester.widget<EditableText>(find.descendant(of:field,matching:find.byType(EditableText))).focusNode.hasFocus,isFalse);
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('pair-accept'))).onPressed,isNull);
    await tapVisible(tester,'pair-source-review');
    expect(tester.widget<CheckboxListTile>(find.byKey(const ValueKey('pair-source-review'))).value,isTrue);
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('pair-accept'))).onPressed,isNotNull);
    await tapVisible(tester,'pair-accept'); await tester.pumpAndSettle();
    expect(find.textContaining('authorized-unverified'),findsOneWidget);
    expect(catalog.profiles.single.restore(1000).state,'authorized-unverified');
    expect(fixture.keys.signCalls,0);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  },variant:const TargetPlatformVariant({TargetPlatform.android}));
}
