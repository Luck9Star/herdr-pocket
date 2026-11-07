import 'remote_input.dart' show utf8ByteLength;

const remoteInputReviewByteLimit = 4096;

/// Counts original bytes; review labels never change the bytes to be sent.
class RemotePasteReview {
  RemotePasteReview(this.original,this.clipboard) :
    clipboardBytes = utf8ByteLength(clipboard),appendedBytes = utf8ByteLength(original + clipboard);
  final String original,clipboard;
  final int clipboardBytes,appendedBytes;
  bool get canReplace => clipboard.isNotEmpty && clipboardBytes <= remoteInputReviewByteLimit;
  bool get canAppend => canReplace && appendedBytes <= remoteInputReviewByteLimit;
}

/// Make controls and directional formatting visible without executing them in
/// the review itself. LF keeps a visual line break as well as its explicit tag.
String visibleRemoteInput(String text) {
  final result = StringBuffer();
  var count = 0;
  for (final rune in text.runes) {
    // Any usable/sendable input fits in this many runes. Avoid mounting an
    // unbounded clipboard in a phone dialog when its use is already forbidden.
    if (count++ == remoteInputReviewByteLimit) { result.write('\n…（预览已截短）'); break; }
    final label = switch (rune) {
      0x09 => 'TAB',0x0a => 'LF',0x0d => 'CR',0x1b => 'ESC',0x7f => 'DEL',
      _ => null,
    };
    final invisible = rune < 0x20 || (rune >= 0x7f && rune <= 0x9f) || rune == 0x00ad || rune == 0x061c ||
      (rune >= 0x200b && rune <= 0x200f) || (rune >= 0x2028 && rune <= 0x202e) ||
      (rune >= 0x2060 && rune <= 0x206f) || rune == 0xfeff;
    if (invisible) {
      result.write('[${label ?? 'U+${rune.toRadixString(16).toUpperCase().padLeft(4,'0')}'}]');
      if (rune == 0x0a) result.writeln();
    } else { result.writeCharCode(rune); }
  }
  return result.toString();
}
