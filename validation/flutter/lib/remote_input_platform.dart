import 'package:flutter/services.dart';
import 'remote_input.dart';

/// Platform bridges store only this public marker in an app-private no-backup
/// directory. Unsupported/missing bridges fail closed, with no file fallback.
class PlatformRemoteInputJournal implements RemoteInputJournal {
  const PlatformRemoteInputJournal();
  static const channel = MethodChannel('herdr.pocket/input_journal');
  @override
  Future<String?> read() async {
    final value = await channel.invokeMethod<Object?>('read');
    if (value != null && value is! String) throw const FormatException('input_journal_invalid');
    if (value != null) RemoteInputPending.parse(value as String);
    return value as String?;
  }
  @override
  Future<void> prepare(String record) async {
    RemoteInputPending.parse(record);
    await channel.invokeMethod<void>('prepare',{'record':record});
  }
  @override
  Future<void> clear(String record) async {
    RemoteInputPending.parse(record);
    await channel.invokeMethod<void>('clear',{'record':record});
  }
}
