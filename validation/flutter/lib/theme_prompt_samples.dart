import 'dart:convert';

/// A bounded, local-only ANSI sample. Parsing never executes terminal actions.
class ThemePromptSample {
  const ThemePromptSample(this.id,this.label,this.ansi,this.cursorColumn,this.cursorRow);
  final String id,label,ansi;
  final int cursorColumn,cursorRow;
}

class ThemePromptSamples {
  const ThemePromptSamples(this.samples);
  final List<ThemePromptSample> samples;
  static ThemePromptSamples parse(String raw) {
    if (utf8.encode(raw).length > 16384) throw const FormatException('invalid_theme_samples');
    final value = _Json(raw).parse();
    if (value is! Map<String,Object?> || !_keys(value,{'schemaVersion','id','columns','rows','samples'}) ||
        value['schemaVersion'] != 1 || value['schemaVersion'] is! int || value['id'] != 'theme-prompt-samples-v1' ||
        value['columns'] != 40 || value['columns'] is! int || value['rows'] != 3 || value['rows'] is! int || value['samples'] is! List) {
      throw const FormatException('invalid_theme_samples');
    }
    final list=value['samples'] as List, seen=<String>{}, out=<ThemePromptSample>[];
    if (list.length != 2) throw const FormatException('invalid_theme_samples');
    for (final item in list) {
      if (item is! Map<String,Object?> || !_keys(item,{'id','label','ansi','cursorColumn','cursorRow'})) throw const FormatException('invalid_theme_samples');
      final id=item['id'],label=item['label'],ansi=item['ansi'],col=item['cursorColumn'],row=item['cursorRow'];
      if (id is! String || !{'powerlevel10k','oh-my-posh'}.contains(id) || !seen.add(id) ||
          label is! String || label.trim().isEmpty || utf8.encode(label).length > 160 || !_validText(label) ||
          ansi is! String || ansi.isEmpty || utf8.encode(ansi).length > 4096 || !_validAnsi(ansi) ||
          col is! int || col < 0 || col >= 40 || row is! int || row < 0 || row >= 3) throw const FormatException('invalid_theme_samples');
      out.add(ThemePromptSample(id,label,ansi,col,row));
    }
    return ThemePromptSamples(List.unmodifiable(out));
  }
}
bool _keys(Map<String,Object?> value,Set<String> allowed) => value.length == allowed.length && value.keys.every(allowed.contains);
// Printable Unicode includes private-use Nerd Font glyphs. Format controls,
// isolated surrogates and non-printing characters are excluded from labels and
// terminal text. Match CRLF before stripping SGR so a split pair is rejected.
final _printable = RegExp(r'^[\p{L}\p{M}\p{N}\p{P}\p{S}\p{Zs}\p{Co}]*$', unicode:true);
final _sgr = RegExp(r'\x1b\[[0-9;]*m');
bool _validText(String value) => _printable.firstMatch(value)?.end == value.length;
bool _validAnsi(String value) {
  final lines = value.split('\r\n');
  return lines.length <= 3 && lines.every((line) => _validText(line.replaceAll(_sgr,'')));
}

/// Minimal JSON grammar: objects, arrays, strings and integer literals only.
/// This preserves duplicate-key and numeric spelling checks before decoding.
class _Json {
  _Json(this.text);
  final String text;
  int at=0;
  void ws() { while (at<text.length && ' \t\r\n'.contains(text[at])) { at++; } }
  bool eat(String token) { ws(); if (at<text.length && text[at]==token) { at++; return true; } return false; }
  String string() {
    ws(); final match=RegExp(r'"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"').matchAsPrefix(text,at);
    if (match==null) throw const FormatException('invalid_theme_samples');
    at=match.end; return jsonDecode(match[0]!) as String;
  }
  Object? value([int depth=0]) {
    if (depth > 3) throw const FormatException('invalid_theme_samples');
    ws(); if (at>=text.length) throw const FormatException('invalid_theme_samples');
    if (text[at]=='"') return string();
    if (eat('{')) {
      final result=<String,Object?>{};
      if (eat('}')) return result;
      while (true) {
        final key=string(); if (result.containsKey(key) || !eat(':')) throw const FormatException('invalid_theme_samples');
        result[key]=value(depth+1); if (eat('}')) return result; if (!eat(',')) throw const FormatException('invalid_theme_samples');
      }
    }
    if (eat('[')) {
      final result=<Object?>[]; if (eat(']')) return result;
      while (true) { result.add(value(depth+1)); if (eat(']')) return result; if (!eat(',')) throw const FormatException('invalid_theme_samples'); }
    }
    ws(); final number=RegExp(r'-?(?:0|[1-9][0-9]*)').matchAsPrefix(text,at);
    if (number==null) throw const FormatException('invalid_theme_samples');
    at=number.end; return int.parse(number[0]!);
  }
  Object? parse() { final result=value(); ws(); if (at!=text.length) throw const FormatException('invalid_theme_samples'); return result; }
}
