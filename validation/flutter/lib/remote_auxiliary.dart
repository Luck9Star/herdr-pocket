/// Explicit, one-shot toolbar combinations. Never transform terminal/IME text.
class AuxiliaryModifiers {
  bool ctrl = false, alt = false;
  bool get held => ctrl || alt;
  void reset() { ctrl = false; alt = false; }
  bool toggle(String name, {required bool allowed}) {
    if (!allowed) { reset(); return false; }
    if (name == 'ctrl') { ctrl = !ctrl; return true; }
    if (name == 'alt') { alt = !alt; return true; }
    return false;
  }
  String? take(String name, {required bool applicationCursorMode, required bool allowed}) {
    final useCtrl = ctrl, useAlt = alt; reset();
    return allowed ? auxiliaryKey(name,applicationCursorMode:applicationCursorMode,ctrl:useCtrl,alt:useAlt) : null;
  }
}

String? auxiliaryKey(String name, {bool applicationCursorMode = false, bool ctrl = false, bool alt = false}) {
  final modifier = 1 + (ctrl ? 4 : 0) + (alt ? 2 : 0);
  final cursor = const {'up':'A','down':'B','right':'C','left':'D','home':'H','end':'F'}[name];
  if (cursor != null) return modifier > 1 ? '\x1b[1;$modifier$cursor' : '\x1b${applicationCursorMode ? 'O' : '['}$cursor';
  final page = const {'pgup':5,'pgdn':6}[name];
  if (page != null) return '\x1b[$page${modifier > 1 ? ';$modifier' : ''}~';
  final shortcut = const {'ctrl-c':'\x03','ctrl-d':'\x04','ctrl-z':'\x1a','ctrl-a':'\x01',
    'ctrl-e':'\x05','ctrl-l':'\x0c','ctrl-r':'\x12','ctrl-u':'\x15','ctrl-w':'\x17'}[name];
  if (shortcut != null) return shortcut;
  var value = const {'esc':'\x1b','tab':'\t','enter':'\r','space':' '}[name] ??
    (RegExp(r'^[a-z]$').hasMatch(name) ? name : null);
  if (value == null) return null;
  if (ctrl) {
    if (RegExp(r'^[a-z]$').hasMatch(value)) { value = String.fromCharCode(value.toUpperCase().codeUnitAt(0)-64); }
    else if (name == 'space') { value = '\x00'; }
    else { return null; }
  }
  return '${alt ? '\x1b' : ''}$value';
}
