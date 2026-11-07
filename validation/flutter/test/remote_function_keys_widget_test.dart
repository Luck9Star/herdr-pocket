import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/host_tabs.dart';
import 'package:herdr_flutter_probe/pairing_page.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'package:herdr_flutter_probe/remote_input.dart';
import 'package:terminal_view/terminal_view.dart';
import 'host_catalog_test.dart' show MemoryCatalogStorage;
import 'host_tabs_widget_test.dart' show tabProfile;
import 'pairing_gui_test.dart' show TestDeviceKeys,tapVisible,fillPairTarget,authorizedResponse,acceptResponse;
import 'remote_input_widget_test.dart' as input;
import 'remote_test_data.dart';

/// Client UI double only: no SSH authentication or device store claim.
class FunctionKeysAdapter extends input.InputFixtureAdapter {
  late RemoteConfig frozenConfig;
  @override
  Future<RemoteSnapshot> observe(RemoteConfig config,{required DashboardConsumer onDashboard,
      required FrameConsumer onFrame,RemoteProgress? onProgress}) {
    frozenConfig = config;
    final result = super.observe(config,onDashboard:onDashboard,onFrame:onFrame,onProgress:onProgress);
    onProgress?.call(generation,'snapshot');
    return result;
  }
  @override
  void selectPane(int expectedGeneration,String paneId) {
    super.selectPane(expectedGeneration,paneId);
    final config = frozenConfig;
    selectedTarget = RemoteInputTarget(connection:connection,generation:expectedGeneration,
      host:config.host,port:config.port,username:config.username,hostFingerprint:config.expectedFingerprint,
      session:config.session,socketPath:config.socketPath,paneId:paneId,
      terminalId:paneId == 'w1:p1' ? 'term_abcd' : 'term_1234');
  }
}

Future<void> press(WidgetTester tester,String key) async {
  final button = find.byKey(ValueKey(key)); await tester.ensureVisible(button);
  await tester.tap(button); await tester.pump(); await tester.pump();
}

void main() {
  setUp(PairingPage.resetMemorySession); tearDown(PairingPage.resetMemorySession);
  for (final entry in ['new-pairing','saved-host-tab']) {
    testWidgets('$entry has reachable one-shot function keys at 320px and rejects stale/collapsed modes', (tester) async {
      tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(320,844);
      addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetViewInsets);
      final adapter = FunctionKeysAdapter(),config = fixtureConfig();
      final keys = TestDeviceKeys(config['privateKeyPem'] as String),tokens = (await tester.runAsync(DesignTokens.load))!;
      if (entry == 'new-pairing') {
        Map<String,dynamic>? request;
        await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:PairingPage(tokens:tokens,keys:keys,adapter:adapter,
          onRequest:(value) { request = value; },clock:() => 1000)));
        await fillPairTarget(tester,config);
        await tapVisible(tester,'pair-target-review'); await tapVisible(tester,'pair-create');
        await acceptResponse(tester,authorizedResponse(request!));
      } else {
        final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
        final host = tabProfile('Function key host','probe','127.0.0.1','direct','opaque-function-keys');
        await catalog.add(host); final tabs = HostTabs();
        addTearDown(catalog.dispose); addTearDown(tabs.dispose);
        await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:HostCatalogPage(tokens:tokens,catalog:catalog,keys:keys,
          tabs:tabs,adapterFactory:(_) => adapter,offlineBuilder:(_) => const SizedBox())));
        await tester.pumpAndSettle(); await tapVisible(tester,'host-open-${host.id}'); await tester.pumpAndSettle();
      }
      await tapVisible(tester,'pair-connect'); await tester.pumpAndSettle();
      await press(tester,'remote-review'); await press(tester,'remote-connect');
      adapter.publish(); await tester.pump(); await press(tester,'remote-pane-w1:p1');
      adapter.frame!(adapter.generation,'w1:p1',const RemoteFrame(0,true,'FUNCTION KEY UI DOUBLE'));
      await tester.pump();
      expect(find.byKey(const ValueKey('remote-function-keys-toggle')),findsNothing);
      expect(adapter.received,isEmpty);
      await input.mode(tester,'direct'); await press(tester,'remote-function-keys-toggle');
      for (final name in ['f1','f12','insert','delete','backspace','shift-tab']) {
        final key = find.byKey(ValueKey('remote-function-key-$name')); await tester.ensureVisible(key); await tester.pump();
        expect(key.hitTestable(),findsOneWidget); expect(tester.getSize(key).height,greaterThanOrEqualTo(48));
      }
      await press(tester,'remote-function-key-f1');
      await press(tester,'remote-modifier-ctrl'); await press(tester,'remote-function-key-f1');
      await press(tester,'remote-modifier-alt'); await press(tester,'remote-function-key-f12');
      await press(tester,'remote-modifier-ctrl'); await press(tester,'remote-modifier-alt'); await press(tester,'remote-function-key-insert');
      await press(tester,'remote-function-key-delete'); await press(tester,'remote-function-key-backspace');
      await press(tester,'remote-function-key-shift-tab');
      expect(adapter.received.map((bytes) => utf8.decode(bytes)),['\x1bOP','\x1b[1;5P','\x1b[24;3~','\x1b[2;7~','\x1b[3~','\x7f','\x1b[Z']);
      await press(tester,'remote-modifier-ctrl'); await press(tester,'remote-function-key-backspace');
      expect(adapter.received.length,7); expect(find.textContaining('此辅助组合未定义'),findsOneWidget);
      expect(tester.widget<FilterChip>(find.byKey(const ValueKey('remote-modifier-ctrl'))).selected,isFalse);
      final old = tester.widget<OutlinedButton>(find.byKey(const ValueKey('remote-function-key-f1'))).onPressed!;
      await press(tester,'remote-modifier-alt'); await press(tester,'remote-function-keys-toggle');
      expect(find.byKey(const ValueKey('remote-function-key-f1')),findsNothing);
      expect(tester.widget<FilterChip>(find.byKey(const ValueKey('remote-modifier-alt'))).selected,isFalse);
      old(); await tester.pump(); expect(adapter.received.length,7);
      await press(tester,'remote-function-keys-toggle'); old(); await tester.pump(); expect(adapter.received.length,7);
      await input.mode(tester,'draft'); old(); await tester.pump();
      expect(find.byKey(const ValueKey('remote-function-keys-toggle')),findsNothing); expect(adapter.received.length,7);
      await input.mode(tester,'direct');
      expect(find.byKey(const ValueKey('remote-function-key-f1')),findsNothing);
      expect(tester.takeException(),isNull); await tester.pumpWidget(const SizedBox());
    });
  }
  testWidgets('hiding retires function-key callbacks and modifiers until explicit resume plus fresh full', (tester) async {
    final visible = ValueNotifier(true); addTearDown(visible.dispose);
    final adapter = input.InputFixtureAdapter(); await input.start(tester,adapter,visibility:visible);
    await input.mode(tester,'direct'); await press(tester,'remote-function-keys-toggle'); await press(tester,'remote-modifier-ctrl');
    final old = tester.widget<OutlinedButton>(find.byKey(const ValueKey('remote-function-key-f1'))).onPressed!;
    visible.value = false; await tester.pump(); old(); await tester.pump();
    expect(adapter.received,isEmpty); expect(find.byKey(const ValueKey('remote-function-key-f1')),findsNothing);
    visible.value = true; await tester.pump(); await press(tester,'remote-resume');
    old(); await tester.pump(); expect(adapter.received,isEmpty);
    adapter.frame!(adapter.generation,'w1:p1',const RemoteFrame(0,true,'FRESH',observationEpoch:1)); await tester.pump();
    await input.mode(tester,'direct'); await press(tester,'remote-function-keys-toggle'); old(); await tester.pump();
    expect(adapter.received,isEmpty);
    expect(tester.widget<FilterChip>(find.byKey(const ValueKey('remote-modifier-ctrl'))).selected,isFalse);
    await press(tester,'remote-function-key-f1'); expect(adapter.received.single,[27,79,80]);
    expect(tester.takeException(),isNull); await tester.pumpWidget(const SizedBox());
  });
  testWidgets('expanding and collapsing function keys preserves IME composition without modifying text', (tester) async {
    final adapter = input.InputFixtureAdapter(); await input.start(tester,adapter); await input.mode(tester,'direct');
    final original = tester.widget<TerminalView>(find.byType(TerminalView));
    tester.testTextInput.updateEditingValue(const TextEditingValue(text:'中文',selection:TextSelection.collapsed(offset:2),
      composing:TextRange(start:0,end:2))); await tester.pump();
    await press(tester,'remote-function-keys-toggle'); await press(tester,'remote-function-keys-toggle');
    final current = tester.widget<TerminalView>(find.byType(TerminalView));
    expect(current.key,original.key); expect(identical(current.terminal,original.terminal),isTrue);
    expect(adapter.received,isEmpty);
    tester.testTextInput.updateEditingValue(const TextEditingValue(text:'中文',selection:TextSelection.collapsed(offset:2),
      composing:TextRange.empty)); await tester.pump();
    expect(adapter.received.single,utf8.encode('中文'));
    expect(tester.takeException(),isNull); await tester.pumpWidget(const SizedBox());
  });
  testWidgets('an unknown function-key result locks input and never replays its old callback', (tester) async {
    final adapter = input.InputFixtureAdapter()..nextResult = const RemoteInputResult.unknown();
    await input.start(tester,adapter); await input.mode(tester,'direct'); await press(tester,'remote-function-keys-toggle');
    final old = tester.widget<OutlinedButton>(find.byKey(const ValueKey('remote-function-key-f12'))).onPressed!;
    await press(tester,'remote-function-key-f12');
    expect(adapter.received.single,[27,91,50,52,126]);
    old(); await tester.pump(); expect(adapter.received.length,1);
    expect(find.byKey(const ValueKey('remote-function-keys-toggle')),findsNothing);
    adapter.frame!(adapter.generation,'w1:p1',const RemoteFrame(1,true,'FRESH AFTER UNKNOWN'));
    await tester.pump(); old(); await tester.pump();
    expect(adapter.received.length,1); expect(find.byKey(const ValueKey('remote-function-keys-toggle')),findsNothing);
    expect(tester.takeException(),isNull); await tester.pumpWidget(const SizedBox());
  });
  testWidgets('real editing composition blocks original and function actions before rebuild, then commits once', (tester) async {
    final adapter = input.InputFixtureAdapter(); await input.start(tester,adapter); await input.mode(tester,'direct');
    await press(tester,'remote-function-keys-toggle'); await press(tester,'remote-modifier-ctrl');
    final original = tester.widget<TerminalView>(find.byType(TerminalView));
    final oldFunction = tester.widget<OutlinedButton>(find.byKey(const ValueKey('remote-function-key-f1'))).onPressed!;
    final oldEnter = tester.widget<OutlinedButton>(find.byKey(const ValueKey('remote-key-Enter'))).onPressed!;
    final oldBase = tester.widget<OutlinedButton>(find.byKey(const ValueKey('remote-base-c'))).onPressed!;
    final oldModifier = tester.widget<FilterChip>(find.byKey(const ValueKey('remote-modifier-alt'))).onSelected!;
    final oldEditing = original.onEditingValueChanged!;
    tester.testTextInput.updateEditingValue(const TextEditingValue(text:'中',selection:TextSelection.collapsed(offset:1),
      composing:TextRange(start:0,end:1)));
    await tester.idle(); // Deliver the text channel without rebuilding old button closures.
    oldFunction(); oldEnter(); oldBase(); oldModifier(true);
    await tester.pump(); await tester.pump();
    expect(adapter.received,isEmpty); expect(original.focusNode!.hasFocus,isTrue);
    expect(tester.widget<OutlinedButton>(find.byKey(const ValueKey('remote-function-key-f1'))).onPressed,isNull);
    expect(tester.widget<OutlinedButton>(find.byKey(const ValueKey('remote-key-Enter'))).onPressed,isNull);
    expect(tester.widget<FilterChip>(find.byKey(const ValueKey('remote-modifier-ctrl'))).selected,isFalse);
    expect(tester.widget<FilterChip>(find.byKey(const ValueKey('remote-modifier-alt'))).onSelected,isNull);
    // Layout-only expansion/collapse preserves the actual editing connection.
    await press(tester,'remote-function-keys-toggle'); await press(tester,'remote-function-keys-toggle');
    expect(tester.widget<TerminalView>(find.byType(TerminalView)).key,original.key);
    tester.testTextInput.updateEditingValue(const TextEditingValue(text:'中',selection:TextSelection.collapsed(offset:1),
      composing:TextRange.empty)); await tester.pump(); await tester.pump();
    expect(adapter.received.map((bytes) => utf8.decode(bytes)),['中']);
    oldFunction(); oldEnter(); oldModifier(true); await tester.pump();
    expect(adapter.received.length,1);
    await press(tester,'remote-function-key-f1');
    expect(adapter.received.map((bytes) => utf8.decode(bytes)),['中','\x1bOP']);
    await input.mode(tester,'observe'); await input.mode(tester,'direct');
    await press(tester,'remote-function-keys-toggle'); await press(tester,'remote-modifier-ctrl');
    oldEditing(const TextEditingValue(text:'旧',selection:TextSelection.collapsed(offset:1),composing:TextRange(start:0,end:1)));
    await tester.pump();
    expect(tester.widget<FilterChip>(find.byKey(const ValueKey('remote-modifier-ctrl'))).selected,isTrue);
    await press(tester,'remote-function-key-f1'); expect(adapter.received.last,[27,91,49,59,53,80]);
    expect(tester.takeException(),isNull); await tester.pumpWidget(const SizedBox());
  });
  testWidgets('range-only composition start and cancellation release modifiers without treating shown keyboard as composition', (tester) async {
    final adapter = input.InputFixtureAdapter(); await input.start(tester,adapter); await input.mode(tester,'direct');
    await press(tester,'remote-function-keys-toggle');
    tester.testTextInput.updateEditingValue(const TextEditingValue(text:'a',selection:TextSelection.collapsed(offset:1),composing:TextRange.empty));
    await tester.pump(); await tester.pump(); expect(adapter.received.single,[97]);
    await press(tester,'remote-modifier-ctrl');
    final old = tester.widget<OutlinedButton>(find.byKey(const ValueKey('remote-function-key-f1'))).onPressed!;
    tester.testTextInput.updateEditingValue(const TextEditingValue(text:'a',selection:TextSelection.collapsed(offset:1),
      composing:TextRange(start:0,end:1))); await tester.idle(); old(); await tester.pump();
    expect(adapter.received.length,1); expect(tester.widget<FilterChip>(find.byKey(const ValueKey('remote-modifier-ctrl'))).selected,isFalse);
    tester.testTextInput.updateEditingValue(const TextEditingValue(text:'',selection:TextSelection.collapsed(offset:0),composing:TextRange.empty));
    await tester.pump(); await tester.pump(); old(); await tester.pump(); expect(adapter.received.length,1);
    expect(tester.testTextInput.isVisible,isTrue);
    await press(tester,'remote-function-key-f1'); expect(adapter.received.last,[27,79,80]);
    expect(tester.takeException(),isNull); await tester.pumpWidget(const SizedBox());
  });
}
