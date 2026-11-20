import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart' show kDebugMode;
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/main.dart' as app;
import 'package:integration_test/integration_test.dart';

const _enabled = String.fromEnvironment('HERDR_ANDROID_DOCUMENTS');
const _runId = String.fromEnvironment('HERDR_ANDROID_DOCUMENTS_RUN_ID');
const _package = 'dev.herdr.herdr_flutter_probe';
const _password = 'fixture-document-passphrase';
const _wrongPassword = 'wrong-fixture-document-passphrase';
const _poll = Duration(milliseconds: 100);
const _uiTimeout = Duration(seconds: 45);
const _hostTimeout = Duration(seconds: 240);

const _cancelled = '已取消打开文件。';
const _exported = '加密文件已交给系统保存 · 接收设备仍需审查并独立配对。';
const _opened = '已打开加密文件 · 请输入原口令，解密后逐条审查。';
const _rejected = '口令不匹配或文件被改动 · 未导入任何资料。';
const _preview = '已解密公开资料 · 尚未写入。逐条选择添加、保留或替换；任何目标仍须重新核验并在此设备配对。';
const _applied = '本机公开资料已原子更新 · 新条目没有设备身份，需正式配对。被替换身份已停用保留，请在原主机核验撤销或明确删除。';

Finder _control(String key) => find.byKey(ValueKey(key));

void _check(bool good, String code) {
  if (!good) fail('documents_$code');
}

class _Exchange {
  _Exchange() {
    try {
      _check(!directory.existsSync(), 'exchange_already_exists');
      directory.createSync();
    } on FileSystemException {
      fail('documents_exchange_unavailable');
    }
  }

  final directory = Directory(
    '/data/user/0/$_package/cache/herdr-documents-$_runId',
  );
  String? _lastAck;

  Future<void> checkpoint(String stage) async {
    final pending = File('${directory.path}/checkpoint.json.pending');
    final ack = File('${directory.path}/ack.json');
    try {
      pending.writeAsStringSync(jsonEncode({'stage': stage}), flush: true);
      pending.renameSync('${directory.path}/checkpoint.json');

      final elapsed = Stopwatch()..start();
      while (elapsed.elapsed < _hostTimeout) {
        if (ack.existsSync()) {
          _check(ack.lengthSync() <= 128, 'invalid_ack_$stage');
          final value = jsonDecode(ack.readAsStringSync());
          _check(value is Map && value.length == 1, 'invalid_ack_$stage');
          final acknowledged = (value as Map)['stage'];
          if (acknowledged == stage) {
            _lastAck = stage;
            return;
          }
          _check(
            acknowledged is String && acknowledged == _lastAck,
            'unexpected_ack_$stage',
          );
        }
        // A foreground DocumentsUI activity can pause the Flutter frame clock.
        // Wall-clock polling also lets native replies and the crypto isolate run.
        await Future<void>.delayed(_poll);
      }
    } on FileSystemException {
      fail('documents_exchange_io_$stage');
    } on FormatException {
      fail('documents_invalid_ack_$stage');
    }
    fail('documents_ack_timeout_$stage');
  }
}

class _Ui {
  _Ui(this.tester);

  final WidgetTester tester;

  Future<void> waitFor(String label, bool Function() ready) async {
    final elapsed = Stopwatch()..start();
    while (!ready()) {
      final remaining = _uiTimeout - elapsed.elapsed;
      if (remaining <= Duration.zero) fail('documents_ui_timeout_$label');
      await tester
          .pump(_poll)
          .timeout(
            remaining,
            onTimeout: () {
              fail('documents_frame_timeout_$label');
            },
          );
    }
    _check(tester.takeException() == null, 'ui_exception_$label');
  }

  bool _single(Finder finder) => finder.evaluate().length == 1;
  bool _visible(Finder finder) =>
      _single(finder) && _single(finder.hitTestable());

  Future<Finder> show(
    Finder finder,
    String label, {
    bool Function()? enabled,
  }) async {
    await waitFor(label, () => _single(finder));
    if (!_visible(finder)) await tester.ensureVisible(finder);
    await waitFor(label, () => _visible(finder) && (enabled?.call() ?? true));
    return finder;
  }

  Future<void> press(String key, {VoidCallback? beforeTap}) async {
    final finder = _control(key);
    await show(
      finder,
      key,
      enabled: () => tester.widget<FilledButton>(finder).onPressed != null,
    );
    beforeTap?.call();
    await tester.tap(finder);
  }

  Future<void> openSettings() async {
    final settings = find.byWidgetPredicate(
      (widget) =>
          widget.key == const ValueKey('home-tab-3') ||
          (widget is NavigationDestination && widget.label == '设置'),
    );
    await tester.tap(await show(settings, 'settings'));
  }

  Future<void> openTransfer() async {
    final entry = _control('hosts-transfer');
    await show(
      entry,
      'transfer_entry',
      enabled: () => tester.widget<ListTile>(entry).onTap != null,
    );
    await tester.tap(entry);
    await show(find.text('加密迁移公开配置'), 'transfer_title');
  }

  Future<void> returnToSettings() async {
    final back = find.descendant(
      of: find.byType(AppBar),
      matching: find.byType(BackButton),
    );
    await tester.tap(await show(back, 'transfer_back'));
    await waitFor(
      'settings_return',
      () =>
          back.evaluate().isEmpty &&
          _visible(_control('hosts-terminal-preferences')),
    );
  }

  Future<void> checkFont(int size) async {
    final entry = _control('hosts-terminal-preferences');
    final subtitle = find.descendant(
      of: entry,
      matching: find.text('$size px · 仅本机显示'),
    );
    await waitFor(
      'settings_font_$size',
      () =>
          _visible(entry) &&
          _visible(subtitle) &&
          tester.widget<ListTile>(entry).onTap != null,
    );
  }

  Future<void> setFont(int size) async {
    final entry = _control('hosts-terminal-preferences');
    await show(
      entry,
      'settings_font',
      enabled: () => tester.widget<ListTile>(entry).onTap != null,
    );
    await tester.tap(entry);

    final finder = await show(_control('terminal-font-slider'), 'font_slider');
    final slider = tester.widget<Slider>(finder);
    final context = tester.element(finder);
    final theme = SliderTheme.of(context);
    // Flutter Material's standard track is inset by the overlay radius. Read
    // the actual control bounds/direction, then verify the displayed value.
    final track = (theme.trackShape ?? const RoundedRectSliderTrackShape())
        .getPreferredRect(
          parentBox: tester.renderObject<RenderBox>(finder),
          sliderTheme: theme.copyWith(
            trackHeight: theme.trackHeight ?? 4,
            overlayShape: theme.overlayShape ?? const RoundSliderOverlayShape(),
            thumbShape: theme.thumbShape ?? const RoundSliderThumbShape(),
          ),
          isEnabled: true,
        );
    final reading = (size - slider.min) / (slider.max - slider.min);
    final fraction = Directionality.of(context) == TextDirection.ltr
        ? reading
        : 1 - reading;
    final box = tester.renderObject<RenderBox>(finder);
    await tester.tapAt(
      box.localToGlobal(
        Offset(track.left + track.width * fraction, track.center.dy),
      ),
    );
    await show(
      find.descendant(
        of: _control('terminal-font-preview'),
        matching: find.text('$size px'),
        matchRoot: true,
      ),
      'font_slider_value_$size',
    );
    await press('terminal-font-save');
    await checkFont(size);
  }

  Future<void> status(String expected, String label) async {
    final receipt = find.descendant(
      of: _control('transfer-status'),
      matching: find.text(expected),
      matchRoot: true,
    );
    await show(receipt, label);
    final open = _control('transfer-open');
    // The same status text can be painted before the operation releases its
    // controls. Verify its completion before a later operation.
    await waitFor(
      '${label}_idle',
      () =>
          _single(open) && tester.widget<FilledButton>(open).onPressed != null,
    );
  }

  Future<void> enterPassword(String key, String value) async {
    final field = _control(key);
    await show(
      field,
      key,
      enabled: () => tester.widget<TextField>(field).enabled == true,
    );
    _check(tester.widget<TextField>(field).obscureText, 'plain_password_field');
    await tester.tap(field);
    // Fixture text enters through the Flutter test input channel. Only the
    // host's Android window and IME samples prove system keyboard visibility.
    await tester.enterText(field, value);
    checkPassword(key, value);
  }

  void checkPassword(String key, String value) {
    final field = _control(key);
    _check(_single(field), 'password_field_unconfirmed');
    final widget = tester.widget<TextField>(field);
    _check(
      widget.enabled == true &&
          widget.obscureText &&
          widget.controller?.text == value,
      'password_entry_unconfirmed',
    );
  }

  bool get _keyboardHiddenInForeground =>
      tester.binding.lifecycleState == AppLifecycleState.resumed &&
      tester.view.viewInsets.bottom == 0;

  Future<void> keyboardHidden() async {
    await waitFor(
      'keyboard_dismissed_in_foreground',
      () => _keyboardHiddenInForeground,
    );
  }

  Future<void> decrypt(String password) async {
    await keyboardHidden();
    await press(
      'transfer-decrypt',
      beforeTap: () {
        _check(_keyboardHiddenInForeground, 'decrypt_viewport_changed');
        checkPassword('transfer-password', password);
      },
    );
  }

  Future<void> checkToggle(String key, bool value) async {
    final finder = await show(_control(key), key);
    _check(
      tester.widget<CheckboxListTile>(finder).value == value,
      'toggle_value_$key',
    );
  }

  Future<void> turnOn(String key) async {
    final finder = _control(key);
    await show(
      finder,
      key,
      enabled: () => tester.widget<CheckboxListTile>(finder).onChanged != null,
    );
    _check(
      tester.widget<CheckboxListTile>(finder).value == false,
      'toggle_initial_$key',
    );
    await tester.tap(finder);
    await waitFor(
      'toggle_checked_$key',
      () =>
          _single(finder) &&
          tester.widget<CheckboxListTile>(finder).value == true,
    );
  }

  void checkNoPreview() {
    _check(
      _control('transfer-import-preferences').evaluate().isEmpty &&
          _control('transfer-apply').evaluate().isEmpty,
      'unexpected_preview',
    );
  }
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('Android native encrypted configuration document round trip', (
    tester,
  ) async {
    _check(
      Platform.isAndroid &&
          kDebugMode &&
          _enabled == '1' &&
          RegExp(r'^[0-9]{1,20}$').hasMatch(_runId),
      'isolated_android_debug_required',
    );

    _check(!tester.testTextInput.isRegistered, 'test_ime_registered');
    final ui = _Ui(tester);
    await app.main();
    await ui.show(_control('home-empty-card'), 'empty_home');
    final exchange = _Exchange();
    await exchange.checkpoint('app_ready');

    await ui.openSettings();
    await ui.setFont(19);
    await exchange.checkpoint('initial19');

    await ui.openTransfer();
    await ui.press('transfer-open');
    await exchange.checkpoint('cancel_picker');
    await ui.status(_cancelled, 'cancelled');
    ui.checkNoPreview();
    await exchange.checkpoint('cancel_done');

    await ui.turnOn('transfer-export-preferences');
    await ui.turnOn('transfer-review');
    await ui.enterPassword('transfer-password', _password);
    await ui.enterPassword('transfer-password-repeat', _password);
    await exchange.checkpoint('hide_export');
    await ui.keyboardHidden();
    await ui.press('transfer-export');
    await exchange.checkpoint('save_picker');
    await ui.status(_exported, 'exported');
    await exchange.checkpoint('export_done');

    await ui.returnToSettings();
    await ui.setFont(13);
    await exchange.checkpoint('control13');
    await ui.openTransfer();

    for (final (picker, done, password) in [
      ('wrong_picker', 'wrong_done', _wrongPassword),
      ('tampered_picker', 'tampered_done', _password),
      ('correct_picker', 'preview', _password),
    ]) {
      await ui.press('transfer-open');
      await exchange.checkpoint(picker);
      await ui.status(_opened, '${picker}_opened');
      ui.checkNoPreview();
      await ui.enterPassword('transfer-password', password);
      await exchange.checkpoint('hide_${picker.split('_').first}');
      await ui.decrypt(password);
      if (done == 'preview') {
        await ui.status(_preview, 'preview');
        await ui.show(
          find.text('明确应用档案终端字号（19 px，当前 13 px）'),
          'preview_font_values',
        );
        await ui.checkToggle('transfer-import-preferences', false);
        await ui.checkToggle('transfer-review', false);
        final apply = await ui.show(
          _control('transfer-apply'),
          'preview_apply',
        );
        _check(
          tester.widget<FilledButton>(apply).onPressed == null,
          'preview_apply_enabled',
        );
      } else {
        await ui.status(_rejected, done);
        ui.checkNoPreview();
      }
      await exchange.checkpoint(done);
    }

    await ui.turnOn('transfer-import-preferences');
    await ui.turnOn('transfer-review');
    await exchange.checkpoint('apply_dispatch');
    await ui.press('transfer-apply');
    await ui.status(_applied, 'applied');
    ui.checkNoPreview();
    await ui.returnToSettings();
    await ui.checkFont(19);
    await exchange.checkpoint('apply_done');
  }, timeout: const Timeout(Duration(minutes: 12)));
}
