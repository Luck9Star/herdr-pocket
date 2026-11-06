import 'package:flutter/services.dart';
import 'remote_input.dart';

/// The native table keeps public v1/v2 markers in app-private no-backup storage.
/// There is no single-slot or filesystem fallback on unsupported platforms.
class PlatformRemoteInputJournal implements RemoteInputJournal {
  const PlatformRemoteInputJournal();
  static const channel = MethodChannel('herdr.pocket/input_journal');
  @override
  Future<List<String>> readAll() async {
    final value = await channel.invokeMethod<Object?>('readAll');
    if (value is! List || value.any((record) => record is! String)) throw const FormatException('input_journal_invalid');
    final records = value.cast<String>();
    parseRemoteInputJournalRecords(records);
    return List<String>.unmodifiable(records);
  }
  @override
  Future<String> prepare(String record) async {
    RemoteInputPending.parse(record);
    final lease = await channel.invokeMethod<Object?>('prepare',{'record':record});
    if (!isRemoteInputJournalLease(lease)) throw const FormatException('input_journal_invalid');
    return lease as String;
  }
  Future<void> _leased(String method,String record,String lease) async {
    RemoteInputPending.parse(record);
    if (!isRemoteInputJournalLease(lease)) throw const FormatException('input_journal_invalid');
    final result = await channel.invokeMethod<Object?>(method,{'record':record,'lease':lease});
    if (result != null) throw const FormatException('input_journal_invalid');
  }
  @override Future<void> complete(String record,String lease) => _leased('complete',record,lease);
  @override Future<void> abandon(String record,String lease) => _leased('abandon',record,lease);
  @override Future<void> resolve(String record) async {
    RemoteInputPending.parse(record);
    final result = await channel.invokeMethod<Object?>('resolve',{'record':record});
    if (result != null) throw const FormatException('input_journal_invalid');
  }
}
