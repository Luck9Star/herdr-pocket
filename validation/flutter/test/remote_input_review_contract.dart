// Runs with standalone Dart; no Flutter SDK, package resolution or network.
import 'dart:convert';
import 'dart:math';
import '../lib/remote_input_review.dart';

void require(bool condition,String message) {
  if (!condition) throw StateError(message);
}

void main() {
  var cases = 0;
  void check(String raw) {
    final bytes = utf8.encode(raw).length;
    require(boundedRemoteInputBytes(raw) == min(bytes,4097),'bounded UTF-8 mismatch');
    cases++;
  }
  for (final raw in ['', '中', '🙂', '\ud800', '\udfff', '\ud800X\udfff',
      'A\n\x1b[31m\u202eB',List.filled(4096,'x').join(),List.filled(1024,'🙂').join(),
      List.filled(1366,'中').join()]) { check(raw); }
  final random = Random(42);
  for (var i = 0; i < 500; i++) {
    check(String.fromCharCodes(List.generate(random.nextInt(3000),(_) => random.nextInt(65536))));
  }
  final original = List.filled(4094,'x').join(),review = RemotePasteReview(original,'中');
  require(review.canReplace && !review.canAppend,'4094+3 must permit replacement only');
  require(review.original == original && review.clipboard == '中','sendable originals must stay exact');
  final fits = RemotePasteReview(List.filled(4093,'x').join(),'中');
  require(fits.canAppend && fits.appendedBytes == 4096,'exact boundary must append');
  final oversized = RemotePasteReview('original','${List.filled(1000000,'x').join()}PRIVATE TAIL');
  require(oversized.clipboardBytes == 4097 && oversized.clipboard.isEmpty,'oversized clipboard must be discarded');
  require(!oversized.canAppend && !oversized.canReplace,'oversized clipboard must not be used');
  require(remoteInputByteLabel(oversized.clipboardBytes) == '超过 4096','overflow must not claim exact count');
  require(!RemotePasteReview('original','').canReplace,'empty clipboard cannot replace');
  require(RemotePasteReview(List.filled(1000000,'x').join(),'new').canReplace,'huge draft must allow replacement');
  require(visibleRemoteInput('A\n\x1b\u202e') == 'A[LF]\n[ESC][U+202E]','controls must stay inert');
  print('PASS: $cases UTF-8 cases; 4094+3 replacement; exact append; oversized discard; empty/control contracts');
}
