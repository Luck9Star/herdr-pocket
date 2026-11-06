import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/network_profiles.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'package:herdr_flutter_probe/remote_page.dart';
import 'network_profiles_test.dart' show testNetwork;
import 'remote_test_data.dart';

class PendingAdapter extends RemoteReadOnlyAdapter {
  final pending = Completer<RemoteSnapshot>();
  int calls = 0, cancels = 0;
  DashboardConsumer? dashboard;
  FrameConsumer? frame;
  String? selected;
  @override
  Future<RemoteSnapshot> observe(RemoteConfig config,{required DashboardConsumer onDashboard,
      required FrameConsumer onFrame,RemoteProgress? onProgress}) {
    calls++; generation++; dashboard = onDashboard; frame = onFrame; return pending.future;
  }
  @override
  void selectPane(int expectedGeneration,String paneId) { selected = paneId; }
  void publish({bool empty = false}) => dashboard!(RemoteDashboard(generation,'probe',
    empty ? const [] : const [RemotePane('w1:p1','term_abcd'),RemotePane('w1:p2','term_1234')]));
  @override
  Future<void> cancel() async { generation++; cancels++; }
}
class BindingChanges extends ChangeNotifier { void emit() => notifyListeners(); }
Finder field(String name) => find.byKey(ValueKey('remote-$name'));

void restoreResumedLifecycle(WidgetTester tester) {
  // Direct test binding calls do not synthesize omitted lifecycle states.
  final path = switch (tester.binding.lifecycleState) {
    AppLifecycleState.paused => const [AppLifecycleState.hidden,AppLifecycleState.inactive,AppLifecycleState.resumed],
    AppLifecycleState.hidden => const [AppLifecycleState.inactive,AppLifecycleState.resumed],
    AppLifecycleState.inactive => const [AppLifecycleState.resumed],
    AppLifecycleState.resumed => const <AppLifecycleState>[],
    _ => const [AppLifecycleState.resumed],
  };
  for (final state in path) { tester.binding.handleAppLifecycleStateChanged(state); }
}

Future<void> prepare(WidgetTester tester,PendingAdapter adapter,Size size) async {
  tester.view.devicePixelRatio = 1; tester.view.physicalSize = size;
  addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetViewInsets);
  final tokens = (await tester.runAsync(DesignTokens.load))!;
  await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:RemotePage(tokens:tokens,adapter:adapter)));
  await fillRemoteFixture(tester);
}

Future<void> fillRemoteFixture(WidgetTester tester) async {
  final values = fixtureConfig();
  for (final entry in values.entries) {
    if (entry.key == 'schemaVersion' || entry.key == 'reviewConfirmed' || entry.key == 'paneId') continue;
    await tester.ensureVisible(field(entry.key));
    await tester.enterText(field(entry.key),entry.value.toString());
    await tester.pump();
  }
}

void main() {
  testWidgets('MT04 requested new view refuses a same-name pane with a replaced terminal', (tester) async {
    final adapter = PendingAdapter();
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:RemotePage(tokens:tokens,adapter:adapter,
      requestedTarget:const RemotePane('w1:p1','term_ffff'))));
    await fillRemoteFixture(tester);
    await tester.ensureVisible(field('review')); await tester.tap(field('review')); await tester.pump();
    await tester.ensureVisible(field('connect')); await tester.tap(field('connect')); await tester.pump();
    expect(adapter.calls,1);
    expect(() => adapter.publish(),throwsA(isA<RemoteFailure>().having((e) => e.code,'code','resume_target_changed')));
    expect(adapter.selected,isNull);
    await tester.pumpWidget(const SizedBox());
  });
  testWidgets('reused system page is permanently locked when changed to overlay and back', (tester) async {
    final adapter = PendingAdapter();
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    final binding = ValueNotifier<NetworkConnectionBinding?>(null);
    addTearDown(binding.dispose);
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:ValueListenableBuilder<NetworkConnectionBinding?>(
      valueListenable:binding,builder:(_,value,__) => RemotePage(tokens:tokens,adapter:adapter,networkBinding:value))));
    await fillRemoteFixture(tester);
    await tester.ensureVisible(field('review')); await tester.tap(field('review')); await tester.pump();
    await tester.ensureVisible(field('connect')); await tester.tap(field('connect')); await tester.pump();
    expect(adapter.calls,1);
    final originalState = tester.state(find.byType(RemotePage));
    final overlay = NetworkConnectionBinding(testNetwork('easytier'),() => true);
    binding.value = overlay; await tester.pump();
    expect(identical(tester.state(find.byType(RemotePage)),originalState),isTrue);
    expect(adapter.cancels,greaterThan(0));
    expect(tester.widget<CheckboxListTile>(field('review')).onChanged,isNull);
    expect(tester.widget<FilledButton>(field('connect')).onPressed,isNull);
    expect(find.byKey(const ValueKey('remote-network-invalidated')),findsOneWidget);
    adapter.pending.complete(const RemoteSnapshot(1,'probe','w1:p1','LATE OLD ROUTE'));
    await tester.pump();
    expect(find.textContaining('LATE OLD ROUTE'),findsNothing);
    binding.value = null; await tester.pump();
    expect(identical(tester.state(find.byType(RemotePage)),originalState),isTrue);
    expect(tester.widget<CheckboxListTile>(field('review')).onChanged,isNull);
    expect(tester.widget<FilledButton>(field('connect')).onPressed,isNull);
    expect(adapter.calls,1);
  });
  testWidgets('reused overlay page cannot reconnect after switching to system route', (tester) async {
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    final overlay = NetworkConnectionBinding(testNetwork('easytier'),() => true);
    final adapter = PendingAdapter();
    final binding = ValueNotifier<NetworkConnectionBinding?>(overlay);
    addTearDown(binding.dispose);
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:ValueListenableBuilder<NetworkConnectionBinding?>(
      valueListenable:binding,builder:(_,value,__) => RemotePage(tokens:tokens,adapter:adapter,networkBinding:value))));
    final originalState = tester.state(find.byType(RemotePage));
    binding.value = null; await tester.pump();
    expect(identical(tester.state(find.byType(RemotePage)),originalState),isTrue);
    expect(tester.widget<CheckboxListTile>(field('review')).onChanged,isNull);
    expect(tester.widget<FilledButton>(field('connect')).onPressed,isNull);
    expect(find.byKey(const ValueKey('remote-network-invalidated')),findsOneWidget);
    expect(adapter.calls,0);
  });
  testWidgets('revoked binding stays locked even if its current callback later recovers', (tester) async {
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    final changes = BindingChanges(); addTearDown(changes.dispose);
    var current = true;
    final binding = NetworkConnectionBinding(null,() => current,changes:changes);
    final adapter = PendingAdapter();
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:RemotePage(tokens:tokens,adapter:adapter,networkBinding:binding)));
    current = false; changes.emit(); await tester.pump();
    current = true; changes.emit(); await tester.pump();
    expect(tester.widget<CheckboxListTile>(field('review')).onChanged,isNull);
    expect(tester.widget<FilledButton>(field('connect')).onPressed,isNull);
    expect(find.byKey(const ValueKey('remote-network-invalidated')),findsOneWidget);
    expect(adapter.calls,0);
  });
  testWidgets('mobile review resets on edit, keys clear and cancelled late full cannot appear', (tester) async {
    final adapter = PendingAdapter();
    await prepare(tester,adapter,const Size(360,780));
    await tester.ensureVisible(field('review'));
    await tester.tap(field('review')); await tester.pump();
    expect(tester.widget<FilledButton>(field('connect')).onPressed,isNotNull);
    await tester.ensureVisible(field('host')); await tester.enterText(field('host'),'localhost'); await tester.pump();
    expect(tester.widget<CheckboxListTile>(field('review')).value,isFalse);
    await tester.ensureVisible(field('review')); await tester.tap(field('review')); await tester.pump();
    await tester.ensureVisible(field('connect')); await tester.tap(field('connect')); await tester.pump();
    expect(adapter.calls,1);
    expect(tester.widget<TextField>(field('privateKeyPem')).controller!.text,isEmpty);
    expect(tester.widget<TextField>(field('host')).enabled,isFalse);
    await tester.ensureVisible(field('cancel')); await tester.tap(field('cancel')); await tester.pump();
    await tester.ensureVisible(field('privateKeyPem'));
    await tester.enterText(field('privateKeyPem'),'NEXT ATTEMPT SYNTHETIC TEXT'); await tester.pump();
    adapter.pending.complete(const RemoteSnapshot(1,'probe','w1:p1','LATE PRIVATE OUTPUT'));
    await tester.pumpAndSettle();
    expect(tester.widget<TextField>(field('privateKeyPem')).controller!.text,'NEXT ATTEMPT SYNTHETIC TEXT');
    expect(find.textContaining('LATE PRIVATE OUTPUT'),findsNothing);
    expect(find.textContaining('只读快照 · 连接已关闭'),findsNothing);
    expect(tester.takeException(),isNull);
  });
  testWidgets('390px keyboard viewport keeps named connect action reachable with at least 44px target', (tester) async {
    final adapter = PendingAdapter();
    await prepare(tester,adapter,const Size(390,844));
    tester.view.viewInsets = const FakeViewPadding(bottom:320);
    await tester.pump();
    await tester.ensureVisible(field('review')); await tester.tap(field('review')); await tester.pump();
    await tester.ensureVisible(field('connect')); await tester.pumpAndSettle();
    expect(field('connect').hitTestable(),findsOneWidget);
    expect(tester.getSize(field('connect')).height,greaterThanOrEqualTo(44));
    expect(tester.widget<TextField>(field('privateKeyPem')).obscureText,isTrue);
    expect(tester.takeException(),isNull);
  });
  testWidgets('explicit masked paste is 44px and late clipboard replies cannot refill after edits or leaving', (tester) async {
    final adapter = PendingAdapter();
    await prepare(tester,adapter,const Size(360,780));
    final clipboard = <Completer<Object?>>[];
    final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(SystemChannels.platform,(call) {
      if (call.method == 'Clipboard.getData') {
        final reply = Completer<Object?>(); clipboard.add(reply); return reply.future;
      }
      return Future<Object?>.value();
    });
    addTearDown(() { messenger.setMockMethodCallHandler(SystemChannels.platform,null); });
    final paste = find.byTooltip('粘贴临时私钥');
    await tester.ensureVisible(paste); await tester.pumpAndSettle();
    expect(tester.getSize(paste).height,greaterThanOrEqualTo(44));
    await tester.tap(paste); await tester.pump();
    clipboard.last.complete({'text':'synthetic-not-a-key\nsecond-line'}); await tester.pump();
    final secret = tester.widget<TextField>(field('privateKeyPem'));
    expect(secret.obscureText,isTrue);
    expect(secret.controller!.text,r'synthetic-not-a-key\nsecond-line');
    await tester.tap(paste); await tester.pump();
    await tester.ensureVisible(field('host')); await tester.enterText(field('host'),'another-fixture'); await tester.pump();
    clipboard.last.complete({'text':'LATE INVALID CLIPBOARD'}); await tester.pump();
    expect(secret.controller!.text,r'synthetic-not-a-key\nsecond-line');
    await tester.ensureVisible(paste); await tester.tap(paste); await tester.pump();
    await tester.pumpWidget(const SizedBox());
    clipboard.last.complete({'text':'AFTER DISPOSE'}); await tester.pump();
    expect(tester.takeException(),isNull);
  });
  testWidgets('snapshot board requires explicit target, disconnect keeps stale frame and never selects another pane', (tester) async {
    final adapter = PendingAdapter();
    await prepare(tester,adapter,const Size(360,780));
    await tester.ensureVisible(field('review')); await tester.tap(field('review')); await tester.pump();
    await tester.ensureVisible(field('connect')); await tester.tap(field('connect')); await tester.pump();
    adapter.publish(); await tester.pump();
    expect(adapter.selected,isNull);
    expect(find.text('w1:p1'),findsOneWidget); expect(find.text('w1:p2'),findsOneWidget);
    final target = find.byKey(const ValueKey('remote-pane-w1:p2'));
    await tester.ensureVisible(target); await tester.tap(target); await tester.pump();
    expect(adapter.selected,'w1:p2');
    adapter.frame!(adapter.generation,'w1:p2',const RemoteFrame(5,true,'SYNTHETIC FULL'));
    await tester.pump();
    expect(find.textContaining('只读观察中'),findsOneWidget);
    adapter.frame!(adapter.generation,'w1:p2',const RemoteFrame(6,false,'SYNTHETIC DELTA'));
    await tester.pump();
    adapter.pending.completeError(const RemoteFailure('observe_ended')); await tester.pumpAndSettle();
    expect(find.textContaining('旧画面 · 已停止'),findsOneWidget);
    expect(find.textContaining('只读观察中'),findsNothing);
    expect(adapter.calls,1); expect(tester.takeException(),isNull);
  });
  testWidgets('empty snapshot is honest and background stop rejects late frames without reconnecting', (tester) async {
    final adapter = PendingAdapter();
    await prepare(tester,adapter,const Size(390,844));
    await tester.ensureVisible(field('review')); await tester.tap(field('review')); await tester.pump();
    await tester.ensureVisible(field('connect')); await tester.tap(field('connect')); await tester.pump();
    adapter.publish(empty:true); await tester.pump();
    expect(find.textContaining('没有 pane'),findsOneWidget);
    expect(adapter.selected,isNull);
    addTearDown(() { restoreResumedLifecycle(tester); });
    restoreResumedLifecycle(tester);
    final observedGeneration = adapter.generation;
    for (final state in [AppLifecycleState.inactive,AppLifecycleState.hidden,AppLifecycleState.paused]) {
      tester.binding.handleAppLifecycleStateChanged(state);
    }
    expect(adapter.cancels,greaterThan(0));
    adapter.frame!(observedGeneration,'w1:p1',const RemoteFrame(7,true,'LATE FULL'));
    restoreResumedLifecycle(tester); await tester.pump();
    expect(tester.binding.lifecycleState,AppLifecycleState.resumed);
    expect(adapter.calls,1); expect(find.textContaining('只读观察中'),findsNothing);
    expect(find.textContaining('应用已暂停'),findsOneWidget);
    expect(tester.takeException(),isNull);
  });
  for (final width in [320.0,360.0,390.0]) {
    testWidgets('board and stop remain reachable at ${width}px with keyboard and larger text', (tester) async {
      final adapter = PendingAdapter();
      await prepare(tester,adapter,Size(width,640));
      tester.platformDispatcher.textScaleFactorTestValue = 1.3;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      tester.view.viewInsets = const FakeViewPadding(bottom:260); await tester.pump();
      await tester.ensureVisible(field('review')); await tester.tap(field('review')); await tester.pump();
      await tester.ensureVisible(field('connect')); await tester.tap(field('connect')); await tester.pump();
      adapter.publish(); await tester.pump();
      final pane = find.byKey(const ValueKey('remote-pane-w1:p1'));
      await tester.ensureVisible(pane); await tester.pumpAndSettle();
      expect(tester.getSize(pane).height,greaterThanOrEqualTo(44));
      await tester.ensureVisible(field('cancel')); await tester.pumpAndSettle();
      expect(field('cancel').hitTestable(),findsOneWidget);
      expect(tester.getSize(field('cancel')).height,greaterThanOrEqualTo(44));
      expect(tester.takeException(),isNull);
    });
  }

}
