import 'dart:io';
import 'dual_overlay_ui_steps.dart';
import 'android_pairing_observe_test.dart' as existing;
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:terminal_view/terminal_view.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/host_tabs.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'package:herdr_flutter_probe/remote_input.dart';
import 'package:herdr_flutter_probe/remote_page.dart';
import '../test/host_catalog_test.dart' show MemoryCatalogStorage;
import '../test/host_tabs_widget_test.dart' show TabFixtureAdapter, tabProfile, connectTab;
import '../test/pairing_gui_test.dart' show TestDeviceKeys, tapVisible;
import '../test/remote_input_widget_test.dart' show mode;
import '../test/remote_test_data.dart' show fixtureConfig;

class InputTabAdapter extends TabFixtureAdapter {
  final received = <Uint8List>[];
  @override
  Future<RemoteInputResult> sendInput(RemoteInputTarget target, Uint8List bytes, {bool Function()? stillCurrent}) async {
    if (!identical(target, this.target) || stillCurrent?.call() != true) {
      return const RemoteInputResult.rejected('input_cancelled_before_write');
    }
    received.add(Uint8List.fromList(bytes));
    return const RemoteInputResult.accepted();
  }
}

void main() {
  testWidgets('two local tabs keep keyboard input on the selected target after closing one', (tester) async {
    tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(390,844);
    addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
    final root = Directory.systemTemp.createTempSync('dual-tabs-input-');
    addTearDown(() => root.deleteSync(recursive:true));
    final steps = DualOverlayUiSteps(tester, root);
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final a = tabProfile('Host A','probeA','127.0.0.1','tailscale','opaque-a');
    final b = tabProfile('Host B','probeB','127.0.0.2','easytier','opaque-b');
    await catalog.add(a); await catalog.add(b);
    final adapters = <String,InputTabAdapter>{}, tabs = HostTabs();
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:HostCatalogPage(tokens:tokens,catalog:catalog,
      keys:TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String),tabs:tabs,
      adapterFactory:(host) => adapters[host.id] = InputTabAdapter(),offlineBuilder:(_) => const SizedBox())));
    await tester.pumpAndSettle();
    final beforeA = steps.hostTabIds();
    await tapVisible(tester,'host-open-${a.id}'); await tester.pumpAndSettle();
    final aTab = tabs.active!.id, aa = adapters[a.id]!;
    await tapVisible(tester,'pair-connect'); await tester.pumpAndSettle(); await connectTab(tester,aa);
    expect(steps.requireNewActiveHostTab(beforeA, a.id, requireRemote:true), aTab);
    await mode(tester,'direct');
    await steps.tapVisibleTerminal();
    expect(tester.state<TerminalViewState>(find.byType(TerminalView)).hasInputConnection, isTrue);
    tester.testTextInput.enterText('E'); await tester.pumpAndSettle();
    expect(aa.received.single,[69]);
    await tapVisible(tester,'hosts-board-tab');
    final beforeB = steps.hostTabIds();
    await tapVisible(tester,'host-open-${b.id}'); await tester.pumpAndSettle();
    final bTab = tabs.active!.id, bb = adapters[b.id]!;
    await tapVisible(tester,'pair-connect'); await tester.pumpAndSettle(); await connectTab(tester,bb);
    expect(existing.hostTab().evaluate().length, 2); // Old unique-widget check failed for the second tab.
    expect(steps.requireNewActiveHostTab(beforeB, b.id, requireRemote:true), bTab);
    expect(steps.hostTabIds().contains(aTab), isTrue);
    expect(() => steps.requireNewActiveHostTab(beforeB, a.id, requireRemote:true), throwsStateError);
    expect(() => steps.requireNewActiveHostTab(<String>{}, b.id, requireRemote:true), throwsStateError);
    await mode(tester,'direct');
    await steps.tapVisibleTerminal();
    expect(tester.state<TerminalViewState>(find.byType(TerminalView)).hasInputConnection, isTrue);
    tester.testTextInput.enterText('T'); await tester.pumpAndSettle();
    expect(bb.received.single,[84]); expect(aa.received.length,1);
    await tapVisible(tester,'host-tab-$aTab'); await tester.pump();
    await tapVisible(tester,'host-tab-close-$aTab'); await tester.pump();
    await tapVisible(tester,'host-tab-$bTab'); await tester.pump();
    await tapVisible(tester,'remote-resume'); await tester.pump();
    final dynamic state = tester.state(find.byType(RemotePage));
    bb.frame!(bb.generation,'w1:p1',RemoteFrame(0,true,'B AFTER CLOSE',observationEpoch:state.observationEpoch as int));
    await tester.pump(); await mode(tester,'direct');
    await steps.tapVisibleTerminal();
    expect(tester.state<TerminalViewState>(find.byType(TerminalView)).hasInputConnection, isTrue);
    tester.testTextInput.enterText('t'); await tester.pumpAndSettle();
    expect(bb.received.length,2); expect(bb.received.last,[116]); expect(aa.received.length,1);
    expect(bb.calls,1); expect(aa.calls,1);
    await tester.pumpWidget(const SizedBox()); tabs.dispose(); catalog.dispose();
  });
}
