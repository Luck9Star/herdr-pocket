import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/host_tabs.dart';
import 'package:herdr_flutter_probe/host_task_summary.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'host_catalog_test.dart' show MemoryCatalogStorage;
import 'host_tabs_widget_test.dart' show tabProfile;
import 'host_task_summary_test.dart' show summaryBoard;

void main() {
  testWidgets('four destinations preserve the board and expose real controls', (tester) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(390, 844);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);
    final tokens = (await tester.runAsync(() async {
      final fontFile = File('/System/Library/Fonts/Supplemental/Arial Unicode.ttf');
      if (fontFile.existsSync()) {
        final font = FontLoader('ScreenChinese')..addFont(fontFile.readAsBytes().then((b) => ByteData.view(b.buffer)));
        await font.load();
      }
      final icons = FontLoader('MaterialIcons')..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'));
      await icons.load();
      return DesignTokens.load();
    }))!;
    final catalog = HostCatalog(storage: MemoryCatalogStorage(), clock: () => 1000);
    final tabs = HostTabs();
    await catalog.load();
    await tester.pumpWidget(RepaintBoundary(key: const ValueKey('capture'), child: MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: tokens.theme.copyWith(textTheme: tokens.theme.textTheme.apply(fontFamily: 'ScreenChinese'),
        chipTheme: tokens.theme.chipTheme.copyWith(labelStyle: TextStyle(fontFamily: 'ScreenChinese', color: tokens.color('textPrimary')))),
      home: HostCatalogPage(tokens: tokens, catalog: catalog, tabs: tabs, offlineBuilder: (_) => const Text('实验室')))));
    await tester.pumpAndSettle();
    Future<void> capture(String name) async {
      if (!Platform.environment.containsKey('HERDR_S01_CAPTURE')) return;
      final boundary = tester.renderObject<RenderRepaintBoundary>(find.byKey(const ValueKey('capture')));
      await tester.runAsync(() async {
        final image = await boundary.toImage(pixelRatio: 1);
        final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
        File('/tmp/herdr-s01-$name.png').writeAsBytesSync(bytes!.buffer.asUint8List());
        image.dispose();
      });
    }
    expect(find.text('还没有主机'), findsOneWidget);
    await capture('empty');
    await tester.tap(find.text('终端').last); await tester.pumpAndSettle();
    expect(find.textContaining('暂无打开的本地视图'), findsOneWidget);
    await tester.tap(find.text('网络').last); await tester.pumpAndSettle();
    expect(find.byType(NavigationBar), findsOneWidget);
    expect(find.textContaining('网络'), findsWidgets);
    await tester.tap(find.text('设置').last); await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('hosts-terminal-preferences')), findsOneWidget);
    expect(find.byKey(const ValueKey('hosts-transfer')), findsOneWidget);
    await tester.tap(find.text('看板').last); await tester.pumpAndSettle();
    final profile = tabProfile('工作站', 'build-session', '100.64.0.1', 'direct', 'fixture');
    await catalog.add(profile); await tester.pumpAndSettle();
    expect(find.byKey(ValueKey('host-open-${profile.id}')), findsOneWidget);
    expect(find.textContaining('状态未知'), findsWidgets);
    for (final name in ['all', 'current', 'history']) {
      final chip = find.byKey(ValueKey('hosts-filter-$name'));
      expect(tester.getSize(chip).height, greaterThanOrEqualTo(44));
      expect(tester.widget<ChoiceChip>(chip).label, isA<Text>());
    }
    await capture('host');
    final dynamic state = tester.state(find.byType(HostCatalogPage));
    final registry = state.summaries as HostTaskSummaries;
    final lease = registry.open(profile);
    final attempt = lease.begin()!;
    attempt.publish(summaryBoard(profile));
    await tester.pump(); await tester.pump();
    expect(find.textContaining('受阻窗格'), findsOneWidget);
    expect(find.textContaining('w1:p0'), findsOneWidget);
    expect(find.descendant(of:find.byKey(ValueKey('host-card-${profile.id}')),matching:find.text('待处理 1')), findsOneWidget);
    final card = find.byKey(ValueKey('host-card-${profile.id}'));
    expect(find.descendant(of:card, matching:find.text('会话 build-session')), findsOneWidget);
    final time = DateTime.utc(2026,11,7,10).toLocal();
    String two(int n) => n.toString().padLeft(2,'0');
    expect(find.descendant(of:card, matching:find.text(
      '同步 ${two(time.month)}-${two(time.day)} ${two(time.hour)}:${two(time.minute)}')), findsOneWidget);
    await capture('populated');
    attempt.publish(summaryBoard(profile, blocked: 2, revision: 2));
    final other = tabProfile('工作站', 'review-session', '100.64.0.2', 'direct', 'fixture-other');
    await catalog.add(other); await tester.pump(); await tester.pump();
    final otherLease = registry.open(other), otherAttempt = otherLease.begin()!;
    otherAttempt.publish(summaryBoard(other, blocked: 0)); await tester.pump(); await tester.pump();
    expect(find.text('w1:p0'), findsOneWidget); expect(find.text('w1:p1'), findsOneWidget);
    final secondCard=find.byKey(ValueKey('host-card-${other.id}'));
    final secondSession=find.descendant(of:secondCard,matching:find.text('会话 review-session'));
    final secondStatus=find.descendant(of:secondCard,matching:find.text('状态未知'));
    expect(secondSession,findsOneWidget); expect(secondStatus,findsOneWidget);
    expect(tester.getRect(secondSession).bottom,lessThan(tester.getRect(find.byType(NavigationBar)).top));
    for (final key in ['host-open-${profile.id}','host-management-${profile.id}']) {
      expect(tester.getSize(find.byKey(ValueKey(key))).height,greaterThanOrEqualTo(44));
    }
    await capture('multi-390');
    tester.view.physicalSize = const Size(320,844); await tester.pumpAndSettle();
    for (final name in ['all','current','history']) {
      final chip=find.byKey(ValueKey('hosts-filter-$name'));
      expect(tester.getRect(chip).right,lessThanOrEqualTo(304));
      expect(chip.hitTestable(),findsOneWidget);
    }
    await capture('multi-320');
    final secondOpen=find.byKey(ValueKey('host-open-${other.id}'));
    await tester.ensureVisible(secondOpen); await tester.pumpAndSettle();
    expect(secondOpen.hitTestable(),findsOneWidget);
    expect(tester.widget<FilledButton>(secondOpen).onPressed,isNotNull);
    await tester.ensureVisible(find.byKey(const ValueKey('hosts-search'))); await tester.pumpAndSettle();
    tester.platformDispatcher.textScaleFactorTestValue = 1.1;
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    await tester.pumpAndSettle();
    expect(secondSession,findsOneWidget);
    tester.platformDispatcher.textScaleFactorTestValue = 1.3;
    await tester.pumpAndSettle();
    for (final name in ['all','current','history']) {
      final chip=find.byKey(ValueKey('hosts-filter-$name'));
      expect(tester.getRect(chip).right,lessThanOrEqualTo(304));
      expect(tester.getSize(chip).height,greaterThanOrEqualTo(44));
      expect(chip.hitTestable(),findsOneWidget);
    }
    await capture('multi-320-large');
    await tester.tap(find.byKey(const ValueKey('hosts-filter-history'))); await tester.pumpAndSettle();
    expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('hosts-filter-history'))).selected,isTrue);
    await tester.tap(find.byKey(const ValueKey('hosts-filter-all'))); await tester.pumpAndSettle();
    tester.platformDispatcher.clearTextScaleFactorTestValue(); await tester.pumpAndSettle();
    tester.view.physicalSize = const Size(1200,844); await tester.pumpAndSettle(); await capture('multi-1200');
    tester.view.physicalSize = const Size(390,844); await tester.pumpAndSettle();
    attempt.publish(summaryBoard(profile, revision: 3, freshness: DashboardFreshness.unavailable));
    await tester.pump(); await tester.pump();
    final history = find.byKey(const ValueKey('hosts-filter-history'));
    await tester.ensureVisible(history); await tester.tap(history); await tester.pumpAndSettle();
    expect(tester.widget<ChoiceChip>(history).selected, isTrue);
    await capture('history');
    lease.close(); otherLease.close();
    await tester.ensureVisible(find.byKey(const ValueKey('hosts-direct-ssh')));
    await tester.tap(find.byKey(const ValueKey('hosts-direct-ssh'))); await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('direct-probe')), findsOneWidget);
    await tester.pumpWidget(const SizedBox()); tabs.dispose(); catalog.dispose();
  });
}
