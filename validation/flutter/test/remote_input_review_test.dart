import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/remote_input_review.dart';

void main() {
  test('review exposes controls, directional formatting and invisible separators as inert text',() {
    expect(visibleRemoteInput('A\n\t\r\x1b[31m\x00\x7f\u0085\u202eB\u2066C\u2069\u200b\ufeff\u2028'),
      'A[LF]\n[TAB][CR][ESC][31m[U+0000][DEL][U+0085][U+202E]B[U+2066]C[U+2069][U+200B][U+FEFF][U+2028]');
  });
  test('ordinary Unicode and literal bracket labels remain visible without rewriting original input',() {
    const raw = '中文 e\u0301 🙂 [ESC]';
    final review = RemotePasteReview('old',raw);
    expect(visibleRemoteInput(raw),raw); expect(review.clipboard,raw); expect(review.original,'old');
  });
  test('4096 limit counts raw UTF8 rather than review labels or grapheme count',() {
    final exact = RemotePasteReview('',List.filled(4096,'\x1b').join());
    expect(exact.clipboardBytes,4096); expect(exact.canReplace,isTrue); expect(exact.canAppend,isTrue);
    expect(visibleRemoteInput(exact.clipboard).length,greaterThan(4096));
    final unicode = RemotePasteReview('',List.filled(1366,'中').join());
    expect(unicode.clipboardBytes,4098); expect(unicode.canReplace,isFalse); expect(unicode.canAppend,isFalse);
  });
  test('append counts existing bytes, while replacing an oversized draft remains an explicit option',() {
    final review = RemotePasteReview(List.filled(4097,'x').join(),'new');
    expect(review.appendedBytes,4100); expect(review.canAppend,isFalse); expect(review.canReplace,isTrue);
    expect(RemotePasteReview(List.filled(4093,'x').join(),'中').canAppend,isTrue);
    expect(RemotePasteReview(List.filled(4094,'x').join(),'中').canAppend,isFalse);
  });
  test('empty clipboard and oversized raw clipboard cannot replace or append',() {
    for (final clipboard in ['',List.filled(4097,'x').join()]) {
      final review = RemotePasteReview('original',clipboard);
      expect(review.canAppend,isFalse); expect(review.canReplace,isFalse);
    }
  });
  test('unusable oversized text has a bounded explicitly truncated display and unchanged raw byte count',() {
    final raw = List.filled(10000,'x').join(),review = RemotePasteReview('',List.filled(10000,'x').join());
    expect(visibleRemoteInput(raw),endsWith('…（预览已截短）'));
    expect(visibleRemoteInput(raw).length,lessThan(4200));
    expect(review.clipboardBytes,10000); expect(review.clipboard,raw); expect(review.canReplace,isFalse);
  });
}
