import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'package:herdr_flutter_probe/zerotier_device.dart';
import 'host_catalog_test.dart' show MemoryCatalogStorage;
import 'network_profiles_test.dart' show testNetwork;

Map<String,Object> deviceReply() => {'handle':'a0000000-0000-4000-8000-000000000001','instanceId':'b0000000-0000-4000-8000-000000000002'};
Map<String,Object?> statusReply({Object? device,Object? creation,Object? deletion,bool available=true}) =>
  {'available':available,'device':device,'pendingCreation':creation,'pendingDeletion':deletion};
ZeroTierDeviceStatus pendingState(String action,String phase,{String? handle}) {
  final pending = {'handle':handle ?? deviceReply()['handle'],'phase':phase};
  return ZeroTierDeviceStatus.checked(action == 'recoverPendingDeletion' ? statusReply(deletion:pending) : statusReply(creation:pending));
}
class MemoryZeroTierDeviceStore implements ZeroTierDeviceStore {
  ZeroTierDeviceStatus current = ZeroTierDeviceStatus.checked(statusReply());
  int reads = 0,creates = 0,forgets = 0,recoveries = 0,discards = 0,deletionRecoveries = 0;
  bool readFails = false,unknownWrite = false,rejectPending = false;
  Completer<void>? createWait,forgetWait,readWait,pendingWait;
  @override Future<ZeroTierDeviceStatus> status() async {
    reads++; final captured = current; await readWait?.future;
    if (readFails) throw const RemoteFailure('unavailable'); return captured;
  }
  @override Future<ZeroTierDevice> create(ZeroTierDeviceImpact impact) async {
    creates++; await createWait?.future;
    current = ZeroTierDeviceStatus.checked(statusReply(device:deviceReply()));
    if (unknownWrite) throw const RemoteFailure('unknown'); return current.device!;
  }
  @override Future<void> forget(ZeroTierDevice device,ZeroTierDeviceImpact impact) async {
    forgets++; expect(device.same(current.device!),isTrue); await forgetWait?.future;
    current = ZeroTierDeviceStatus.checked(statusReply());
    if (unknownWrite) throw const RemoteFailure('unknown');
  }
  Future<void> checkPending(ZeroTierPending pending,{required bool creation}) async {
    await pendingWait?.future;
    final actual = creation ? current.pendingCreation : current.pendingDeletion;
    if (rejectPending || actual?.same(pending) != true) throw const RemoteFailure('pending_changed');
  }
  @override Future<ZeroTierDevice> recoverPendingCreation(ZeroTierPending pending,ZeroTierDeviceImpact impact) async {
    recoveries++; await checkPending(pending,creation:true);
    current = ZeroTierDeviceStatus.checked(statusReply(device:{...deviceReply(),'handle':pending.handle}));
    if (unknownWrite) throw const RemoteFailure('unknown'); return current.device!;
  }
  @override Future<void> discardPendingCreation(ZeroTierPending pending,ZeroTierDeviceImpact impact) async {
    discards++; await checkPending(pending,creation:true); current = ZeroTierDeviceStatus.checked(statusReply());
    if (unknownWrite) throw const RemoteFailure('unknown');
  }
  @override Future<void> recoverPendingDeletion(ZeroTierPending pending,ZeroTierDeviceImpact impact) async {
    deletionRecoveries++; await checkPending(pending,creation:false); current = ZeroTierDeviceStatus.checked(statusReply());
    if (unknownWrite) throw const RemoteFailure('unknown');
  }
}
/// A new frontend store object viewing the same synthetic native state.
class MemoryZeroTierDeviceView implements ZeroTierDeviceStore {
  MemoryZeroTierDeviceView(this.backend);
  final MemoryZeroTierDeviceStore backend;
  @override Future<ZeroTierDeviceStatus> status() => backend.status();
  @override Future<ZeroTierDevice> create(ZeroTierDeviceImpact impact) => backend.create(impact);
  @override Future<void> forget(ZeroTierDevice device,ZeroTierDeviceImpact impact) => backend.forget(device,impact);
  @override Future<ZeroTierDevice> recoverPendingCreation(ZeroTierPending pending,ZeroTierDeviceImpact impact) => backend.recoverPendingCreation(pending,impact);
  @override Future<void> discardPendingCreation(ZeroTierPending pending,ZeroTierDeviceImpact impact) => backend.discardPendingCreation(pending,impact);
  @override Future<void> recoverPendingDeletion(ZeroTierPending pending,ZeroTierDeviceImpact impact) => backend.recoverPendingDeletion(pending,impact);
}
Future<HostCatalog> zeroTierCatalog() async {
  final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
  await catalog.addNetwork(testNetwork('zerotier')); return catalog;
}
ZeroTierDeviceSession deviceSession(HostCatalog catalog,MemoryZeroTierDeviceStore store,{BeforeZeroTierForget? beforeForget}) =>
  ZeroTierDeviceSession(store:store,impact:() => ZeroTierDeviceImpact.capture(catalog),beforeForget:beforeForget);

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test('metadata is exact and rejects secrets, non-v4 UUIDs and invented phases',() {
    final valid = statusReply(device:deviceReply());
    for (final bad in [
      {...valid,'privateIdentity':'forbidden'}, {...valid,'available':1},
      statusReply(device:{...deviceReply(),'handle':'A0000000-0000-4000-8000-000000000001'}),
      statusReply(device:{...deviceReply(),'instanceId':'b0000000-0000-1000-8000-000000000002'}),
      statusReply(device:{...deviceReply(),'nodeId':'invented'}),
      statusReply(creation:{'handle':deviceReply()['handle'],'phase':'running'}),
      statusReply(deletion:{'handle':deviceReply()['handle'],'phase':'record-pending'}),
      statusReply(creation:{'handle':deviceReply()['handle'],'phase':'record-removed'}),
      statusReply(device:deviceReply(),available:false),
      statusReply(device:deviceReply(),creation:{'handle':deviceReply()['handle'],'phase':'finishing'}),
    ]) { expect(() => ZeroTierDeviceStatus.checked(bad),throwsA(isA<RemoteFailure>())); }
    expect(ZeroTierDeviceStatus.checked(valid).device!.handle,deviceReply()['handle']);
    for (final phase in ['record-present','record-pending','finishing']) {
      expect(ZeroTierDeviceStatus.checked(statusReply(creation:{'handle':deviceReply()['handle'],'phase':phase})).absent,isFalse);
    }
  });
  test('only a successful available absence status permits create',() async {
    final catalog = await zeroTierCatalog(),store = MemoryZeroTierDeviceStore()..readFails = true;
    final s = deviceSession(catalog,store); expect(s.canCreate,isFalse); await s.refresh();
    await s.create(); expect(store.creates,0); expect(s.canCreate,isFalse);
    store.readFails = false; store.current = const ZeroTierDeviceStatus.unavailable(); await s.refresh(); await s.create();
    expect(store.creates,0); store.current = ZeroTierDeviceStatus.checked(statusReply()); await s.refresh();
    expect(s.canCreate,isTrue); await s.create(); expect(store.creates,1); expect(s.canCreate,isFalse);
    s.dispose(); catalog.dispose();
  });
  test('unknown creation reads original state, never replays or recovers',() async {
    final catalog = await zeroTierCatalog(),store = MemoryZeroTierDeviceStore()..unknownWrite = true;
    final s = deviceSession(catalog,store); await s.refresh(); await s.create(); await s.create(); await s.refresh();
    expect(store.creates,1); expect(store.forgets,0); expect(store.recoveries,0); expect(store.discards,0);
    expect(s.status!.device,isNotNull); s.dispose(); catalog.dispose();
  });
  test('forget requires exact two-step review and successful native retirement callback',() async {
    final catalog = await zeroTierCatalog(),store = MemoryZeroTierDeviceStore()..current = ZeroTierDeviceStatus.checked(statusReply(device:deviceReply()));
    var stopped = 0;
    final s = deviceSession(catalog,store,beforeForget:(review) async {
      expect(review.impact.networks.length,1); expect(review.device.instanceId,deviceReply()['instanceId']); stopped++;
    });
    await s.refresh(); expect(store.forgets,0); s.beginReview(); final review = s.review!;
    await s.forget(review); await s.forget(review);
    expect(stopped,1); expect(store.forgets,1); expect(s.status!.absent,isTrue); expect(s.review,isNull);
    s.dispose(); catalog.dispose();
  });
  test('missing or failed retirement proof cannot delete',() async {
    final catalog = await zeroTierCatalog(),store = MemoryZeroTierDeviceStore()..current = ZeroTierDeviceStatus.checked(statusReply(device:deviceReply()));
    final noProof = deviceSession(catalog,store); await noProof.refresh(); noProof.beginReview(); expect(noProof.review,isNull); noProof.dispose();
    final s = deviceSession(catalog,store,beforeForget:(_) async { throw const RemoteFailure('not_retired'); });
    await s.refresh(); s.beginReview(); await s.forget(s.review!); expect(store.forgets,0); expect(s.status!.device,isNotNull);
    s.dispose(); catalog.dispose();
  });
  test('catalog changes while retirement is pending consume and invalidate old review',() async {
    final catalog = await zeroTierCatalog(),store = MemoryZeroTierDeviceStore()..current = ZeroTierDeviceStatus.checked(statusReply(device:deviceReply()));
    final stop = Completer<void>(),s = deviceSession(catalog,store,beforeForget:(_) => stop.future);
    await s.refresh(); s.beginReview(); final work = s.forget(s.review!);
    await catalog.addNetwork(testNetwork('zerotier')); s.invalidate(); stop.complete(); await work;
    expect(store.forgets,0); expect(s.status,isNull); expect(s.review,isNull); expect(s.canCreate,isFalse);
    s.dispose(); catalog.dispose();
  });
  test('changed native instance after review cannot delete original handle',() async {
    final catalog = await zeroTierCatalog(),store = MemoryZeroTierDeviceStore()..current = ZeroTierDeviceStatus.checked(statusReply(device:deviceReply()));
    final s = deviceSession(catalog,store,beforeForget:(_) async {
      store.current = ZeroTierDeviceStatus.checked(statusReply(device:{...deviceReply(),'instanceId':'c0000000-0000-4000-8000-000000000003'}));
    });
    await s.refresh(); s.beginReview(); await s.forget(s.review!); expect(store.forgets,0); expect(s.review,isNull);
    s.dispose(); catalog.dispose();
  });
  test('background during stop proof blocks late forget dispatch',() async {
    final catalog = await zeroTierCatalog(),store = MemoryZeroTierDeviceStore()..current = ZeroTierDeviceStatus.checked(statusReply(device:deviceReply()));
    final stop = Completer<void>(),s = deviceSession(catalog,store,beforeForget:(_) => stop.future);
    await s.refresh(); s.beginReview(); final work = s.forget(s.review!); s.suspend();
    stop.complete(); await work; expect(store.forgets,0); expect(s.status,isNull); expect(s.review,isNull);
    await s.resume(); expect(store.forgets,0); expect(s.status!.device,isNotNull);
    s.dispose(); catalog.dispose();
  });
  test('failed read after stop rejection cannot retain formerly known metadata',() async {
    final catalog = await zeroTierCatalog(),store = MemoryZeroTierDeviceStore()..current = ZeroTierDeviceStatus.checked(statusReply(device:deviceReply()));
    final s = deviceSession(catalog,store,beforeForget:(_) async { store.readFails = true; throw const RemoteFailure('not_retired'); });
    await s.refresh(); s.beginReview(); await s.forget(s.review!);
    expect(store.forgets,0); expect(s.status,isNull); expect(s.canReview,isFalse); expect(s.canCreate,isFalse);
    s.dispose(); catalog.dispose();
  });
  test('unknown forget only reads, does not retry or recreate',() async {
    final catalog = await zeroTierCatalog(),store = MemoryZeroTierDeviceStore()..unknownWrite = true
      ..current = ZeroTierDeviceStatus.checked(statusReply(device:deviceReply()));
    final s = deviceSession(catalog,store,beforeForget:(_) async {}); await s.refresh(); s.beginReview(); await s.forget(s.review!);
    expect(store.forgets,1); expect(store.creates,0); expect(s.notice,contains('未确认')); await s.refresh(); expect(store.forgets,1);
    s.dispose(); catalog.dispose();
  });
  test('background during create rejects late success and resumes with read only',() async {
    final catalog = await zeroTierCatalog(),store = MemoryZeroTierDeviceStore()..createWait = Completer<void>();
    final s = deviceSession(catalog,store); await s.refresh(); final work = s.create(); s.suspend();
    store.createWait!.complete(); await work; expect(s.status,isNull); expect(s.canCreate,isFalse);
    await s.resume(); expect(s.status!.device,isNotNull); expect(store.creates,1); expect(store.forgets,0);
    s.dispose(); catalog.dispose();
  });
  test('late status cannot restore a review after background',() async {
    final catalog = await zeroTierCatalog(),store = MemoryZeroTierDeviceStore()..readWait = Completer<void>();
    final s = deviceSession(catalog,store); final work = s.refresh(); s.suspend(); store.readWait!.complete(); await work;
    expect(s.status,isNull); expect(s.canCreate,isFalse); s.dispose(); catalog.dispose();
  });
  test('new session and store cannot replay pending creation after old view closes',() async {
    final catalog = await zeroTierCatalog(),store = MemoryZeroTierDeviceStore()..createWait = Completer<void>()..unknownWrite = true;
    final original = deviceSession(catalog,store); await original.refresh(); final work = original.create(); original.dispose();
    final reopened = ZeroTierDeviceSession(store:MemoryZeroTierDeviceView(store),impact:() => ZeroTierDeviceImpact.capture(catalog));
    await reopened.refresh(); await reopened.create();
    expect(reopened.writePending,isTrue); expect(reopened.canCreate,isFalse); expect(reopened.status,isNull);
    expect(store.creates,1); expect(store.reads,1);
    store.createWait!.complete(); await work;
    // The coordinator schedules only a read after the exact old Future settles.
    await Future<void>.delayed(Duration.zero);
    expect(reopened.writePending,isFalse); expect(reopened.status!.device,isNotNull);
    expect(store.creates,1); expect(store.reads,2); expect(store.forgets,0);
    reopened.dispose(); catalog.dispose();
  });
  test('closing during forget preflight keeps reopened view read-only until original settles',() async {
    final catalog = await zeroTierCatalog(),store = MemoryZeroTierDeviceStore()..current = ZeroTierDeviceStatus.checked(statusReply(device:deviceReply()));
    final stop = Completer<void>(),original = deviceSession(catalog,store,beforeForget:(_) => stop.future);
    await original.refresh(); original.beginReview(); final work = original.forget(original.review!); original.dispose();
    final reopened = ZeroTierDeviceSession(store:MemoryZeroTierDeviceView(store),impact:() => ZeroTierDeviceImpact.capture(catalog),beforeForget:(_) async {});
    await reopened.refresh(); reopened.beginReview(); expect(reopened.review,isNull); expect(reopened.canCreate,isFalse);
    expect(store.forgets,0); expect(store.reads,1);
    stop.complete(); await work; await Future<void>.delayed(Duration.zero);
    expect(reopened.writePending,isFalse); expect(reopened.canReview,isTrue);
    expect(store.forgets,0); expect(store.creates,0); expect(store.reads,2);
    reopened.dispose(); catalog.dispose();
  });
  test('native contract carries public exact instance and fails closed for missing bridge',() async {
    debugDefaultTargetPlatformOverride = TargetPlatform.android; addTearDown(() => debugDefaultTargetPlatformOverride = null);
    final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger,methods = <String>[];
    final catalog = await zeroTierCatalog(),impact = ZeroTierDeviceImpact.capture(catalog);
    final review = {'catalogRevision':catalog.revision,'profileIds':catalog.networkProfiles.map((p) => p.id).toList(),'hostIds':<String>[]};
    messenger.setMockMethodCallHandler(NativeZeroTierDeviceStore.channel,(call) async {
      methods.add(call.method);
      if (call.method == 'status') { expect(call.arguments,isNull); return statusReply(device:deviceReply()); }
      if (call.method == 'create') { expect(call.arguments,review); return deviceReply(); }
      if (call.method == 'forget') { expect(call.arguments,{...review,...deviceReply()}); return null; }
      expect(call.arguments,{...review,'handle':deviceReply()['handle'],'expectedPhase':call.method == 'discardPendingCreation' ? 'record-pending' : 'record-present'});
      return call.method == 'recoverPendingCreation' ? deviceReply() : null;
    });
    final store = NativeZeroTierDeviceStore(),device = await store.create(impact); await store.status(); await store.forget(device,impact);
    await store.recoverPendingCreation(ZeroTierPending.checked({'handle':device.handle,'phase':'record-present'},creation:true),impact);
    await store.discardPendingCreation(ZeroTierPending.checked({'handle':device.handle,'phase':'record-pending'},creation:true),impact);
    await store.recoverPendingDeletion(ZeroTierPending.checked({'handle':device.handle,'phase':'record-present'},creation:false),impact);
    expect(methods,['create','status','forget','recoverPendingCreation','discardPendingCreation','recoverPendingDeletion']);
    messenger.setMockMethodCallHandler(NativeZeroTierDeviceStore.channel,null);
    expect((await store.status()).available,isFalse); expect((await store.status()).absent,isFalse); catalog.dispose();
  });
  test('native recovery rejects a well-formed result for a different pending handle',() async {
    debugDefaultTargetPlatformOverride = TargetPlatform.android; addTearDown(() => debugDefaultTargetPlatformOverride = null);
    final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    final catalog = await zeroTierCatalog(),impact = ZeroTierDeviceImpact.capture(catalog);
    var calls = 0;
    messenger.setMockMethodCallHandler(NativeZeroTierDeviceStore.channel,(call) async {
      calls++; expect(call.method,'recoverPendingCreation');
      expect((call.arguments as Map)['handle'],deviceReply()['handle']);
      return {...deviceReply(),'handle':'c0000000-0000-4000-8000-000000000003'};
    });
    addTearDown(() { messenger.setMockMethodCallHandler(NativeZeroTierDeviceStore.channel,null); catalog.dispose(); });
    await expectLater(NativeZeroTierDeviceStore().recoverPendingCreation(ZeroTierPending.checked({'handle':deviceReply()['handle'],'phase':'record-present'},creation:true),impact),
      throwsA(isA<RemoteFailure>().having((error) => error.code,'code','zerotier_device_write_unknown')));
    expect(calls,1);
  });
  test('pending action policy uses exact observed phases and blocks replacement creation',() async {
    final catalog = await zeroTierCatalog(),store = MemoryZeroTierDeviceStore();
    final s = deviceSession(catalog,store);
    for (final phase in ['record-present','record-pending','finishing']) {
      store.current = pendingState('recoverPendingCreation',phase); await s.refresh();
      expect(s.canCreate,isFalse);
      expect(s.canReviewPending('recoverPendingCreation'),phase != 'record-pending');
      expect(s.canReviewPending('discardPendingCreation'),phase != 'record-present');
      expect(s.canReviewPending('recoverPendingDeletion'),isFalse);
    }
    for (final phase in ['record-present','record-removed','finishing']) {
      store.current = pendingState('recoverPendingDeletion',phase); await s.refresh();
      expect(s.canReviewPending('recoverPendingDeletion'),isTrue);
      expect(s.canReviewPending('recoverPendingCreation'),isFalse); expect(s.canCreate,isFalse);
    }
    expect(store.recoveries + store.discards + store.deletionRecoveries,0); s.dispose(); catalog.dispose();
  });
  test('pending recovery requires explicit current review and then reads exact restored identity',() async {
    final catalog = await zeroTierCatalog(),store = MemoryZeroTierDeviceStore()..current = pendingState('recoverPendingCreation','record-present');
    final s = deviceSession(catalog,store); await s.refresh(); expect(store.recoveries,0);
    s.beginPendingReview('recoverPendingCreation'); final review = s.pendingReview!;
    expect(review.impact.networks.length,1); await s.confirmPending(review); await s.confirmPending(review);
    expect(store.recoveries,1); expect(s.status!.device!.handle,deviceReply()['handle']);
    expect(s.notice,contains('已恢复')); expect(store.creates,0); s.dispose(); catalog.dispose();
  });
  test('changed phase or handle after review refuses mutation instead of switching recovery action',() async {
    final catalog = await zeroTierCatalog(),store = MemoryZeroTierDeviceStore();
    final s = deviceSession(catalog,store);
    for (final changed in [pendingState('recoverPendingCreation','finishing'),pendingState('recoverPendingCreation','record-present',handle:'d0000000-0000-4000-8000-000000000004')]) {
      store.current = pendingState('recoverPendingCreation','record-present'); await s.refresh();
      s.beginPendingReview('recoverPendingCreation'); final review = s.pendingReview!;
      store.current = changed; await s.confirmPending(review);
      expect(store.recoveries,0); expect(store.discards,0); expect(store.forgets,0); expect(s.pendingReview,isNull);
      expect(s.notice,contains('未确认')); expect(s.status!.pendingCreation!.same(changed.pendingCreation!),isTrue);
    }
    s.dispose(); catalog.dispose();
  });
  test('finishing discard rejection never claims the identity was absent or discarded',() async {
    final catalog = await zeroTierCatalog(),store = MemoryZeroTierDeviceStore()..current = pendingState('discardPendingCreation','finishing')..rejectPending = true;
    final s = deviceSession(catalog,store); await s.refresh(); s.beginPendingReview('discardPendingCreation');
    await s.confirmPending(s.pendingReview!);
    expect(store.discards,1); expect(s.status!.absent,isFalse); expect(s.status!.pendingCreation!.phase,'finishing');
    expect(s.notice,contains('未确认')); expect(store.recoveries,0); expect(store.creates,0);
    s.dispose(); catalog.dispose();
  });
  test('unknown pending results only read and never replay, fallback to forget, or recreate',() async {
    final catalog = await zeroTierCatalog(),store = MemoryZeroTierDeviceStore()..unknownWrite = true;
    final s = deviceSession(catalog,store);
    for (final action in ['recoverPendingCreation','discardPendingCreation','recoverPendingDeletion']) {
      store.current = pendingState(action,action == 'discardPendingCreation' ? 'record-pending' : 'record-present'); await s.refresh();
      s.beginPendingReview(action); final review = s.pendingReview!; await s.confirmPending(review); await s.confirmPending(review);
      expect(s.notice,contains('未确认')); await s.refresh();
    }
    expect(store.recoveries,1); expect(store.discards,1); expect(store.deletionRecoveries,1);
    expect(store.forgets,0); expect(store.creates,0); s.dispose(); catalog.dispose();
  });
  test('background and catalog changes invalidate pending review before any recovery',() async {
    final catalog = await zeroTierCatalog(),store = MemoryZeroTierDeviceStore()..current = pendingState('recoverPendingDeletion','record-removed');
    final s = deviceSession(catalog,store); await s.refresh(); s.beginPendingReview('recoverPendingDeletion'); final first = s.pendingReview!;
    s.suspend(); await s.confirmPending(first); expect(store.deletionRecoveries,0);
    await s.resume(); s.beginPendingReview('recoverPendingDeletion'); final second = s.pendingReview!;
    await catalog.addNetwork(testNetwork('zerotier')); s.invalidate(); await s.confirmPending(second);
    expect(store.deletionRecoveries,0); expect(s.pendingReview,isNull); s.dispose(); catalog.dispose();
  });
  test('closed pending recovery owns original Future across new store and view until read-only completion',() async {
    final catalog = await zeroTierCatalog(),store = MemoryZeroTierDeviceStore()..current = pendingState('recoverPendingDeletion','finishing')..pendingWait = Completer<void>();
    final original = deviceSession(catalog,store); await original.refresh(); original.beginPendingReview('recoverPendingDeletion');
    final work = original.confirmPending(original.pendingReview!); await Future<void>.delayed(Duration.zero);
    expect(store.deletionRecoveries,1); original.dispose();
    final reopened = ZeroTierDeviceSession(store:MemoryZeroTierDeviceView(store),impact:() => ZeroTierDeviceImpact.capture(catalog));
    await reopened.refresh(); reopened.beginPendingReview('recoverPendingDeletion'); expect(reopened.pendingReview,isNull); expect(reopened.canCreate,isFalse);
    store.pendingWait!.complete(); await work; await Future<void>.delayed(Duration.zero);
    expect(store.deletionRecoveries,1); expect(store.forgets,0); expect(store.creates,0); expect(reopened.status!.absent,isTrue);
    reopened.dispose(); catalog.dispose();
  });
  test('native pending phase policy rejects disallowed action before method dispatch',() async {
    debugDefaultTargetPlatformOverride = TargetPlatform.android; addTearDown(() => debugDefaultTargetPlatformOverride = null);
    final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    final catalog = await zeroTierCatalog(),impact = ZeroTierDeviceImpact.capture(catalog);
    var calls = 0; messenger.setMockMethodCallHandler(NativeZeroTierDeviceStore.channel,(call) async { calls++; return null; });
    addTearDown(() { messenger.setMockMethodCallHandler(NativeZeroTierDeviceStore.channel,null); catalog.dispose(); });
    final store = NativeZeroTierDeviceStore();
    await expectLater(store.recoverPendingCreation(pendingState('discardPendingCreation','record-pending').pendingCreation!,impact),throwsA(isA<RemoteFailure>()));
    await expectLater(store.discardPendingCreation(pendingState('recoverPendingCreation','record-present').pendingCreation!,impact),throwsA(isA<RemoteFailure>()));
    expect(calls,0);
  });
}
