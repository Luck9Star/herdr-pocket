import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:terminal_view/terminal_view.dart';
import 'package:herdr_flutter_probe/remote_horizontal_viewport.dart';

void main() {
  testWidgets('column anchor survives rebuild and geometry changes, isolated by target', (tester) async {
    tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(2400,800);
    addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
    final anchors = <String,double>{};
    Future<void> show(String target,double width,double fontSize) async {
      await tester.pumpWidget(MaterialApp(home:Center(child:SizedBox(width:width,height:360,
        child:RemoteHorizontalViewport(identity:target,anchors:anchors,
          style:TerminalStyle(fontFamily:'monospace',fontSize:fontSize),
          child:const ColoredBox(color:Colors.black))))));
      await tester.pump();
    }
    ScrollController controller() => tester.widget<SingleChildScrollView>(
      find.byKey(const ValueKey('remote-horizontal-scroll'))).controller!;
    await show('host/session/pane/terminal-a',200,14);
    expect(controller().position.maxScrollExtent,greaterThan(0));
    controller().jumpTo(controller().position.maxScrollExtent / 2); await tester.pump();
    final column = anchors['host/session/pane/terminal-a']!;
    expect(column,greaterThan(0));
    await show('host/session/pane/terminal-a',250,18);
    expect(anchors['host/session/pane/terminal-a']!,closeTo(column,0.01));
    await show('host/session/pane/terminal-b',200,14);
    expect(controller().offset,0);
    await show('host/session/pane/terminal-a',200,14);
    expect(anchors['host/session/pane/terminal-a']!,closeTo(column,0.01));
    await show('host/session/pane/terminal-a',2000,14);
    expect(controller().offset,0);
    expect(anchors['host/session/pane/terminal-a'],0);
  });
  testWidgets('missing identities are never shared and saved anchors are bounded', (tester) async {
    tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(1000,800);
    addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
    final anchors = <String,double>{};
    Future<void> show(String? target) async {
      await tester.pumpWidget(MaterialApp(home:Center(child:SizedBox(width:200,height:360,
        child:RemoteHorizontalViewport(identity:target,anchors:anchors,
          style:const TerminalStyle(fontFamily:'monospace',fontSize:14),child:const ColoredBox(color:Colors.black))))));
      await tester.pump();
    }
    ScrollController controller() => tester.widget<SingleChildScrollView>(find.byKey(const ValueKey('remote-horizontal-scroll'))).controller!;
    await show(null); controller().jumpTo(30); await tester.pump();
    expect(anchors,isEmpty);
    await show(''); expect(controller().offset,0); controller().jumpTo(30); await tester.pump();
    expect(anchors,isEmpty);
    for (var i = 0; i < 20; i++) { await show('target-$i'); controller().jumpTo(30); await tester.pump(); }
    expect(anchors.length,16); expect(anchors.containsKey('target-0'),isFalse);
    await show('target-0'); expect(controller().offset,0);
  });
}
