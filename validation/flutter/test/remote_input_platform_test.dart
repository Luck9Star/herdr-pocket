import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/remote_input.dart';
import 'package:herdr_flutter_probe/remote_input_platform.dart';
import 'remote_input_test.dart' show target;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const journal = PlatformRemoteInputJournal();
  final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  tearDown(() { messenger.setMockMethodCallHandler(PlatformRemoteInputJournal.channel,null); });
  test('native journal stores a public marker and clear preserves its exact original string', () async {
    String? slot;
    final calls = <MethodCall>[];
    messenger.setMockMethodCallHandler(PlatformRemoteInputJournal.channel,(call) async {
      calls.add(call);
      if (call.method == 'read') return slot;
      final raw = (call.arguments as Map)['record'] as String;
      if (call.method == 'prepare') {
        if (slot != null) throw PlatformException(code:'input_journal_not_empty');
        slot = raw;
      } else if (call.method == 'clear') {
        if (slot != raw) throw PlatformException(code:'input_journal_mismatch');
        slot = null;
      }
      return null;
    });
    final first = RemoteInputPending.create('a'*32,target()).raw;
    final other = RemoteInputPending.create('b'*32,target()).raw;
    expect(await journal.read(),isNull);
    await journal.prepare(first); expect(await journal.read(),first);
    await expectLater(journal.prepare(other),throwsA(isA<PlatformException>()));
    await expectLater(journal.clear(other),throwsA(isA<PlatformException>()));
    expect(await journal.read(),first);
    await journal.clear(first); expect(await journal.read(),isNull);
    for (final call in calls.where((c) => c.method != 'read')) {
      expect((call.arguments as Map).keys,['record']);
      expect((call.arguments as Map)['record'],isNot(contains('bytes_base64')));
    }
  });
  test('missing native bridge has no storage fallback', () async {
    await expectLater(journal.read(),throwsA(isA<MissingPluginException>()));
    await expectLater(journal.prepare(RemoteInputPending.create('c'*32,target()).raw),
      throwsA(isA<MissingPluginException>()));
  });
  test('malformed native read and private/extra fields fail closed before writing', () async {
    var calls = 0;
    messenger.setMockMethodCallHandler(PlatformRemoteInputJournal.channel,(call) async {
      calls++; return call.method == 'read' ? '{"text":"must-not-store"}' : null;
    });
    await expectLater(journal.read(),throwsFormatException);
    await expectLater(journal.prepare('{"privateKeyPem":"must-not-store"}'),throwsFormatException);
    expect(calls,1);
  });
}
