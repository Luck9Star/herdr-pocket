import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'package:herdr_flutter_probe/remote_page.dart';
import 'remote_test_data.dart';

class PendingAdapter extends RemoteReadOnlyAdapter {
  final pending = Completer<RemoteSnapshot>();
  int calls = 0;
  @override
  Future<RemoteSnapshot> read(RemoteConfig config,{RemoteProgress? onProgress}) {
    calls++; generation++; return pending.future;
  }
  @override
  Future<void> cancel() async { generation++; }
}
Finder field(String name) => find.byKey(ValueKey('remote-$name'));

Future<void> prepare(WidgetTester tester,PendingAdapter adapter,Size size) async {
  tester.view.devicePixelRatio = 1; tester.view.physicalSize = size;
  addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetViewInsets);
  final tokens = (await tester.runAsync(DesignTokens.load))!;
  await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:RemotePage(tokens:tokens,adapter:adapter)));
  final values = fixtureConfig();
  for (final entry in values.entries) {
    if (entry.key == 'schemaVersion' || entry.key == 'reviewConfirmed') continue;
    await tester.ensureVisible(field(entry.key));
    await tester.enterText(field(entry.key),entry.value.toString());
    await tester.pump();
  }
}

void main() {
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
    adapter.pending.complete(const RemoteSnapshot(1,'probe','w1:p1','LATE PRIVATE OUTPUT'));
    await tester.pumpAndSettle();
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
}
