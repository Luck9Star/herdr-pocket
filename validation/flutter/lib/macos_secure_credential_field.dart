import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// macOS credentials stay out of Flutter EditableText and its native field editor.
/// The controller is memory-only; AppKit owns the actual secure text control.
class MacosSecureCredentialField extends StatefulWidget {
  const MacosSecureCredentialField({
    super.key,
    required this.controller,
    required this.label,
    required this.identifier,
    required this.enabled,
    this.decoration,
    this.onNativeFocus,
  });
  final TextEditingController controller;
  final String label, identifier;
  final bool enabled;
  final InputDecoration? decoration;
  /// Returns whether the previous Flutter editor was released.
  final bool Function()? onNativeFocus;
  @override
  State<MacosSecureCredentialField> createState() =>
      _MacosSecureCredentialFieldState();
}

class _MacosSecureCredentialFieldState
    extends State<MacosSecureCredentialField> {
  MethodChannel? _channel;
  int _revision = 0;
  bool _fromNative = false, _unavailable = false;

  @override
  void initState() {
    super.initState();
    widget.controller.addListener(_changed);
  }

  void _changed() {
    if (!mounted) return;
    if (!_fromNative) unawaited(_sync(updateText: true));
    setState(() {});
  }

  Future<void> _sync({bool updateText = false}) async {
    final channel = _channel;
    if (channel == null || !mounted || _unavailable) return;
    final revision = ++_revision;
    try {
      await channel.invokeMethod<void>('sync', {
        'revision': revision,
        if (updateText) 'text': widget.controller.text,
        'enabled': widget.enabled,
        'dark': Theme.of(context).brightness == Brightness.dark,
      });
    } catch (_) {
      if (!mounted || !identical(channel, _channel) || revision != _revision)
        return;
      // No editable Flutter fallback and no secret-bearing exception output.
      _fromNative = true;
      widget.controller.clear();
      _fromNative = false;
      setState(() {
        _unavailable = true;
      });
    }
  }

  void _created(int id) {
    if (!mounted) return;
    final channel = MethodChannel('herdr.pocket/secure-field/$id');
    _channel = channel;
    channel.setMethodCallHandler((call) async {
      if (!mounted ||
          !identical(channel, _channel) ||
          !widget.enabled ||
          _unavailable)
        return;
      final args = call.arguments;
      if (args is! Map || args['revision'] != _revision) return;
      if (call.method == 'focused' && args.length == 1) {
        if (widget.onNativeFocus?.call() == true) {
          // Let EditableText close its previous platform input connection
          // before acknowledging the handoff to the native secure editor.
          await WidgetsBinding.instance.endOfFrame;
        }
        return;
      }
      if (call.method != 'changed' || args['text'] is! String) return;
      final text = args['text'] as String;
      _fromNative = true;
      widget.controller.value = TextEditingValue(
        text: text,
        selection: TextSelection.collapsed(offset: text.length),
      );
      _fromNative = false;
    });
    unawaited(_sync(updateText: true));
  }

  void _retire() {
    final channel = _channel;
    _channel = null;
    ++_revision;
    if (channel == null) return;
    channel.setMethodCallHandler(null);
    unawaited(channel.invokeMethod<void>('retire').catchError((Object _) {}));
  }

  @override
  void didUpdateWidget(covariant MacosSecureCredentialField oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.controller != widget.controller) {
      oldWidget.controller.removeListener(_changed);
      widget.controller.addListener(_changed);
    }
    if (oldWidget.identifier != widget.identifier) {
      _retire();
      _unavailable = false;
    } else if (oldWidget.controller != widget.controller ||
        oldWidget.enabled != widget.enabled) {
      unawaited(_sync(updateText: oldWidget.controller != widget.controller));
    }
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    unawaited(_sync());
  }

  @override
  void dispose() {
    widget.controller.removeListener(_changed);
    _retire();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => InputDecorator(
    isEmpty: widget.controller.text.isEmpty,
    decoration: (widget.decoration ?? InputDecoration(
      floatingLabelBehavior: FloatingLabelBehavior.always,
      label: ExcludeSemantics(child: Text(widget.label)),
    )).copyWith(
      enabled: widget.enabled && !_unavailable,
      errorText: _unavailable ? '原生安全输入不可用，请重新打开此页。' : null,
    ),
    child: SizedBox(
      height: 40,
      child: AppKitView(
        key: ValueKey(widget.identifier),
        viewType: 'herdr.pocket/secure-field',
        creationParams: {
          'label': widget.label,
          'identifier': widget.identifier,
        },
        creationParamsCodec: const StandardMessageCodec(),
        onPlatformViewCreated: _created,
      ),
    ),
  );
}
