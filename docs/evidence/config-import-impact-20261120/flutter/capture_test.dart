import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/config_transfer.dart';
import 'package:herdr_flutter_probe/config_transfer_page.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/host_tabs.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart' show RemotePane;

import 'config_transfer_test.dart' show portable;
import 'host_catalog_test.dart' show MemoryCatalogStorage, catalogPairing;
import 'pairing_gui_test.dart' show TestDeviceKeys;
import 'remote_test_data.dart';

const frame = ValueKey('fixture-original-flutter-frame');
const passphrase = 'temporary synthetic fixture phrase';

void main() {
  testWidgets('paint original phone-sized import impact frames', (tester) async {
    final env = Platform.environment;
    final out = Directory(env['CAPTURE_OUT']!);
    final variant = env['CAPTURE_VARIANT']!;
    final Size size = Size(double.parse(env['CAPTURE_WIDTH']!), double.parse(env['CAPTURE_HEIGHT']!));
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = size;
    addTearDown(tester.view.reset);

    final disk = MemoryCatalogStorage();
    final catalog = HostCatalog(storage: disk, clock: () => 1000);
    final tabs = HostTabs();
    await catalog.load();
    Future<HostProfile> createHost(String label, String address) async {
      final initial = HostProfile.create(label, {...fixtureConfig(), 'host':address}, catalogPairing(authorized:true),1000);
      final host = HostProfile.fromJson({
        ...initial.toJson(),
        'pairing': {...initial.pairingRecord,'handle':'fixture-device-${address.split('.').first}'},
      },1000);
      await catalog.add(host);
      return host;
    }
    final first = await createHost('开发主机','development.invalid');
    final second = await createHost('验证主机','validation.invalid');
    final unrelated = await createHost('独立主机','unrelated.invalid');
    await catalog.add(HostProfile.imported(portable(label:first.label,host:'unpaired-development.invalid'),1000));
    final initialWrites = disk.writes;
    final config = PortableConfig.fromJson({
      'version': 1,
      'hosts': [
        portable(label:first.label,host:'new-development.invalid').toJson(),
        portable(label:'验证主机新名称',host:'validation.invalid').toJson(),
      ],
    });
    final (tokens,archive) = (await tester.runAsync(() async {
      final font = FontLoader('EvidenceCjk')..addFont(
        File(env['CAPTURE_FONT']!).readAsBytes().then(ByteData.sublistView),
      );
      final icons = FontLoader('MaterialIcons')..addFont(
        File(env['CAPTURE_ICON_FONT']!).readAsBytes().then(ByteData.sublistView),
      );
      await font.load();
      await icons.load();
      final paint = await DesignTokens.load();
      // Both variants use exactly the same synthetic, deterministic archive.
      final archive = encryptTransferWithMaterial(passphrase,encodePortableConfig(config),
        Uint8List.fromList(List.generate(16,(i)=>i + 1)),
        Uint8List.fromList(List.generate(12,(i)=>i + 17)));
      File('${out.path}/synthetic-archive.hpkt').writeAsBytesSync(archive);
      return (paint,archive);
    }))!;
    final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    var opens = 0;
    messenger.setMockMethodCallHandler(NativeConfigDocuments.channel, (call) async {
      expect(call.method,'open');
      opens++;
      return archive;
    });
    addTearDown(() => messenger.setMockMethodCallHandler(NativeConfigDocuments.channel,null));
    final keys = TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
    final theme = tokens.theme.copyWith(
      textTheme: tokens.theme.textTheme.apply(fontFamily:'EvidenceCjk'),
      primaryTextTheme: tokens.theme.primaryTextTheme.apply(fontFamily:'EvidenceCjk'),
      appBarTheme: tokens.theme.appBarTheme.copyWith(
        titleTextStyle:tokens.theme.appBarTheme.titleTextStyle!.copyWith(fontFamily:'EvidenceCjk'),
      ),
    );
    await tester.pumpWidget(RepaintBoundary(key:frame,child:MaterialApp(theme:theme,debugShowCheckedModeBanner:false,
      home:HostCatalogPage(tokens:tokens,catalog:catalog,tabs:tabs,keys:keys,
        offlineBuilder:(_) => const SizedBox()))));
    await tester.pumpAndSettle();

    expect(tabs.open(first,requestedTarget:const RemotePane('pane-dev-a','terminal-dev-a')),isTrue);
    expect(tabs.open(first,requestedTarget:const RemotePane('pane-dev-b','terminal-dev-b')),isTrue);
    expect(tabs.open(second,requestedTarget:const RemotePane('pane-qa','terminal-qa')),isTrue);
    expect(tabs.open(unrelated,requestedTarget:const RemotePane('pane-other','terminal-other')),isTrue);
    final originals = tabs.tabs;
    await tester.pumpAndSettle();
    final events = <Object>[];
    final captures = <String,Object>{};
    Finder control(String key) => find.byKey(ValueKey(key));
    Finder getControlFromCard(String key) => find.descendant(
      of:control('transfer-impact'),matching:control(key),
    );
    List<double> rect(Rect r) => [r.left,r.top,r.right,r.bottom];
    Map<String,Object?> geometry(Finder finder,Rect viewport) {
      final count = finder.evaluate().length;
      if (count != 1) return {'count':count,'visible':false,'hitTestable':false};
      final bounds = tester.getRect(finder);
      return {
        'count':count,'bounds':rect(bounds),
        'visible':bounds.overlaps(viewport),
        'fullyVisible':viewport.intersect(bounds) == bounds,
        'hitTestable':finder.hitTestable().evaluate().length == 1,
      };
    }

    await tester.tap(find.widgetWithIcon(NavigationDestination,Icons.settings_outlined).hitTestable());
    await tester.pumpAndSettle();
    final routeEntry = control('hosts-transfer').hitTestable();
    expect(routeEntry,findsOneWidget);
    await tester.tap(routeEntry);
    await tester.pumpAndSettle();
    expect(find.byType(ConfigTransferPage),findsOneWidget);
    expect(tabs.tabs,originals);

    final body = find.descendant(of:find.byType(ConfigTransferPage),matching:find.byType(SingleChildScrollView));
    final outer = find.descendant(of:body,matching:find.byType(Scrollable)).first;
    Rect bodyViewport() => tester.getRect(body);
    ScrollPosition scroll() => tester.state<ScrollableState>(outer).position;
    Future<int> dragTo(Finder target,{double anchor = .58}) async {
      var count = 0;
      for (var attempt = 0; attempt < 15; attempt++) {
        expect(target,findsOneWidget);
        final viewport = bodyViewport();
        final aim = viewport.top + viewport.height * anchor;
        final difference = tester.getCenter(target).dy - aim;
        if (difference.abs() <= 18 && target.hitTestable().evaluate().length == 1) return count;
        final last = scroll().pixels;
        if (((difference > 0 && last >= scroll().maxScrollExtent - 1) ||
            (difference < 0 && last <= scroll().minScrollExtent + 1)) &&
            target.hitTestable().evaluate().length == 1) return count;
        final amount = math.min(360.0,math.max(30.0,difference.abs()));
        await tester.dragFrom(Offset(viewport.right-8,viewport.center.dy),Offset(0,-amount*difference.sign));
        await tester.pumpAndSettle();
        expect(scroll().pixels,isNot(last),
          reason:'real scroll gesture did not move the viewport');
        count++;
      }
      fail('could not put the intended control in the phone viewport');
    }

    final open = control('transfer-open');
    await dragTo(open);
    await tester.tap(open.hitTestable());
    await tester.pumpAndSettle();
    expect(opens,1);
    final password = control('transfer-password');
    await dragTo(password);
    await tester.enterText(password,passphrase);
    final passwordController = tester.widget<TextField>(password).controller!;
    final decrypt = control('transfer-decrypt');
    await dragTo(decrypt);
    await tester.runAsync(() async {
      await tester.tap(decrypt.hitTestable());
      final deadline = DateTime.now().add(const Duration(seconds:40));
      while (passwordController.text.isNotEmpty && DateTime.now().isBefore(deadline)) {
        await Future<void>.delayed(const Duration(milliseconds:20));
      }
      expect(passwordController.text,isEmpty);
    });
    await tester.pumpAndSettle();
    final controls = [control('transfer-choice-0'),control('transfer-choice-1')];
    List<String?> choices() => [
      for (final picker in controls) tester.state<FormFieldState<ConfigImportAction>>(picker).value?.name,
    ];
    Future<void> saveFrame(String name) async {
      final render = tester.renderObject<RenderRepaintBoundary>(find.byKey(frame));
      await tester.runAsync(() async {
        final image = await render.toImage(pixelRatio:1);
        expect([image.width,image.height],[size.width.toInt(),size.height.toInt()]);
        final bytes = (await image.toByteData(format:ui.ImageByteFormat.png))!;
        File('${out.path}/$name.png').writeAsBytesSync(bytes.buffer.asUint8List(bytes.offsetInBytes,bytes.lengthInBytes));
        image.dispose();
      });
    }
    Future<void> choose(int index,ConfigImportAction action,String option) async {
      final picker = controls[index];
      final count = await dragTo(picker);
      expect(picker.hitTestable(),findsOneWidget);
      final pickerGeometry = geometry(picker,bodyViewport());
      final arrow = find.descendant(of:picker,matching:find.byIcon(Icons.arrow_drop_down));
      expect(arrow,findsOneWidget);
      final arrowAtTap = geometry(arrow,bodyViewport());
      final clickArrow = arrowAtTap['hitTestable'] == true;
      if (variant == 'after') expect(clickArrow,isTrue);
      await tester.tap(clickArrow ? arrow.hitTestable() : picker.hitTestable());
      await tester.pumpAndSettle();
      final menuItem = find.text(option).hitTestable().last;
      expect(menuItem,findsOneWidget);
      final itemGeometry = geometry(menuItem,Offset.zero & size);
      await tester.tap(menuItem);
      await tester.pumpAndSettle();
      expect(choices()[index],action.name);

      final selected = find.descendant(of:picker,matching:find.text(option));
      expect(selected,findsOneWidget);
      final paragraph = tester.renderObject<RenderParagraph>(selected);
      final intrinsicWidth = paragraph.getMaxIntrinsicWidth(double.infinity);
      final allowed = tester.getRect(picker).intersect(bodyViewport());
      final icon = tester.getRect(arrow);
      final glyphs = paragraph.getBoxesForSelection(TextSelection(baseOffset:0,extentOffset:option.length))
        .map((glyph) => glyph.toRect().shift(paragraph.localToGlobal(Offset.zero))).toList();
      final allGlyphsVisible = glyphs.isNotEmpty &&
        intrinsicWidth <= paragraph.size.width + .01 &&
        glyphs.every((box) => box.intersect(allowed) == box && box.right < icon.left);
      final selectedArrow = geometry(arrow,bodyViewport());
      final arrowFullyVisible = icon.intersect(allowed) == icon;
      if (variant == 'after') {
        expect(allGlyphsVisible,isTrue);
        expect(arrowFullyVisible,isTrue);
        expect(selectedArrow['hitTestable'],isTrue);
      }
      final event = <String,Object?>{'picker':index == 0 ? 'A' : 'B','option':action.name,
        'scrollGestures':count,'pickerGeometryAtTap':pickerGeometry,
        'tapTarget':clickArrow ? 'arrow' : 'picker','arrowGeometryAtTap':arrowAtTap,
        'optionGeometryAtTap':itemGeometry,'choicesAfterTap':choices(),
        'selectedRendering':{'text':option,'intrinsicTextWidth':intrinsicWidth,
          'paragraphWidth':paragraph.size.width,'textGeometry':geometry(selected,bodyViewport()),
          'glyphBounds':glyphs.map(rect).toList(),'allGlyphsVisible':allGlyphsVisible,
          'arrowGeometry':selectedArrow,'arrowFitsInsidePicker':arrowFullyVisible}};
      if (index == 0 && action == ConfigImportAction.replace) {
        await saveFrame('a-replace-control');
        event['controlFrame'] = {'png':'a-replace-control.png'};
      }
      events.add(event);
    }
    Future<void> capture(String name,List<String?> state,List<int> expectedTabs) async {
      final review = control('transfer-review');
      final beforeDrag = scroll().pixels;
      final moves = await dragTo(review,anchor:.84);
      final viewport = bodyViewport();
      expect(choices(),state);
      expect(review.hitTestable(),findsOneWidget);
      final card = control('transfer-impact');
      final indices = variant == 'after' ? expectedTabs : const <int>[];
      expect(card,indices.isEmpty ? findsNothing : findsOneWidget);
      final visible = <Object>[];
      for (final (i,tab) in originals.indexed) {
        final row = getControlFromCard('transfer-affected-tab-${tab.id}');
        expect(row,indices.contains(i) ? findsOneWidget : findsNothing);
        if (!indices.contains(i)) continue;
        final text = tester.widget<Text>(find.descendant(of:row,matching:find.byType(Text)));
        final rowGeometry = geometry(row,viewport);
        expect(rowGeometry['fullyVisible'],isTrue);
        visible.add({'label':text.data,'geometry':rowGeometry});
      }
      final eligibility = find.text('以上标签当前均不能从本机输入。');
      expect(eligibility,indices.isEmpty ? findsNothing : findsOneWidget);
      final json = <String,Object?>{
        'png':'$name.png','choices':choices(),'bodyViewport':rect(viewport),
        'scrollGesturesToReview':moves,'offsetBeforeReviewScroll':beforeDrag,'offsetAtCapture':scroll().pixels,
        'review':geometry(review,viewport),'impactCard':geometry(card,viewport),
        'visibleAffectedTabs':visible,'localInputMessage':geometry(eligibility,viewport),
        'apply':geometry(control('transfer-apply'),viewport),
      };
      await saveFrame(name);
      captures[name] = json;
    }

    final replace = variant == 'after' ? '替换全部冲突' : '替换全部所列冲突（原身份停用保留）';
    if (variant == 'after') {
      expect(find.textContaining('替换时停用资料并保留本机身份'),findsNWidgets(2));
      expect(find.textContaining('未配对，替换时移除资料'),findsOneWidget);
    }
    await choose(0,ConfigImportAction.replace,replace);
    await capture('a-replace',['replace',null],[0,1]);
    await choose(0,ConfigImportAction.keep,'保留本机／跳过此条');
    await capture('a-keep',['keep',null],[]);
    await choose(1,ConfigImportAction.replace,replace);
    await capture('b-replace',['keep','replace'],[2]);

    expect(opens,1);
    expect(tabs.tabs,originals);
    expect(disk.writes,initialWrites);
    expect(keys.signCalls,0);
    File('${out.path}/render-facts.json').writeAsStringSync(const JsonEncoder.withIndent('  ').convert({
      'variant':variant,'source':env['CAPTURE_SOURCE'],'viewport':{'width':size.width,'height':size.height,'dpr':1},
      'capture':'Flutter WidgetTester RenderRepaintBoundary.toImage; not native device or simulator',
      'fixture':{'systemFileCompletion':'test channel','encryptionAndDecryption':'real synthetic fixture',
        'systemOpenCalls':opens,'catalogWritesDuringReview':disk.writes-initialWrites,'deviceSignCalls':keys.signCalls},
      'interactions':events,'states':captures,
    }));
    expect(tester.takeException(),isNull,reason:'Flutter must report zero rendering errors (baseline known negative)');
    await tester.pumpWidget(const SizedBox()); tabs.dispose(); catalog.dispose();
  });
}
