import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/device_keys.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/pairing_page.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart' show RemoteFailure;

import 'host_catalog_test.dart' show MemoryCatalogStorage, saveCatalogProfile;
import 'pairing_gui_test.dart' show fillPairTarget, tapVisible;
import 'remote_test_data.dart';

void main() {
  const handle = '9180336503b7a87cb4df35d294f562a8';
  final expectedPublic = fixtureConfig()['expectedHostKey'] as String;
  const linux = TargetPlatformVariant({TargetPlatform.linux});
  late TestDefaultBinaryMessenger messenger;
  setUp(() {
    PairingPage.resetMemorySession();
    messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  });
  tearDown(() {
    messenger.setMockMethodCallHandler(NativeDeviceKeys.channel, null);
    PairingPage.resetMemorySession();
  });

  for (final fault in [
    null,
    'device_key_write_unknown',
    'device_key_locked',
    'device_key_store_unavailable',
    'locked_after_create',
  ]) {
    testWidgets('Linux creation reserves, saves and dispatches once ($fault)', (
      tester,
    ) async {
      final storage = MemoryCatalogStorage();
      final local = HostCatalog(storage: storage, clock: () => 1000);
      addTearDown(local.dispose);
      await local.load();
      final old = await saveCatalogProfile(local);
      final operations = <String>[];
      messenger.setMockMethodCallHandler(NativeDeviceKeys.channel, (
        MethodCall call,
      ) async {
        operations.add(call.method);
        if (call.method == 'reserve') return handle;
        expect(call.arguments, {'handle': handle});
        if (call.method == 'createReserved') {
          expect(local.pendingCreation?['handle'], handle);
          expect(storage.contents, contains(handle));
          if (fault != null && fault != 'locked_after_create') {
            throw PlatformException(code: fault);
          }
          return expectedPublic;
        }
        if (call.method == 'public') {
          if (fault == 'locked_after_create') {
            throw PlatformException(code: 'device_key_locked');
          }
          return expectedPublic;
        }
        fail('unexpected native operation ${call.method}');
      });
      final tokens = (await tester.runAsync(DesignTokens.load))!;
      await tester.pumpWidget(
        MaterialApp(
          theme: tokens.theme,
          home: PairingPage(tokens: tokens, catalog: local),
        ),
      );
      await fillPairTarget(tester, fixtureConfig());
      await tapVisible(tester, 'pair-target-review');
      await tapVisible(tester, 'pair-create');
      await tester.pumpAndSettle();

      final restored = HostCatalog(storage: storage, clock: () => 1000);
      addTearDown(restored.dispose);
      await restored.load();
      expect(
        restored.profiles.any(
          (profile) =>
              profile.id == old.id &&
              profile.restore(1000).handle == old.restore(1000).handle,
        ),
        isTrue,
      );
      expect(operations, [
        'reserve',
        'createReserved',
        if (fault == null || fault == 'locked_after_create') 'public',
      ]);
      expect(storage.contents, isNot(contains('privateKeyPem')));
      expect(
        restored.pendingCreation?['handle'],
        fault == 'device_key_write_unknown' || fault == 'locked_after_create'
            ? handle
            : null,
      );
      if (fault == null) {
        expect(
          restored.profiles.any(
            (profile) => profile.restore(1000).handle == handle,
          ),
          isTrue,
        );
        expect(find.byKey(const ValueKey('pair-request')), findsOneWidget);
      } else {
        expect(find.byKey(const ValueKey('pair-request')), findsNothing);
        expect(restored.profiles, hasLength(1));
      }
      await tester.pumpWidget(const SizedBox());
    }, variant: linux);
  }

  testWidgets(
    'locked, missing and unavailable Linux stores keep the same host and reference',
    (tester) async {
      final storage = MemoryCatalogStorage();
      final local = HostCatalog(clock: () => 1000, storage: storage);
      addTearDown(local.dispose);
      await local.load();
      final profile = await saveCatalogProfile(local);
      final stored = storage.contents;
      String? fault = 'device_key_locked';
      var reads = 0;
      messenger.setMockMethodCallHandler(NativeDeviceKeys.channel, (
        call,
      ) async {
        expect(call.method, 'public');
        expect(call.arguments, {'handle': profile.restore(1000).handle});
        reads++;
        if (fault != null) throw PlatformException(code: fault);
        return expectedPublic;
      });
      final tokens = (await tester.runAsync(DesignTokens.load))!;
      await tester.pumpWidget(
        MaterialApp(
          home: PairingPage(
            tokens: tokens,
            catalog: local,
            profileId: profile.id,
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.textContaining('请解锁'), findsOneWidget);
      fault = 'device_key_missing';
      await tapVisible(tester, 'pair-recheck-key');
      await tester.pumpAndSettle();
      expect(find.textContaining('未找到原设备密钥'), findsOneWidget);
      fault = 'device_key_store_unavailable';
      await tapVisible(tester, 'pair-recheck-key');
      await tester.pumpAndSettle();
      expect(find.textContaining('请配置 Secret Service'), findsOneWidget);
      fault = null;
      await tapVisible(tester, 'pair-recheck-key');
      await tester.pumpAndSettle();
      expect(find.textContaining('本机原身份已匹配'), findsOneWidget);
      expect(reads, 4);
      expect(storage.contents, stored);
      await tester.pumpWidget(const SizedBox());
    },
    variant: linux,
  );

  testWidgets(
    'restart only rechecks the reserved handle after an unknown write',
    (tester) async {
      final storage = MemoryCatalogStorage();
      final initial = HostCatalog(clock: () => 1000, storage: storage);
      addTearDown(initial.dispose);
      await initial.load();
      await saveCatalogProfile(initial);
      final target = {...fixtureConfig(), 'paneId': ''};
      await initial.beginCreation(target, '待确认', reservedHandle: handle);
      final original = storage.contents;
      final catalog = HostCatalog(clock: () => 1000, storage: storage);
      addTearDown(catalog.dispose);
      var lookups = 0;
      messenger.setMockMethodCallHandler(NativeDeviceKeys.channel, (
        call,
      ) async {
        expect(call.method, 'public');
        expect(call.arguments, {'handle': handle});
        lookups++;
        if (lookups == 1) throw PlatformException(code: 'device_key_missing');
        return expectedPublic;
      });
      final tokens = (await tester.runAsync(DesignTokens.load))!;
      await tester.pumpWidget(
        MaterialApp(
          home: HostCatalogPage(
            tokens: tokens,
            catalog: catalog,
            offlineBuilder: (_) => const SizedBox(),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tapVisible(tester, 'hosts-recheck-pending');
      await tester.pumpAndSettle();
      expect(find.textContaining('未找到原设备密钥'), findsOneWidget);
      await tapVisible(tester, 'hosts-recheck-pending');
      await tester.pumpAndSettle();
      expect(find.textContaining('已找到原设备密钥'), findsOneWidget);
      expect(lookups, 2);
      expect(storage.contents, original);
      await tester.pumpWidget(const SizedBox());
    },
    variant: linux,
  );

  testWidgets(
    'signer preserves the reason when the keyring changes after public lookup',
    (tester) async {
      final store = NativeDeviceKeys();
      final challenge = Uint8List.fromList([1, 2, 3, 4]);
      final reasons = [
        'device_key_locked',
        'device_key_missing',
        'device_key_store_unavailable',
      ];
      var signCalls = 0;
      messenger.setMockMethodCallHandler(NativeDeviceKeys.channel, (
        call,
      ) async {
        if (call.method == 'public') {
          expect(call.arguments, {'handle': handle});
          return expectedPublic;
        }
        expect(call.method, 'sign');
        expect(call.arguments, {'handle': handle, 'payload': challenge});
        throw PlatformException(code: reasons[signCalls++]);
      });
      final public = await store.public(handle);
      final identity = DeviceIdentityLease(store, handle, public).identity();
      for (final reason in reasons) {
        await expectLater(
          identity.sign(challenge),
          throwsA(
            isA<RemoteFailure>().having(
              (failure) => failure.code,
              'code',
              reason,
            ),
          ),
        );
      }
      expect(signCalls, reasons.length);
    },
    variant: linux,
  );
}
