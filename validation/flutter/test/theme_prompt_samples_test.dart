import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/theme_prompt_samples.dart';

Map<String,Object> fixture() => {'schemaVersion':1,'id':'theme-prompt-samples-v1','columns':40,'rows':3,'samples':[
  {'id':'powerlevel10k','label':'Powerlevel10k','ansi':'\u001b[31mfoo\u001b[0m','cursorColumn':3,'cursorRow':0},
  {'id':'oh-my-posh','label':'Oh My Posh','ansi':'first\r\nsecond','cursorColumn':6,'cursorRow':1},
]};
void main() {
  test('accepts bounded SGR, CRLF and both exact sample identities',() {
    final result=ThemePromptSamples.parse(jsonEncode(fixture()));
    expect(result.samples.map((v) => v.id),['powerlevel10k','oh-my-posh']);
    expect(result.samples.last.cursorRow,1);
  });
  test('rejects dangerous terminal controls and invalid bounds',() {
    for (final bad in ['\u001b]52;c;abc\u0007','\u001b[2J','\u001b[1;2H','\u009b31m','bad\nline','bad\rline','a\r\nb\r\nc\r\nd','\r\u001b[m\n','left\u202eright','x\u2028','\u0000','x'*4097]) {
      final json=fixture(); final samples=json['samples'] as List; samples[0]['ansi']=bad;
      expect(() => ThemePromptSamples.parse(jsonEncode(json)),throwsFormatException,reason:bad);
    }
    for (final bad in [-1,40,1.0,true]) {
      final json=fixture(); final samples=json['samples'] as List; samples[0]['cursorColumn']=bad;
      expect(() => ThemePromptSamples.parse(jsonEncode(json)),throwsFormatException);
    }
  });
  test('rejects duplicate JSON keys, IDs, extra fields and invalid surrogate',() {
    final raw=jsonEncode(fixture());
    for (final bad in [raw.replaceFirst('"schemaVersion":1','"schemaVersion":1,"schemaVersion":1'),
      raw.replaceFirst('"oh-my-posh"','"powerlevel10k"'), raw.replaceFirst('"columns":40','"other":1,"columns":40'),
      raw.replaceFirst('foo',r'\ud800')]) {
      expect(() => ThemePromptSamples.parse(bad),throwsFormatException);
    }
  });
}
