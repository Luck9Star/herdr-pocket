import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/remote_input.dart';
import 'package:herdr_flutter_probe/remote_input_platform.dart';
import 'remote_input_test.dart' show target;
import 'remote_input_journal_test.dart' show MemoryTargetInputJournal;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const journal = PlatformRemoteInputJournal();
  final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  tearDown(() { messenger.setMockMethodCallHandler(PlatformRemoteInputJournal.channel,null); });
  test('bridge uses exact raw/lease arguments and unrelated target records coexist', () async {
    final backend = MemoryTargetInputJournal(),calls = <MethodCall>[];
    messenger.setMockMethodCallHandler(PlatformRemoteInputJournal.channel,(call) async {
      calls.add(call);
      try {
        if (call.method == 'readAll') return await backend.readAll();
        final args = call.arguments as Map,raw = args['record'] as String;
        switch (call.method) {
          case 'prepare': return await backend.prepare(raw);
          case 'complete': await backend.complete(raw,args['lease'] as String); return null;
          case 'abandon': await backend.abandon(raw,args['lease'] as String); return null;
          case 'resolve': await backend.resolve(raw); return null;
          default: throw PlatformException(code:'input_journal_unavailable');
        }
      } catch (_) { throw PlatformException(code:'input_journal_unavailable'); }
    });
    final first = RemoteInputPending.create('a'*32,target()).raw;
    final other = RemoteInputPending.create('b'*32,target(term:'term_1234')).raw;
    expect(await journal.readAll(),isEmpty);
    final a = await journal.prepare(first),b = await journal.prepare(other);
    expect(await journal.readAll(),[first,other]);
    await expectLater(journal.resolve(first),throwsA(isA<PlatformException>()));
    await expectLater(journal.complete(first,b),throwsA(isA<PlatformException>()));
    await journal.abandon(first,a); expect(await journal.readAll(),[first,other]);
    await journal.resolve(first); expect(await journal.readAll(),[other]);
    await journal.complete(other,b); expect(await journal.readAll(),isEmpty);
    expect(calls.every((call) => !{'read','clear'}.contains(call.method)),isTrue);
    for (final call in calls) {
      if (call.method == 'readAll') { expect(call.arguments,isNull); continue; }
      final args = call.arguments as Map;
      expect(args.keys.toSet(),{'record',if ({'complete','abandon'}.contains(call.method)) 'lease'});
      expect(args['record'],isIn([first,other])); expect(args['record'],isNot(contains('bytes_base64')));
    }
  });
  test('missing native bridge has no single-slot or storage fallback', () async {
    await expectLater(journal.readAll(),throwsA(isA<MissingPluginException>()));
    await expectLater(journal.prepare(RemoteInputPending.create('c'*32,target()).raw),throwsA(isA<MissingPluginException>()));
  });
  test('readAll rejects malformed, duplicate endpoint and non-string records', () async {
    final raw = RemoteInputPending.create('d'*32,target()).raw;
    final duplicate = RemoteInputPending.create('e'*32,target(generation:2)).raw;
    for (final response in <Object?>[null,raw,[raw,7],[raw,'{}'],[raw,duplicate]]) {
      messenger.setMockMethodCallHandler(PlatformRemoteInputJournal.channel,(call) async => response);
      await expectLater(journal.readAll(),throwsFormatException);
    }
  });
  test('private records and malformed leases never reach the native bridge', () async {
    var calls = 0;
    messenger.setMockMethodCallHandler(PlatformRemoteInputJournal.channel,(call) async { calls++; return null; });
    final raw = RemoteInputPending.create('f'*32,target()).raw;
    await expectLater(journal.prepare('{"privateKeyPem":"must-not-store"}'),throwsFormatException);
    for (final lease in ['', 'not-a-lease', 'A'*32, 'a'*31]) {
      await expectLater(journal.complete(raw,lease),throwsFormatException);
      await expectLater(journal.abandon(raw,lease),throwsFormatException);
    }
    expect(calls,0);
  });
  test('native prepare must return an opaque 32 lower-case hex lease; mutations must return null', () async {
    final raw = RemoteInputPending.create('f'*32,target()).raw;
    for (final response in <Object?>[null,true,7,'a'*31,'A'*32]) {
      messenger.setMockMethodCallHandler(PlatformRemoteInputJournal.channel,(call) async => response);
      await expectLater(journal.prepare(raw),throwsFormatException);
    }
    messenger.setMockMethodCallHandler(PlatformRemoteInputJournal.channel,(call) async => true);
    await expectLater(journal.complete(raw,'1'*32),throwsFormatException);
    await expectLater(journal.abandon(raw,'1'*32),throwsFormatException);
    await expectLater(journal.resolve(raw),throwsFormatException);
  });
}
