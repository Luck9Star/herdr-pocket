import 'dart:async';
import 'dart:io';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart' show RenderParagraph;
import 'package:flutter_test/flutter_test.dart';
import 'package:terminal_view/terminal_view.dart';
import 'package:herdr_flutter_probe/config_transfer.dart';
import 'package:herdr_flutter_probe/config_transfer_page.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/host_tabs.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart' show RemoteFailure,RemoteFrame,RemotePane;
import 'host_catalog_test.dart' show MemoryCatalogStorage,catalogPairing;
import 'config_transfer_test.dart' show portable;
import 'pairing_gui_test.dart' show TestDeviceKeys,tapVisible;
import 'host_tabs_widget_test.dart' show TabFixtureAdapter,tabProfile,connectTab;
import 'import_widget_evidence.dart';
import 'remote_test_data.dart';

class MemoryConfigDocuments implements ConfigDocuments {
  Uint8List? opened;
  int saves = 0,opens = 0;
  @override Future<Uint8List?> open() async { opens++; return opened; }
  @override Future<bool> save(Uint8List archive) async { saves++; return false; }
}
class ImportSaveFixture extends MemoryCatalogStorage {
  String? failure;
  @override
  Future<String> save(String expected,String contents) async {
    final error = failure;
    if (error == 'catalog_conflict') throw const RemoteFailure('catalog_conflict');
    final revision = await super.save(expected,contents);
    if (error != null) throw RemoteFailure(error);
    return revision;
  }
}
class DelayedImportDeviceKeys extends TestDeviceKeys {
  DelayedImportDeviceKeys(super.pem);
  Completer<String>? pendingPublicKey;
  @override
  Future<String> public(String handle) => pendingPublicKey?.future ?? super.public(handle);
}
void main() {
  testWidgets('import recovery prevents a new dial after device key lookup was already started', (tester) async {
    final disk = ImportSaveFixture(), catalog = HostCatalog(storage:disk,clock:() => 1000);
    await catalog.load();
    final old = tabProfile('Import A','probeA','127.0.0.1','unspecified','opaque-delay-old');
    final peer = tabProfile('Pending B','probeB','127.0.0.2','unspecified','opaque-delay-peer');
    await catalog.add(old); await catalog.add(peer);
    final keys = DelayedImportDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
    final adapter = TabFixtureAdapter(), tabs = HostTabs(), tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:HostCatalogPage(tokens:tokens,catalog:catalog,tabs:tabs,
      keys:keys,adapterFactory:(_) => adapter,offlineBuilder:(_) => const SizedBox())));
    await tester.pumpAndSettle();
    await tapVisible(tester,'host-open-${peer.id}'); await tester.pumpAndSettle();
    await tapVisible(tester,'pair-connect'); await tester.pumpAndSettle();
    final pending = Completer<String>(), publicKey = await keys.public('fixture');
    keys.pendingPublicKey = pending;
    await tapVisible(tester,'remote-review'); await tapVisible(tester,'remote-connect');
    expect(adapter.calls,0);
    disk.failure = 'catalog_write_unknown';
    final plan = catalog.previewConfigImport(catalog.exportConfig({old.id},{}));
    await expectLater(catalog.applyConfigImport(plan,[const ConfigImportChoice(ConfigImportAction.replace)],beforeCommit:tabs.retireReplacedHosts),
      throwsA(isA<RemoteFailure>().having((error) => error.code,'code','catalog_write_unknown')));
    pending.complete(publicKey);
    keys.pendingPublicKey = null;
    await tester.pumpAndSettle();
    expect(adapter.calls,0);
    expect(keys.signCalls,0);
    expect(catalog.ready,isFalse);
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('remote-connect'))).onPressed,isNull);
    await catalog.load(); await tester.pumpAndSettle();
    expect(catalog.ready,isTrue);
    expect(adapter.calls,0);
    await tapVisible(tester,'remote-review'); await tapVisible(tester,'remote-connect');
    expect(adapter.calls,1);
    await tester.pumpWidget(const SizedBox()); tabs.dispose(); catalog.dispose();
  });
  testWidgets('390px settings import keeps the old screen readable and closes only its historical tab', (tester) async {
    tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(390,844);
    addTearDown(tester.view.reset);
    final disk = MemoryCatalogStorage(), catalog = HostCatalog(storage:disk,clock:() => 1000);
    await catalog.load();
    final old = tabProfile('开发 A','probeA','127.0.0.1','unspecified','opaque-mobile-a');
    final peer = tabProfile('验证 B','probeB','127.0.0.2','unspecified','opaque-mobile-b');
    await catalog.add(old); await catalog.add(peer);
    final a = TabFixtureAdapter(), b = TabFixtureAdapter(), tabs = HostTabs();
    final tokens = (await tester.runAsync(DesignTokens.load))!, captureKey = GlobalKey();
    final outputs = Platform.environment['HERDR_M105_MOBILE_EVIDENCE'];
    final theme = outputs == null ? tokens.theme : (await tester.runAsync(() => loadImportEvidenceFonts(
      tokens.theme,Platform.environment['HERDR_S06_CJK_FONT'])))!;
    Future<void> capture(String name) async {
      expect(tester.takeException(),isNull);
      if (outputs != null) await captureImportEvidence(tester,captureKey,File('$outputs/$name.png'));
    }
    final config = catalog.exportConfig({old.id},{});
    const passphrase = 'local mobile fixture archive';
    final archive = (await tester.runAsync(() => encryptPortableConfig(passphrase,config)))!;
    final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(NativeConfigDocuments.channel,(call) async {
      expect(call.method,'open'); return archive;
    });
    addTearDown(() => messenger.setMockMethodCallHandler(NativeConfigDocuments.channel,null));
    await tester.pumpWidget(RepaintBoundary(key:captureKey,child:MaterialApp(debugShowCheckedModeBanner:false,theme:theme,home:HostCatalogPage(tokens:tokens,catalog:catalog,tabs:tabs,
      keys:TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String),adapterFactory:(p) => p.id == old.id ? a : b,offlineBuilder:(_) => const SizedBox()))));
    await tester.pumpAndSettle();
    await tapVisible(tester,'host-open-${old.id}'); await tester.pumpAndSettle();
    await tapVisible(tester,'pair-connect'); await tester.pumpAndSettle(); await connectTab(tester,a);
    const oldMarker = 'A LAST FRAME / M1-05';
    a.frame!(a.generation,'w1:p1',const RemoteFrame(1,false,'\x1b[22;1H$oldMarker'));
    await tester.pump();
    final oldTab = tabs.active!, original = tester.widget<TerminalView>(find.byType(TerminalView)).terminal;
    await tapVisible(tester,'hosts-board-tab');
    await tapVisible(tester,'host-open-${peer.id}'); await tester.pumpAndSettle();
    await tapVisible(tester,'pair-connect'); await tester.pumpAndSettle(); await connectTab(tester,b);
    final survivor = tabs.active!, bGeneration = b.generation, bTarget = b.inputTarget;
    expect(bTarget,isNotNull);
    await tester.tap(find.widgetWithIcon(NavigationDestination,Icons.settings_outlined)); await tester.pumpAndSettle();
    expect(b.inputTarget,same(bTarget)); expect(b.pauses,0);
    await tapVisible(tester,'hosts-transfer'); await tester.pumpAndSettle(); await tapVisible(tester,'transfer-open');
    final password = find.byKey(const ValueKey('transfer-password')), decrypt = find.byKey(const ValueKey('transfer-decrypt'));
    await tester.ensureVisible(password); await tester.enterText(password,passphrase);
    final controller = tester.widget<TextField>(password).controller!;
    await tester.ensureVisible(decrypt); await tester.pumpAndSettle();
    await tester.runAsync(() async {
      await tester.tap(decrypt);
      final deadline = DateTime.now().add(const Duration(seconds:30));
      while (controller.text.isNotEmpty && DateTime.now().isBefore(deadline)) {
        await Future<void>.delayed(const Duration(milliseconds:20));
      }
      expect(controller.text,isEmpty);
    });
    await tester.pumpAndSettle();
    final choice = find.byKey(const ValueKey('transfer-choice-0'));
    await tester.ensureVisible(choice); await tester.pumpAndSettle();
    await tester.tap(find.descendant(of:choice,matching:find.byIcon(Icons.arrow_drop_down)).hitTestable());
    await tester.pumpAndSettle(); await tester.tap(find.text('替换全部冲突').hitTestable().last); await tester.pumpAndSettle();
    await tapVisible(tester,'transfer-review');
    final apply = find.byKey(const ValueKey('transfer-apply'));
    await tester.ensureVisible(apply); await tester.pumpAndSettle();
    expect(apply.hitTestable(),findsOneWidget);
    final affected = find.byKey(ValueKey('transfer-affected-tab-${oldTab.id}'));
    expect(affected.hitTestable(),findsOneWidget);
    expect(find.byKey(ValueKey('transfer-affected-tab-${survivor.id}')),findsNothing);
    await capture('mobile-import-review');
    await tester.tap(apply); await tester.pumpAndSettle();
    expect(oldTab.view.value.state,'retired'); expect(tabs.tabs,[oldTab,survivor]);
    expect(b.inputTarget,same(bTarget)); expect(b.generation,bGeneration);
    await tester.pageBack(); await tester.pumpAndSettle();
    await tester.tap(find.widgetWithIcon(NavigationDestination,Icons.terminal)); await tester.pumpAndSettle();
    expect(survivor.inputEligible.value,isTrue);
    await tapVisible(tester,'host-tab-${oldTab.id}'); await tester.pumpAndSettle();
    final historical = find.byKey(ValueKey('retired-host-view-${oldTab.id}'));
    expect(historical,findsOneWidget);
    expect(find.text('仅可查看最后画面。可手动关闭此标签。'),findsOneWidget);
    expect(find.textContaining('返回后需主动恢复并等待原目标新画面'),findsNothing);
    final oldTerminal = tester.widget<TerminalView>(find.descendant(of:historical,matching:find.byType(TerminalView)));
    expect(oldTerminal.readOnly,isTrue); expect(oldTerminal.terminal,same(original));
    expect(oldTerminal.terminal.onOutput,isNull);
    expect(oldTerminal.terminal.buffer.lines[21].getText(),contains(oldMarker));
    expect(find.byKey(const ValueKey('remote-connect')),findsNothing);
    expect(find.byKey(const ValueKey('remote-resume')),findsNothing);
    final close = find.byKey(ValueKey('host-tab-close-${oldTab.id}'));
    if (close.hitTestable().evaluate().isEmpty) {
      await tester.ensureVisible(close); await tester.pumpAndSettle();
    }
    expect(close.hitTestable(),findsOneWidget);
    await capture('mobile-import-retained');
    await tester.tap(close); await tester.pumpAndSettle();
    expect(tabs.tabs,[survivor]); expect(b.cancels,0); expect(b.calls,1); expect(b.generation,bGeneration);
    expect(historical,findsNothing);
    final remaining = find.byKey(ValueKey('host-tab-${survivor.id}'));
    expect(remaining,findsOneWidget);
    await tester.ensureVisible(remaining); await capture('mobile-import-closed');
    await tester.pumpWidget(const SizedBox()); tabs.dispose(); catalog.dispose();
  });
  for (final failure in ['catalog_conflict','catalog_write_unknown']) {
    testWidgets('failed import preserves the unrelated original observation while recovering catalog: $failure', (tester) async {
      tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(390,844);
      addTearDown(tester.view.reset);
      final disk = ImportSaveFixture(), catalog = HostCatalog(storage:disk,clock:() => 1000);
      await catalog.load();
      final old = tabProfile('Old','probeA','127.0.0.1','unspecified','opaque-import-old');
      final peer = tabProfile('Peer','probeB','127.0.0.2','unspecified','opaque-import-peer');
      await catalog.add(old); await catalog.add(peer);
      final adapter = TabFixtureAdapter(), tabs = HostTabs(), tokens = (await tester.runAsync(DesignTokens.load))!;
      await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:HostCatalogPage(tokens:tokens,catalog:catalog,tabs:tabs,
        keys:TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String),adapterFactory:(_) => adapter,offlineBuilder:(_) => const SizedBox())));
      await tester.pumpAndSettle();
      expect(tabs.open(old),isTrue); final affected = tabs.active!;
      await tester.pumpAndSettle();
      await tapVisible(tester,'host-open-${peer.id}'); await tester.pumpAndSettle();
      await tapVisible(tester,'pair-connect'); await tester.pumpAndSettle(); await connectTab(tester,adapter);
      final survivor = tabs.active!, generation = adapter.generation, target = adapter.inputTarget;
      final config = catalog.exportConfig({old.id},{}), plan = catalog.previewConfigImport(config);
      disk.failure = failure;
      await expectLater(catalog.applyConfigImport(plan,[const ConfigImportChoice(ConfigImportAction.replace)],beforeCommit:tabs.retireReplacedHosts),
        throwsA(isA<RemoteFailure>().having((error) => error.code,'code',failure)));
      await tester.pumpAndSettle();
      expect(catalog.ready,isFalse);
      expect(tabs.tabs,[affected,survivor]);
      expect(affected.retired,isTrue);
      expect(adapter.generation,generation);
      expect(adapter.inputTarget,same(target));
      expect(adapter.cancels,0);
      expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-direct'))).onSelected,isNull);
      await catalog.load(); await tester.pumpAndSettle();
      expect(catalog.ready,isTrue);
      expect(catalog.profiles.singleWhere((p) => p.id == old.id).retired,failure == 'catalog_write_unknown');
      expect(tabs.active,same(survivor));
      expect(tabs.tabs,[affected,survivor]);
      expect(adapter.generation,generation);
      expect(adapter.cancels,0);
      adapter.frame!(generation,'w1:p1',const RemoteFrame(1,false,'Original peer continued'));
      await tester.pump();
      expect(survivor.view.value.state,'live');
      expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-direct'))).onSelected,isNotNull);
      await tester.pumpWidget(const SizedBox()); tabs.dispose(); catalog.dispose();
    });
  }
  testWidgets('review from settings shows every tab for selected replacements only', (tester) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(540, 860);
    addTearDown(tester.view.reset);
    final disk = MemoryCatalogStorage();
    final catalog = HostCatalog(storage:disk,clock:() => 1000);
    final tabs = HostTabs();
    await catalog.load();
    Future<HostProfile> addHost(String label,String address) async {
      final original = HostProfile.create(label,{...fixtureConfig(),'host':address},catalogPairing(authorized:true),1000);
      final profile = HostProfile.fromJson({...original.toJson(),
        'pairing':{...original.pairingRecord,'handle':'fixture-device-handle-${address.split('.').first}'},
      },1000);
      await catalog.add(profile);
      return profile;
    }
    final first = await addHost('开发','development.invalid');
    final second = await addHost('验证','validation.invalid');
    final unrelated = await addHost('旁路','unrelated.invalid');
    await catalog.add(HostProfile.imported(portable(label:first.label,host:'unpaired.invalid'),1000));
    final writes = disk.writes;
    const password = 'fixture archive passphrase';
    final archive = (await tester.runAsync(() => encryptPortableConfig(password,PortableConfig.fromJson({
      'version':1,'hosts':[
        portable(label:first.label,host:'new-development.invalid').toJson(),
        portable(label:'验证新名称',host:'validation.invalid').toJson(),
      ],
    }))))!;
    final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    var opens = 0;
    messenger.setMockMethodCallHandler(NativeConfigDocuments.channel,(call) async {
      expect(call.method,'open');
      opens++;
      return archive;
    });
    addTearDown(() => messenger.setMockMethodCallHandler(NativeConfigDocuments.channel,null));
    final keys = TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:HostCatalogPage(tokens:tokens,catalog:catalog,
      tabs:tabs,keys:keys,offlineBuilder:(_) => const SizedBox())));
    await tester.pumpAndSettle();
    expect(tabs.open(first,requestedTarget:const RemotePane('pane-a','terminal-a')),isTrue);
    expect(tabs.open(first,requestedTarget:const RemotePane('pane-b','terminal-b')),isTrue);
    expect(tabs.open(second,requestedTarget:const RemotePane('pane-c','terminal-c')),isTrue);
    expect(tabs.open(unrelated,requestedTarget:const RemotePane('pane-d','terminal-d')),isTrue);
    final originalTabs = tabs.tabs;
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithIcon(NavigationDestination,Icons.settings_outlined));
    await tester.pumpAndSettle();
    await tapVisible(tester,'hosts-transfer');
    await tester.pumpAndSettle();
    expect(find.byType(ConfigTransferPage),findsOneWidget);
    expect(tabs.tabs,originalTabs);
    await tapVisible(tester,'transfer-open');
    await tester.pumpAndSettle();
    expect(opens,1);

    final passwordField = find.byKey(const ValueKey('transfer-password'));
    await tester.ensureVisible(passwordField);
    await tester.enterText(passwordField,password);
    final controller = tester.widget<TextField>(passwordField).controller!;
    final decrypt = find.byKey(const ValueKey('transfer-decrypt'));
    await tester.ensureVisible(decrypt);
    await tester.pumpAndSettle();
    await tester.runAsync(() async {
      await tester.tap(decrypt);
      final deadline = DateTime.now().add(const Duration(seconds:30));
      while (controller.text.isNotEmpty && DateTime.now().isBefore(deadline)) {
        await Future<void>.delayed(const Duration(milliseconds:20));
      }
      expect(controller.text,isEmpty);
    });
    await tester.pumpAndSettle();

    Finder picker(int index) => find.byKey(ValueKey('transfer-choice-$index'));
    Finder arrow(int index) => find.descendant(of:picker(index),matching:find.byIcon(Icons.arrow_drop_down));
    Future<void> choose(int index,String title) async {
      await tester.ensureVisible(picker(index));
      await tester.pumpAndSettle();
      expect(arrow(index).hitTestable(),findsOneWidget);
      await tester.tap(arrow(index).hitTestable());
      await tester.pumpAndSettle();
      final item = find.text(title).hitTestable().last;
      expect(item,findsOneWidget);
      await tester.tap(item);
      await tester.pumpAndSettle();
    }
    Future<void> expectFullChoice(int index,String title) async {
      final field = picker(index);
      await tester.ensureVisible(field);
      await tester.pumpAndSettle();
      final selected = find.descendant(of:field,matching:find.text(title)).hitTestable();
      final dropdownArrow = arrow(index).hitTestable();
      expect(selected,findsOneWidget);
      expect(dropdownArrow,findsOneWidget);
      final paragraph = tester.renderObject<RenderParagraph>(selected);
      expect(paragraph.getMaxIntrinsicWidth(double.infinity),lessThanOrEqualTo(paragraph.size.width+0.01));
      final viewport = tester.getRect(find.descendant(
        of:find.byType(ConfigTransferPage),matching:find.byType(SingleChildScrollView),
      ));
      final bounds = tester.getRect(field).intersect(viewport);
      final icon = tester.getRect(dropdownArrow);
      expect(bounds.intersect(icon),icon);
      final glyphs = paragraph.getBoxesForSelection(TextSelection(baseOffset:0,extentOffset:title.length));
      expect(glyphs,isNotEmpty);
      for (final glyph in glyphs) {
        final painted = glyph.toRect().shift(paragraph.localToGlobal(Offset.zero));
        expect(bounds.intersect(painted),painted);
        expect(painted.right,lessThan(icon.left));
      }
    }
    const replace = '替换全部冲突';
    const keep = '保留本机／跳过此条';
    const add = '添加新条目（不复用身份）';
    final impact = find.byKey(const ValueKey('transfer-impact'));
    Finder affected(HostTab tab) => find.descendant(of:impact,matching:find.byKey(ValueKey('transfer-affected-tab-${tab.id}')));
    expect(impact,findsNothing);
    expect(find.textContaining('替换时停用资料并保留本机身份'),findsNWidgets(2));
    expect(find.textContaining('未配对，替换时移除资料'),findsOneWidget);
    await choose(0,replace);
    expect(impact,findsOneWidget);
    expect(affected(originalTabs[0]),findsOneWidget);
    expect(affected(originalTabs[1]),findsOneWidget);
    expect(affected(originalTabs[2]),findsNothing);
    expect(affected(originalTabs[3]),findsNothing);
    expect(find.descendant(of:impact,matching:find.textContaining('pane-a · terminal-a')),findsOneWidget);
    expect(find.descendant(of:impact,matching:find.textContaining('pane-b · terminal-b')),findsOneWidget);
    expect(find.descendant(of:impact,matching:find.textContaining('停止连接')),findsOneWidget);
    expect(find.descendant(of:impact,matching:find.text('以上标签当前均不能从本机输入。')),findsOneWidget);
    expect(find.descendant(of:impact,matching:find.textContaining('fixture-device-handle')),findsNothing);

    tester.view.physicalSize = const Size(390, 844);
    await tester.pumpAndSettle();
    await expectFullChoice(0,replace);
    tester.view.physicalSize = const Size(320, 740);
    await tester.pumpAndSettle();
    await expectFullChoice(0,replace);
    await choose(1,replace);
    await expectFullChoice(1,replace);
    expect(affected(originalTabs[2]),findsOneWidget);
    expect(find.descendant(of:affected(originalTabs[2]),matching:find.textContaining('· 验证 · pane-c')),findsOneWidget);
    await choose(0,add);
    expect(affected(originalTabs[0]),findsNothing);
    expect(affected(originalTabs[1]),findsNothing);
    expect(affected(originalTabs[2]),findsOneWidget);
    await choose(1,keep);
    await expectFullChoice(1,keep);
    expect(impact,findsNothing);
    await choose(0,replace);
    expect(affected(originalTabs[0]),findsOneWidget);
    expect(affected(originalTabs[1]),findsOneWidget);
    expect(affected(originalTabs[2]),findsNothing);
    await tapVisible(tester,'transfer-review');
    await tester.pumpAndSettle();
    final apply = find.byKey(const ValueKey('transfer-apply'));
    await tester.ensureVisible(apply);
    await tester.pumpAndSettle();
    expect(apply.hitTestable(),findsOneWidget);
    expect(tester.widget<FilledButton>(apply).onPressed,isNotNull);
    expect(tester.takeException(),isNull);
    expect(tabs.tabs,originalTabs);
    expect(disk.writes,writes);
    expect(keys.signCalls,0);

    expect(tabs.open(first,requestedTarget:const RemotePane('pane-new','terminal-new')),isTrue);
    final newTab = tabs.active!;
    await tester.pumpAndSettle();
    expect(affected(newTab),findsOneWidget);
    expect(find.descendant(of:affected(newTab),matching:find.textContaining('输入焦点将撤回')),findsOneWidget);
    expect(tester.widget<CheckboxListTile>(find.byKey(const ValueKey('transfer-review'))).value,isFalse);
    expect(tester.widget<FilledButton>(apply).onPressed,isNull);
    expect(disk.writes,writes);

    // Reconfirm the updated scope and use the real settings import action.
    // Tabs outside this replacement, including the same-named new profile's
    // future tabs, are identified by their own profile IDs.
    final close = Completer<void>();
    var closes = 0;
    newTab.registerTransport(() { closes++; return close.future; });
    await tapVisible(tester,'transfer-review');
    await tapVisible(tester,'transfer-apply');
    expect(disk.writes,writes);
    await tester.pump(const Duration(seconds:5));
    await tester.pumpAndSettle();
    expect(find.textContaining('连接关闭未确认 · 本次未保存'),findsOneWidget);
    expect(newTab.view.value.state,'retired-unconfirmed');
    expect(newTab.inputEligible.value,isFalse);
    expect(disk.writes,writes);
    expect(closes,1);
    close.complete();
    await tester.pumpAndSettle();
    expect(newTab.view.value.state,'retired');
    await tapVisible(tester,'transfer-review');
    await tapVisible(tester,'transfer-apply');
    await tester.pumpAndSettle();
    expect(closes,1);
    expect(disk.writes,writes+1);
    expect(tabs.tabs,[...originalTabs,newTab]);
    expect(tabs.tabs.map((tab) => tab.view.value.label),[
      '已停用 · 连接已停止','已停用 · 连接已停止','陈旧','陈旧','已停用 · 连接已停止',
    ]);
    expect(newTab.inputEligible.value,isFalse);
    final replacement = catalog.profiles.singleWhere((p) => p.label == first.label && !p.retired);
    expect(replacement.id,isNot(first.id));
    expect(replacement.hasIdentity,isFalse);
    await tester.pageBack(); await tester.pumpAndSettle();
    await tester.tap(find.widgetWithIcon(NavigationDestination,Icons.terminal)); await tester.pumpAndSettle();
    final emptyHistory = find.byKey(ValueKey('retired-host-view-${newTab.id}'));
    expect(emptyHistory,findsOneWidget);
    expect(find.descendant(of:emptyHistory,matching:find.textContaining('尚无终端画面')),findsOneWidget);
    expect(find.descendant(of:emptyHistory,matching:find.text('可手动关闭此标签。')),findsOneWidget);
    expect(find.textContaining('仅可查看最后画面'),findsNothing);
    await tester.pumpWidget(const SizedBox()); tabs.dispose(); catalog.dispose();
  });

  testWidgets('normal host board opens imported metadata in formal explicit pairing without inheriting identity', (tester) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(800, 860);
    addTearDown(tester.view.reset);
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final imported = HostProfile.imported(portable(),1000); await catalog.add(imported);
    final keys = TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:HostCatalogPage(tokens:tokens,catalog:catalog,keys:keys,
      offlineBuilder:(_) => const SizedBox()))); await tester.pumpAndSettle();
    await tapVisible(tester,'home-tab-3'); await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('hosts-transfer')),findsOneWidget);
    await tapVisible(tester,'home-tab-0'); await tester.pumpAndSettle();
    expect(find.textContaining('导入未配对'),findsOneWidget); expect(keys.creates,0); expect(keys.signCalls,0);
    await tapVisible(tester,'host-open-${imported.id}'); await tester.pumpAndSettle();
    expect(tester.widget<TextField>(find.byKey(const ValueKey('pair-host'))).controller!.text,'fixture.invalid');
    expect(find.byKey(const ValueKey('pair-request')),findsNothing);
    await tapVisible(tester,'pair-target-review'); await tapVisible(tester,'pair-create'); await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('pair-request')),findsOneWidget); expect(keys.creates,1); expect(keys.signCalls,0);
    expect(catalog.profiles.length,1); expect(catalog.profiles.single.hasIdentity,isTrue);
    expect((catalog.profiles.single.pairingRecord['request'] as Map)['issued_at'],catalog.clock());
    expect(catalog.profiles.single.id,isNot(imported.id)); expect(catalog.pendingCreation,isNull);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('imported profile board disable, re-enable and delete never restore or delete an absent device identity', (tester) async {
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final imported = HostProfile.imported(portable(),1000); await catalog.add(imported);
    final keys = TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:HostCatalogPage(tokens:tokens,catalog:catalog,keys:keys,
      offlineBuilder:(_) => const SizedBox()))); await tester.pumpAndSettle();
    expect(catalog.profiles.single.hasIdentity,isFalse); expect(tester.takeException(),isNull);
    await tapVisible(tester,'host-management-${imported.id}'); await tester.pumpAndSettle();
    await tapVisible(tester,'host-disable-${imported.id}'); await tester.pumpAndSettle();
    expect(catalog.profiles.single.enabled,isFalse); expect(catalog.profiles.single.hasIdentity,isFalse);
    expect(tester.widget<FilledButton>(find.byKey(ValueKey('host-open-${imported.id}'))).onPressed,isNull);
    await tapVisible(tester,'host-disable-${imported.id}'); await tester.pumpAndSettle();
    expect(catalog.profiles.single.enabled,isTrue); expect(catalog.profiles.single.hasIdentity,isFalse);
    await tapVisible(tester,'host-delete-${imported.id}'); await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton,'仅删除本机')); await tester.pumpAndSettle();
    expect(catalog.profiles,isEmpty); expect(keys.deleted,isFalse); expect(keys.creates,0); expect(keys.signCalls,0);
    expect(tester.takeException(),isNull);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('file cancellation and malformed envelope never create a plan, write catalog, or expose identity export', (tester) async {
    final disk = MemoryCatalogStorage(), documents = MemoryConfigDocuments();
    final catalog = HostCatalog(storage:disk,clock:() => 1000); await catalog.load();
    await catalog.add(HostProfile.imported(portable(),1000)); final writes = disk.writes;
    await tester.pumpWidget(MaterialApp(home:ConfigTransferPage(catalog:catalog,documents:documents,closeTabs:(_) {})));
    await tester.pumpAndSettle();
    final password = tester.widget<TextField>(find.byKey(const ValueKey('transfer-password')));
    expect(password.obscureText,isTrue); expect(password.enableIMEPersonalizedLearning,isFalse);
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('transfer-export'))).onPressed,isNull);
    await tapVisible(tester,'transfer-open'); await tester.pumpAndSettle();
    expect(find.textContaining('已取消打开文件'),findsOneWidget);
    documents.opened = Uint8List(51);
    await tapVisible(tester,'transfer-open'); await tester.pumpAndSettle();
    expect(find.textContaining('格式、大小或公开字段'),findsOneWidget);
    expect(find.byKey(const ValueKey('transfer-apply')),findsNothing);
    expect(documents.saves,0); expect(disk.writes,writes);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('pending identity creation disables the entire transfer path', (tester) async {
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    await catalog.beginCreation(fixtureConfig(),'Unresolved creation');
    final documents = MemoryConfigDocuments();
    await tester.pumpWidget(MaterialApp(home:ConfigTransferPage(catalog:catalog,documents:documents,closeTabs:(_) {})));
    await tester.pumpAndSettle();
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('transfer-open'))).onPressed,isNull);
    expect(tester.widget<TextField>(find.byKey(const ValueKey('transfer-password'))).enabled,isFalse);
    expect(documents.opens,0); expect(find.textContaining('身份创建操作'),findsOneWidget);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
}
