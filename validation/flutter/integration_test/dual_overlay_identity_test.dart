import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/network_identity_dialog.dart';
import 'package:herdr_flutter_probe/network_profiles.dart';
import 'package:herdr_flutter_probe/network_profiles_page.dart';

import '../test/host_catalog_test.dart' show MemoryCatalogStorage;
import '../test/network_profiles_test.dart' show testNetwork;
import '../test/network_tailscale_test.dart'
    show TailscaleIdentityFixture, TailscaleRuntimeFixture;
import 'android_pairing_observe_test.dart' as existing;
import 'dual_overlay_ui_steps.dart';

Future<
  ({
    NetworkProfile profile,
    DualOverlayUiSteps steps,
    TailscaleIdentityFixture store,
    ValueNotifier<bool> barrier,
    List<Offset> taps,
  })
>
pageFixture(WidgetTester tester, Size size) async {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = size;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final root = Directory.systemTemp.createTempSync('dual-identity-');
  addTearDown(() => root.deleteSync(recursive: true));
  final catalog = HostCatalog(
    storage: MemoryCatalogStorage(),
    clock: () => 1000,
  );
  await catalog.load();
  addTearDown(catalog.dispose);
  await catalog.addNetwork(testNetwork('easytier'));
  final profile = testNetwork('tailscale');
  await catalog.addNetwork(profile);
  final store = TailscaleIdentityFixture();
  final barrier = ValueNotifier(false);
  addTearDown(barrier.dispose);
  final taps = <Offset>[];
  await tester.pumpWidget(
    MaterialApp(
      home: ValueListenableBuilder(
        valueListenable: barrier,
        child: Listener(
          onPointerDown: (event) => taps.add(event.position),
          child: NetworkProfilesPage(
            catalog: catalog,
            closeTabs: (_) {},
            identityStore: store,
            runtime: TailscaleRuntimeFixture(profile),
          ),
        ),
        builder: (_, blocked, child) =>
            AbsorbPointer(absorbing: blocked, child: child),
      ),
    ),
  );
  return (
    profile: profile,
    steps: DualOverlayUiSteps(tester, root),
    store: store,
    barrier: barrier,
    taps: taps,
  );
}

void main() {
  testWidgets(
    'waits for the real narrow network header and opens identity once',
    (tester) async {
      final f = await pageFixture(tester, const Size(320, 600));
      final tile = find.byKey(
        PageStorageKey('network-details-${f.profile.id}'),
      );
      await tester.ensureVisible(tile);
      await tester.pumpAndSettle();
      f.barrier.value = true;
      await tester.pump();
      expect(tile, findsOneWidget);
      expect(existing.groupHeader(tile).hitTestable(), findsNothing);
      Timer(const Duration(milliseconds: 900), () => f.barrier.value = false);

      await f.steps.openNetworkIdentity(f.profile.id);
      expect(find.byType(NetworkIdentityDialog), findsOneWidget);
      expect(f.taps, hasLength(2)); // One header tap, then one identity tap.
      expect(f.store.reads, 1);
      expect(f.store.creates, 0);
    },
  );

  testWidgets('an already expanded profile only taps its identity control', (
    tester,
  ) async {
    final f = await pageFixture(tester, const Size(390, 844));
    await f.steps.showNetworkControls(f.profile.id);
    final tile = find.byKey(PageStorageKey('network-details-${f.profile.id}'));
    final header = existing.groupHeader(tile);
    expect(tester.getRect(header).contains(tester.getCenter(tile)), isFalse);
    f.taps.clear();

    await f.steps.openNetworkIdentity(f.profile.id);
    expect(find.byType(NetworkIdentityDialog), findsOneWidget);
    expect(f.taps, hasLength(1));
    expect(f.store.reads, 1);
    expect(f.store.creates, 0);
    final review = await existing.stableReviewCheckbox(
      tester,
      'network-identity-review',
    );
    await tester.tap(review);
    await tester.pump();
    final create = find.byKey(const ValueKey('network-identity-create'));
    expect(tester.widget<FilledButton>(create).onPressed, isNotNull);
    await existing.tapStablePointer(tester, create);
    await tester.pumpAndSettle();
    expect(f.store.creates, 1);
    expect(f.store.record?.mode, 'DEVICE_STATE');
    expect(
      find.byKey(const ValueKey('network-identity-present')),
      findsOneWidget,
    );
  });

  testWidgets('a disabled identity button is never tapped or written', (
    tester,
  ) async {
    final f = await pageFixture(tester, const Size(320, 600));
    await f.steps.showNetworkControls(f.profile.id);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    addTearDown(
      () => tester.binding.handleAppLifecycleStateChanged(
        AppLifecycleState.resumed,
      ),
    );
    await tester.pump();
    final identity = find.byKey(ValueKey('network-identity-${f.profile.id}'));
    expect(tester.widget<TextButton>(identity).onPressed, isNull);
    f.taps.clear();

    await expectLater(
      f.steps.openNetworkIdentity(f.profile.id),
      throwsA(isA<TestFailure>()),
    );
    expect(find.byType(NetworkIdentityDialog), findsNothing);
    expect(f.taps, isEmpty);
    expect(f.store.reads, 0);
    expect(f.store.creates, 0);
  });
}
