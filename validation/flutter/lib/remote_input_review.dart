const remoteInputReviewByteLimit = 4096;

/// Exact within the limit, otherwise a limit+1 sentinel. Avoid encoding or
/// walking an arbitrarily large clipboard after it is already unusable.
int boundedRemoteInputBytes(String text) {
  var bytes = 0;
  for (var index = 0; index < text.length; index++) {
    final unit = text.codeUnitAt(index);
    if (unit < 0x80) { bytes++; }
    else if (unit < 0x800) { bytes += 2; }
    else if (unit >= 0xd800 && unit <= 0xdbff && index + 1 < text.length &&
        text.codeUnitAt(index + 1) >= 0xdc00 && text.codeUnitAt(index + 1) <= 0xdfff) {
      bytes += 4; index++;
    } else { bytes += 3; } // Includes UTF-8 replacement for a lone surrogate.
    if (bytes > remoteInputReviewByteLimit) return remoteInputReviewByteLimit + 1;
  }
  return bytes;
}

String remoteInputByteLabel(int bytes) => bytes > remoteInputReviewByteLimit
  ? '超过 $remoteInputReviewByteLimit' : '$bytes';

/// Review labels never change sendable bytes. Oversized clipboard contents are
/// discarded, so no UI can accidentally render them or offer a partial paste.
class RemotePasteReview {
  factory RemotePasteReview(String original,String clipboard) {
    final originalBytes = boundedRemoteInputBytes(original),clipboardBytes = boundedRemoteInputBytes(clipboard);
    return RemotePasteReview._(original,clipboardBytes <= remoteInputReviewByteLimit ? clipboard : '',
      originalBytes,clipboardBytes);
  }
  RemotePasteReview._(this.original,this.clipboard,this.originalBytes,this.clipboardBytes);
  final String original,clipboard;
  final int originalBytes,clipboardBytes;
  int get appendedBytes => originalBytes + clipboardBytes > remoteInputReviewByteLimit
    ? remoteInputReviewByteLimit + 1 : originalBytes + clipboardBytes;
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
