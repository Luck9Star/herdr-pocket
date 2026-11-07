import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:terminal_view/terminal_view.dart';

/// Reads the pinned production text-input client. Bind after layout, then read
/// the actual current value again for every action; no keyboard-visibility or
/// last-build approximation is used to decide whether auxiliary input is safe.
class RemoteTerminalIme {
  TerminalViewState? _editor;
  Terminal? _source;

  bool bind(BuildContext? context,Terminal? source) {
    TerminalViewState? found;
    void visit(Element element) {
      if (element is StatefulElement && element.state is TerminalViewState) {
        final state = element.state as TerminalViewState;
        if (identical(state.widget.terminal,source)) { found = state; return; }
      }
      element.visitChildElements(visit);
    }
    context?.visitChildElements(visit);
    final changed = !identical(_editor,found) || !identical(_source,source);
    _editor = found; _source = source;
    return changed;
  }

  TextEditingValue? read(Terminal? source) {
    final editor = _editor;
    if (source == null || !identical(source,_source) || editor == null || !editor.mounted ||
        !identical(editor.widget.terminal,source)) return null;
    return editor.currentTextEditingValue;
  }

  bool blocksAuxiliary(Terminal? source) {
    final value = read(source);
    return value == null || !value.composing.isCollapsed;
  }

  void clear() { _editor = null; _source = null; }
}
