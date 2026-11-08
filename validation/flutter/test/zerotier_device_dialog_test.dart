import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/network_profiles.dart';
import 'package:herdr_flutter_probe/network_profiles_page.dart';
import 'package:herdr_flutter_probe/zerotier_device.dart';
import 'package:herdr_flutter_probe/zerotier_device_dialog.dart';
import 'network_profiles_test.dart' show testNetwork;
import 'remote_test_data.dart' show fixtureConfig;
import 'zerotier_device_test.dart' show MemoryZeroTierDeviceStore,deviceReply,statusReply,pendingState;

class ReviewCatalog extends HostCatalog {
  ReviewCatalog() { ready = true; revision = 'a' * 64; networkProfiles = [testNetwork('zerotier'),testNetwork('zerotier').change(enabled:false)]; }
  void signal() => notifyListeners();
}
HostProfile affectedHost(NetworkProfile network) => HostProfile.fromJson({
  'id':'f' * 32,'label':'离线测试主机','enabled':false,'provider':'zerotier','retired':false,
  'networkProfileId':network.id,'pairing':null,
  'target':{for (final key in HostProfile.targetFields) key:fixtureConfig()[key]},
},1000);
Future<void> showReview(WidgetTester tester,ReviewCatalog catalog,MemoryZeroTierDeviceStore store,{BeforeZeroTierForget? beforeForget}) async {
  await tester.pumpWidget(MaterialApp(home:Scaffold(body:ZeroTierDeviceDialog(catalog:catalog,store:store,beforeForget:beforeForget))));
  await tester.pumpAndSettle();
}
Future<void> tapReview(WidgetTester tester,String key) async {
  final finder = find.byKey(ValueKey(key));
  final scrollable = find.descendant(of:find.byKey(const ValueKey('zt-device-list')),matching:find.byType(Scrollable)).first;
  // A previous action can leave the viewport below a recycled target card.
  // Start from the top so scrollUntilVisible can reliably search downwards.
  tester.state<ScrollableState>(scrollable).position.jumpTo(0); await tester.pump();
  await tester.scrollUntilVisible(finder,250,scrollable:scrollable);
  // The scroll offset only reaches the render tree on the next frame; without
  // it the tap lands on the stale offset of a row outside the viewport.
  await tester.ensureVisible(finder); await tester.pumpAndSettle(); await tester.tap(finder); await tester.pumpAndSettle();
}
void main() {
  testWidgets('impact is unknown while catalog is unavailable or writing, independent of native availability',(tester) async {
    final catalog=ReviewCatalog(),store=MemoryZeroTierDeviceStore()..current=const ZeroTierDeviceStatus.unavailable();
    catalog.profiles=[affectedHost(catalog.networkProfiles.first)];
    await showReview(tester,catalog,store);
    final scrollable=find.descendant(of:find.byKey(const ValueKey('zt-device-list')),matching:find.byType(Scrollable)).first;
    await tester.scrollUntilVisible(find.textContaining('完整影响范围 · 2 个网络 / 1 台主机'),200,scrollable:scrollable); await tester.pump();
    expect(find.textContaining('完整影响范围 · 2 个网络 / 1 台主机'),findsOneWidget);
    await tester.scrollUntilVisible(find.text('离线测试主机 · 停用'),200,scrollable:scrollable); await tester.pump();
    expect(find.text('离线测试主机 · 停用'),findsOneWidget);
    tester.state<ScrollableState>(scrollable).position.jumpTo(0); await tester.pump();
    catalog.ready=false; catalog.networkProfiles=[]; catalog.profiles=[]; catalog.signal(); await tester.pump();
    await tester.scrollUntilVisible(find.byKey(const ValueKey('zt-impact-unknown')),200,scrollable:scrollable); await tester.pump();
    expect(find.byKey(const ValueKey('zt-impact-unknown')),findsOneWidget);
    expect(find.textContaining('完整影响范围 ·'),findsNothing);
    expect(find.text('当前没有 ZeroTier 公开网络。'),findsNothing);
    expect(find.text('当前没有受影响主机。'),findsNothing);
    catalog.ready=true; catalog.writing=true; catalog.signal(); await tester.pump();
    expect(find.byKey(const ValueKey('zt-impact-unknown')),findsOneWidget);
    expect(find.textContaining('完整影响范围 ·'),findsNothing);
    catalog.writing=false; catalog.signal(); await tester.pump();
    await tester.scrollUntilVisible(find.text('完整影响范围 · 0 个网络 / 0 台主机'),200,scrollable:scrollable); await tester.pump();
    expect(find.text('完整影响范围 · 0 个网络 / 0 台主机'),findsOneWidget);
    expect(find.text('当前没有 ZeroTier 公开网络。'),findsOneWidget);
    expect(find.text('当前没有受影响主机。'),findsOneWidget);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('network page opens the single device review with injected store',(tester) async {
    final catalog = ReviewCatalog(),store = MemoryZeroTierDeviceStore();
    await tester.pumpWidget(MaterialApp(home:NetworkProfilesPage(catalog:catalog,closeTabs:(_) => fail('must not close tabs'),zeroTierDeviceStore:store)));
    await tester.tap(find.byKey(const ValueKey('networks-zerotier-device'))); await tester.pumpAndSettle();
    expect(find.text('ZeroTier · 共享设备身份'),findsOneWidget); expect(store.reads,1);
    await tapReview(tester,'zt-device-create'); expect(store.creates,1); expect(store.forgets,0);
    // The create row sits far below the first section, which the list recycles
    // once it scrolls out of the viewport.
    final list=find.descendant(of:find.byKey(const ValueKey('zt-device-list')),matching:find.byType(Scrollable)).first;
    tester.state<ScrollableState>(list).position.jumpTo(0); await tester.pump();
    expect(find.textContaining('所有 ZeroTier 公开网络共享'),findsOneWidget);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('close and system back return to the network page without mutation',(tester) async {
    final catalog = ReviewCatalog(),store = MemoryZeroTierDeviceStore();
    await tester.pumpWidget(MaterialApp(home:NetworkProfilesPage(catalog:catalog,closeTabs:(_) => fail('must not close tabs'),zeroTierDeviceStore:store)));
    await tester.tap(find.byKey(const ValueKey('networks-zerotier-device'))); await tester.pumpAndSettle();
    expect(find.byTooltip('关闭'),findsOneWidget);
    await tester.tap(find.byTooltip('关闭')); await tester.pumpAndSettle();
    expect(find.text('ZeroTier · 共享设备身份'),findsNothing); expect(find.text('网络管理 · 公开配置'),findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('networks-zerotier-device'))); await tester.pumpAndSettle();
    await tester.binding.handlePopRoute(); await tester.pumpAndSettle();
    expect(find.text('ZeroTier · 共享设备身份'),findsNothing); expect(find.text('网络管理 · 公开配置'),findsOneWidget);
    expect(store.reads,2); expect(store.creates,0); expect(store.forgets,0);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('system back revokes a pending stop proof before the closing animation finishes',(tester) async {
    final catalog = ReviewCatalog(),store = MemoryZeroTierDeviceStore()..current = ZeroTierDeviceStatus.checked(statusReply(device:deviceReply()));
    final stop = Completer<void>();
    await tester.pumpWidget(MaterialApp(home:NetworkProfilesPage(catalog:catalog,closeTabs:(_) => fail('must not close tabs'),
      zeroTierDeviceStore:store,beforeZeroTierForget:(_) => stop.future)));
    await tester.tap(find.byKey(const ValueKey('networks-zerotier-device'))); await tester.pumpAndSettle();
    await tapReview(tester,'zt-device-review'); await tapReview(tester,'zt-device-acknowledge');
    await tester.ensureVisible(find.byKey(const ValueKey('zt-device-forget')));
    await tester.tap(find.byKey(const ValueKey('zt-device-forget'))); await tester.pump();
    await tester.binding.handlePopRoute(); stop.complete(); await tester.pumpAndSettle();
    expect(store.forgets,0); expect(store.creates,0); expect(find.text('ZeroTier · 共享设备身份'),findsNothing);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('unavailable metadata and missing retirement callback disable destructive actions',(tester) async {
    final catalog = ReviewCatalog(),store = MemoryZeroTierDeviceStore()..current = const ZeroTierDeviceStatus.unavailable();
    await showReview(tester,catalog,store);
    expect(find.textContaining('本版本未启用原生组件'),findsOneWidget);
    expect(find.textContaining('不代表已入网'),findsOneWidget);
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('zt-device-create'))).onPressed,isNull);
    await tapReview(tester,'zt-device-review'); expect(store.forgets,0); expect(store.creates,0);
    expect(find.textContaining('当前版本暂不支持此操作'),findsOneWidget);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('complete affected list includes disabled networks and hosts before second confirmation',(tester) async {
    final catalog = ReviewCatalog(),store = MemoryZeroTierDeviceStore()..current = ZeroTierDeviceStatus.checked(statusReply(device:deviceReply()));
    catalog.profiles = [affectedHost(catalog.networkProfiles.last)];
    var retired = 0;
    await showReview(tester,catalog,store,beforeForget:(review) async {
      retired++; expect(review.impact.networks.length,2); expect(review.impact.hosts.single.enabled,isFalse);
    });
    await tapReview(tester,'zt-device-review'); expect(store.forgets,0);
    expect(find.textContaining('2 个网络 / 1 台主机'),findsOneWidget);
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('zt-device-forget'))).onPressed,isNull);
    await tapReview(tester,'zt-device-acknowledge'); await tapReview(tester,'zt-device-forget');
    expect(retired,1); expect(store.forgets,1); expect(store.creates,0);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('full affected list changes invalidate an acknowledged review even at the same revision',(tester) async {
    final catalog = ReviewCatalog(),store = MemoryZeroTierDeviceStore()..current = ZeroTierDeviceStatus.checked(statusReply(device:deviceReply()));
    await showReview(tester,catalog,store,beforeForget:(_) async {});
    await tapReview(tester,'zt-device-review'); await tapReview(tester,'zt-device-acknowledge');
    final revision = catalog.revision;
    catalog.profiles = [affectedHost(catalog.networkProfiles.last)]; catalog.signal(); await tester.pumpAndSettle();
    expect(catalog.revision,revision); expect(find.byKey(const ValueKey('zt-device-forget')),findsNothing);
    expect(find.textContaining('审查已失效'),findsOneWidget); expect(store.forgets,0);
    await tapReview(tester,'zt-device-refresh'); await tapReview(tester,'zt-device-review');
    expect(tester.widget<CheckboxListTile>(find.byKey(const ValueKey('zt-device-acknowledge'))).value,isFalse);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('background invalidates second step and resume reads without mutation',(tester) async {
    final catalog = ReviewCatalog(),store = MemoryZeroTierDeviceStore()..current = ZeroTierDeviceStatus.checked(statusReply(device:deviceReply()));
    await showReview(tester,catalog,store,beforeForget:(_) async {});
    await tapReview(tester,'zt-device-review'); await tapReview(tester,'zt-device-acknowledge');
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused); await tester.pump();
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed); await tester.pumpAndSettle();
    // A paused app draws no frames, so the revoked review only leaves the tree
    // on the first frame drawn after the app comes back.
    expect(find.byKey(const ValueKey('zt-device-forget')),findsNothing);
    expect(store.reads,2); expect(store.forgets,0); expect(store.creates,0);
    await tapReview(tester,'zt-device-review');
    expect(tester.widget<CheckboxListTile>(find.byKey(const ValueKey('zt-device-acknowledge'))).value,isFalse);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('closing the view while creation is pending never retries or deletes late result',(tester) async {
    final catalog = ReviewCatalog(),store = MemoryZeroTierDeviceStore()..createWait = Completer<void>();
    await tester.pumpWidget(MaterialApp(home:NetworkProfilesPage(catalog:catalog,closeTabs:(_) => fail('must not close tabs'),zeroTierDeviceStore:store)));
    await tester.tap(find.byKey(const ValueKey('networks-zerotier-device'))); await tester.pumpAndSettle();
    final button = find.byKey(const ValueKey('zt-device-create')); await tester.ensureVisible(button);
    await tester.tap(button); await tester.pump(); expect(store.creates,1);
    await tester.tap(find.byKey(const ValueKey('zt-device-close'))); await tester.pumpAndSettle();
    expect(store.forgets,0); expect(store.reads,1);
    await tester.tap(find.byKey(const ValueKey('networks-zerotier-device'))); await tester.pumpAndSettle();
    expect(store.reads,1); expect(store.creates,1);
    expect(find.textContaining('原设备操作尚未确认'),findsWidgets);
    expect(find.text('已确认：没有设备身份'),findsNothing);
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('zt-device-create'))).onPressed,isNull);
    store.createWait!.complete(); await tester.pumpAndSettle();
    expect(store.creates,1); expect(store.reads,2);
    expect(tester.takeException(),isNull); await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('pending operations stay idle until explicit review and cannot create replacement identity',(tester) async {
    final catalog = ReviewCatalog(),store = MemoryZeroTierDeviceStore()..current = ZeroTierDeviceStatus.checked(statusReply(
      creation:{'handle':deviceReply()['handle'],'phase':'record-pending'}));
    await showReview(tester,catalog,store,beforeForget:(_) async {});
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('zt-device-create'))).onPressed,isNull);
    expect(find.textContaining('仅处理这条原记录'),findsOneWidget);
    expect(store.creates,0); expect(store.recoveries,0); expect(store.discards,0); expect(store.forgets,0);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('finishing creation review shows full impact and requires a second explicit confirmation',(tester) async {
    final catalog = ReviewCatalog(),store = MemoryZeroTierDeviceStore()..current = pendingState('recoverPendingCreation','finishing');
    catalog.profiles = [affectedHost(catalog.networkProfiles.last)];
    await showReview(tester,catalog,store);
    expect(find.textContaining('无法仅凭此页判断身份是否已安装'),findsOneWidget);
    await tapReview(tester,'zt-pending-review-recoverPendingCreation'); expect(store.recoveries,0);
    expect(find.textContaining('2 个网络 / 1 台主机'),findsOneWidget);
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('zt-pending-confirm'))).onPressed,isNull);
    await tapReview(tester,'zt-pending-acknowledge'); await tapReview(tester,'zt-pending-confirm');
    expect(store.recoveries,1); expect(store.creates,0); expect(store.forgets,0);
    expect(store.current.device!.handle,deviceReply()['handle']);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('catalog impact change revokes acknowledged pending recovery at unchanged revision',(tester) async {
    final catalog = ReviewCatalog(),store = MemoryZeroTierDeviceStore()..current = pendingState('discardPendingCreation','record-pending');
    await showReview(tester,catalog,store); await tapReview(tester,'zt-pending-review-discardPendingCreation'); await tapReview(tester,'zt-pending-acknowledge');
    final revision = catalog.revision; catalog.profiles = [affectedHost(catalog.networkProfiles.last)]; catalog.signal(); await tester.pumpAndSettle();
    expect(catalog.revision,revision); expect(find.byKey(const ValueKey('zt-pending-confirm')),findsNothing); expect(store.discards,0);
    await tapReview(tester,'zt-device-refresh'); await tapReview(tester,'zt-pending-review-discardPendingCreation');
    expect(tester.widget<CheckboxListTile>(find.byKey(const ValueKey('zt-pending-acknowledge'))).value,isFalse);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('background revokes pending deletion review without a deletion fallback',(tester) async {
    final catalog = ReviewCatalog(),store = MemoryZeroTierDeviceStore()..current = pendingState('recoverPendingDeletion','record-present');
    await showReview(tester,catalog,store); await tapReview(tester,'zt-pending-review-recoverPendingDeletion'); await tapReview(tester,'zt-pending-acknowledge');
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused); await tester.pump();
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed); await tester.pumpAndSettle();
    // A paused app draws no frames, so the revoked review only leaves the tree
    // on the first frame drawn after the app comes back.
    expect(find.byKey(const ValueKey('zt-pending-confirm')),findsNothing);
    await tapReview(tester,'zt-pending-review-recoverPendingDeletion');
    expect(tester.widget<CheckboxListTile>(find.byKey(const ValueKey('zt-pending-acknowledge'))).value,isFalse);
    expect(store.deletionRecoveries,0); expect(store.forgets,0);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('pending deletion continues only its intent and does not require ordinary forget callback',(tester) async {
    final catalog = ReviewCatalog(),store = MemoryZeroTierDeviceStore()..current = pendingState('recoverPendingDeletion','record-removed');
    await showReview(tester,catalog,store); await tapReview(tester,'zt-pending-review-recoverPendingDeletion');
    expect(find.textContaining('仅继续已经开始的原身份移除'),findsOneWidget);
    await tapReview(tester,'zt-pending-acknowledge'); await tapReview(tester,'zt-pending-confirm');
    expect(store.deletionRecoveries,1); expect(store.forgets,0); expect(store.creates,0); expect(store.current.absent,isTrue);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('closing and reopening an in-flight pending recovery is read-only until original completion',(tester) async {
    final catalog = ReviewCatalog(),store = MemoryZeroTierDeviceStore()..current = pendingState('recoverPendingCreation','record-present')..pendingWait = Completer<void>();
    await tester.pumpWidget(MaterialApp(home:NetworkProfilesPage(catalog:catalog,closeTabs:(_) => fail('must not close tabs'),zeroTierDeviceStore:store)));
    await tester.tap(find.byKey(const ValueKey('networks-zerotier-device'))); await tester.pumpAndSettle();
    await tapReview(tester,'zt-pending-review-recoverPendingCreation'); await tapReview(tester,'zt-pending-acknowledge');
    await tester.ensureVisible(find.byKey(const ValueKey('zt-pending-confirm'))); await tester.tap(find.byKey(const ValueKey('zt-pending-confirm'))); await tester.pump();
    expect(store.recoveries,1); await tester.tap(find.byKey(const ValueKey('zt-device-close'))); await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('networks-zerotier-device'))); await tester.pumpAndSettle();
    expect(find.textContaining('原设备操作尚未确认'),findsWidgets);
    expect(find.byKey(const ValueKey('zt-pending-confirm')),findsNothing); expect(store.recoveries,1);
    store.pendingWait!.complete(); await tester.pumpAndSettle();
    expect(store.recoveries,1); expect(store.creates,0); expect(store.forgets,0); expect(store.current.device,isNotNull);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
}
