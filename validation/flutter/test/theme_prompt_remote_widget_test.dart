import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:terminal_view/terminal_view.dart';
import 'package:herdr_flutter_probe/theme_prompt_samples.dart';
import 'remote_input_widget_test.dart' as input;
import 'terminal_font_diagnostics_test.dart' show press;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late ThemePromptSamples samples;
  setUpAll(() async {
    samples=ThemePromptSamples.parse(await rootBundle.loadString('assets/shared/theme-prompt-samples-v1.json'));
    final font=FontLoader('ProbeNerd')..addFont(rootBundle.load('assets/shared/fonts/JetBrainsMonoNerdFontMono-Regular.ttf'));
    await font.load();
  });
  for (final width in [320.0,390.0]) {
    testWidgets('normal observation opens theme samples locally and preserves draft at $width px',(tester) async {
      final adapter=input.InputFixtureAdapter(); await input.start(tester,adapter,width:width);
      await input.mode(tester,'draft');
      final draft=find.byKey(const ValueKey('remote-input-draft'));
      await tester.ensureVisible(draft); await tester.enterText(draft,'keep this draft'); await tester.pump();
      final controller=tester.widget<TextField>(draft).controller!,calls=adapter.calls,generation=adapter.generation;
      await press(tester,'remote-font-diagnostics-open');
      await tester.runAsync(() => Future<void>.delayed(Duration.zero)); await tester.pump();
      for (final sample in samples.samples) {
        final chip=find.byKey(ValueKey('terminal-font-sample-${sample.id}'));
        await tester.ensureVisible(chip); await tester.tap(chip); await tester.pumpAndSettle();
        final view=tester.widget<TerminalView>(find.byKey(ValueKey('terminal-theme-view-${sample.id}')));
        expect(view.readOnly,isTrue); expect(view.autoResize,isFalse);
        expect(view.terminal.viewWidth,40); expect(view.terminal.viewHeight,3);
        expect(view.terminal.buffer.cursorX,sample.cursorColumn); expect(view.terminal.buffer.cursorY,sample.cursorRow);
        expect(find.textContaining('本地只读示例'),findsOneWidget);
        expect(adapter.received,isEmpty); expect(adapter.calls,calls); expect(adapter.generation,generation);
        expect(controller.text,'keep this draft');
      }
      await press(tester,'terminal-font-diagnostics-close');
      expect(controller.text,'keep this draft'); expect(adapter.received,isEmpty);
      expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-observe'))).selected,isTrue);
    });
  }
}
