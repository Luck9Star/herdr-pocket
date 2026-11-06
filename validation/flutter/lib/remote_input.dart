import 'dart:async';
import 'dart:collection';
import 'dart:convert';
import 'dart:typed_data';

int utf8ByteLength(String value) => utf8.encode(value).length;

/// Implemented by the app-private native atomic marker bridge. No command body.
abstract class RemoteInputJournal {
  Future<String?> read();
  Future<void> prepare(String record);
  Future<void> clear(String record);
}

class RemoteInputPending {
  const RemoteInputPending(this.raw, this.requestId, this.target, this.at);
  final String raw, requestId;
  final RemoteInputTarget target;
  final DateTime at;
  static const fields = {'schemaVersion','requestId','host','port','username','hostFingerprint',
    'session','socketPath','paneId','terminalId','generation','createdAt'};
  factory RemoteInputPending.create(String id, RemoteInputTarget target) {
    final at = DateTime.now().toUtc();
    final raw = jsonEncode({'schemaVersion':1,'requestId':id,'host':target.host,'port':target.port,
      'username':target.username,'hostFingerprint':target.hostFingerprint,'session':target.session,
      'socketPath':target.socketPath,'paneId':target.paneId,'terminalId':target.terminalId,
      'generation':target.generation,'createdAt':at.toIso8601String()});
    RemoteInputPending.parse(raw);
    return RemoteInputPending(raw,id,target,at);
  }
  factory RemoteInputPending.parse(String raw) {
    if (utf8ByteLength(raw) > 8192) throw const FormatException('input_journal_invalid');
    final data = jsonDecode(raw);
    if (data is! Map<String,dynamic> || data.length != fields.length ||
        data.keys.any((k) => !fields.contains(k)) || data['schemaVersion'] != 1 || jsonEncode(data) != raw) {
      throw const FormatException('input_journal_invalid');
    }
    String field(String key, int limit) {
      final value = data[key];
      if (value is! String || value.isEmpty || value.length > limit || RegExp(r'[\x00-\x1f\x7f]').hasMatch(value)) {
        throw const FormatException('input_journal_invalid');
      }
      return value;
    }
    final id = field('requestId',32), terminal = field('terminalId',128);
    final session = field('session',64), socket = field('socketPath',1024);
    final fingerprint = field('hostFingerprint',100), host = field('host',253);
    final username = field('username',128), pane = field('paneId',128);
    final port = data['port'], generation = data['generation'];
    final at = DateTime.tryParse(field('createdAt',40));
    if (!RegExp(r'^[0-9a-f]{32}$').hasMatch(id) || !RegExp(r'^term_[0-9a-f]{1,123}$').hasMatch(terminal) ||
        session == 'default' || !RegExp(r'^[A-Za-z0-9_-]{1,64}$').hasMatch(session) ||
        !RegExp(r'^[A-Za-z0-9:_-]{1,128}$').hasMatch(pane) || !socket.startsWith('/') ||
        socket.split('/').skip(1).any((s) => s.isEmpty || s == '.' || s == '..') ||
        !RegExp(r'^[A-Za-z0-9:.\[\]_-]+$').hasMatch(host) || username.startsWith('-') || RegExp(r'\s').hasMatch(username) ||
        !RegExp(r'^SHA256:[A-Za-z0-9+/]{43}$').hasMatch(fingerprint) || at == null || !at.isUtc ||
        port is! int || port < 1 || port > 65535 || generation is! int || generation < 1 || generation > 2147483647) {
      throw const FormatException('input_journal_invalid');
    }
    return RemoteInputPending(raw,id,RemoteInputTarget(connection:Object(),generation:generation,
      host:host,port:port,username:username,hostFingerprint:fingerprint,session:session,
      socketPath:socket,paneId:pane,terminalId:terminal),at);
  }
}

/// A capability of the separately patched test server, never of stock 0.9.5.
class RemoteInputCapability {
  const RemoteInputCapability(this.maxBytes);
  final int maxBytes;
  static RemoteInputCapability? parse(Object? value) {
    if (value is! Map || value['type'] != 'pocket_input_capabilities' ||
        value['version'] != 1 || value['protocol'] != 22 ||
        value['atomic_terminal_guard'] != true || value['raw_bytes'] != true ||
        value['max_input_bytes'] is! int || value['max_input_bytes'] != 4096) return null;
    return const RemoteInputCapability(4096);
  }
}

/// The opaque connection identity prevents a new connection reusing an old lease.
class RemoteInputTarget {
  const RemoteInputTarget({required this.connection, required this.generation,
    required this.host, required this.port, required this.username,
    required this.hostFingerprint, required this.session, required this.socketPath,
    required this.paneId, required this.terminalId});
  final Object connection;
  final int generation, port;
  final String host, username, hostFingerprint, session, socketPath, paneId, terminalId;
  String get label => '$username@$host:$port / $session / $paneId / $terminalId';
  bool sameEndpoint(RemoteInputTarget other) => host == other.host && port == other.port &&
    username == other.username && hostFingerprint == other.hostFingerprint &&
    session == other.session && socketPath == other.socketPath &&
    paneId == other.paneId && terminalId == other.terminalId;
}

enum RemoteInputMode { observe, direct, draft }
enum RemoteInputDisposition { rejected, accepted, unknown }

class RemoteInputResult {
  const RemoteInputResult(this.disposition, this.code, {this.requiresJournalRecovery = false, this.receipt});
  const RemoteInputResult.rejected(String code) : this(RemoteInputDisposition.rejected, code);
  const RemoteInputResult.accepted({RemoteInputReceipt? receipt})
    : this(RemoteInputDisposition.accepted, 'accepted', receipt:receipt);
  const RemoteInputResult.unknown() : this(RemoteInputDisposition.unknown, 'input_result_unknown');
  const RemoteInputResult.journalLocked(RemoteInputDisposition disposition, {RemoteInputReceipt? receipt})
    : this(disposition, 'input_journal_clear_failed', requiresJournalRecovery:true, receipt:receipt);
  final RemoteInputDisposition disposition;
  final String code;
  final bool requiresJournalRecovery;
  final RemoteInputReceipt? receipt;
}

/// Public acceptance metadata, created only after the complete ACK matches.
/// It proves queue admission, not terminal/application execution.
class RemoteInputReceipt {
  const RemoteInputReceipt(this.requestId,this.paneId,this.terminalId,this.acceptedBytes);
  final String requestId, paneId, terminalId;
  final int acceptedBytes;
  String get label => 'request $requestId · pane $paneId · terminal $terminalId · $acceptedBytes bytes';
}

class RemoteInputLease {
  const RemoteInputLease(this.target, this.epoch, this.mode);
  final RemoteInputTarget target;
  final int epoch;
  final RemoteInputMode mode;
}

/// Local-only record. Do not put its bytes or target in diagnostics/telemetry.
class RemoteInputRecord {
  RemoteInputRecord(this.target, Uint8List data, this.at, {this.requestId,this.knownDisposition}) : bytes = Uint8List.fromList(data);
  final RemoteInputTarget target;
  final Uint8List bytes;
  final DateTime at;
  final String? requestId;
  final RemoteInputDisposition? knownDisposition;
  String get text => utf8.decode(bytes, allowMalformed: true);
}

typedef RemoteInputWriter = Future<RemoteInputResult> Function(RemoteInputTarget target,
  Uint8List bytes, bool Function() stillCurrent);
class _QueuedInput {
  _QueuedInput(this.lease, this.bytes);
  final RemoteInputLease lease;
  final Uint8List bytes;
  final result = Completer<RemoteInputResult>();
}

/// A bounded, connected-only ordering buffer, not an offline/retry queue.
/// Invalidation drops every not-yet-submitted event. Only one write is in flight.
class RemoteInputGate {
  RemoteInputGate(this.writer, {this.onChanged});
  final RemoteInputWriter writer;
  void Function()? onChanged;
  RemoteInputTarget? target;
  RemoteInputCapability? capability;
  RemoteInputMode mode = RemoteInputMode.observe;
  bool fresh = false, focused = false, sending = false;
  int epoch = 0, _queuedBytes = 0;
  RemoteInputRecord? unknown;
  RemoteInputResult? lastResult;
  final _queue = Queue<_QueuedInput>();
  bool get canInput => fresh && focused && target != null && capability != null && unknown == null;
  bool get canAcknowledgeUnknown => unknown != null && fresh && capability != null && target != null &&
    !identical(target!.connection, unknown!.target.connection) &&
    target!.sameEndpoint(unknown!.target);
  void _notify() => onChanged?.call();

  void bind(RemoteInputTarget value, RemoteInputCapability? supported) {
    if (!identical(value, target)) {
      invalidate(); target = value;
    }
    capability = supported;
    if (supported == null && mode != RemoteInputMode.observe) {
      epoch++; mode = RemoteInputMode.observe; focused = false; _discardQueued();
    }
    fresh = true;
    _notify();
  }

  void restorePending(RemoteInputPending pending) {
    // Preserve richer in-process bytes if this is the same unresolved attempt.
    unknown ??= RemoteInputRecord(pending.target,Uint8List(0),pending.at,requestId:pending.requestId);
    epoch++; mode = RemoteInputMode.observe; _discardQueued(); _notify();
  }

  void invalidate() {
    epoch++; fresh = false; focused = false; mode = RemoteInputMode.observe;
    lastResult = null;
    _discardQueued(); _notify();
  }

  void setMode(RemoteInputMode value) {
    epoch++; _discardQueued();
    mode = canInput ? value : RemoteInputMode.observe;
    _notify();
  }

  void setFocused(bool value) {
    if (focused == value) return;
    focused = value; epoch++; _discardQueued();
    if (!value) mode = RemoteInputMode.observe;
    _notify();
  }

  RemoteInputLease? capture() => canInput && mode != RemoteInputMode.observe
    ? RemoteInputLease(target!, epoch, mode) : null;
  bool current(RemoteInputLease lease) => canInput && identical(lease.target,target) &&
    lease.epoch == epoch && lease.mode == mode;

  bool acknowledgeUnknown() {
    if (!canAcknowledgeUnknown || sending) return false;
    unknown = null; lastResult = null; epoch++; mode = RemoteInputMode.observe;
    _notify(); return true;
  }

  Future<RemoteInputResult> submit(RemoteInputLease lease, String text) {
    final bytes = Uint8List.fromList(utf8.encode(text));
    if (!current(lease) || bytes.isEmpty || bytes.length > capability!.maxBytes ||
        (lease.mode == RemoteInputMode.draft && (sending || _queue.isNotEmpty))) {
      return Future.value(const RemoteInputResult.rejected('input_not_ready'));
    }
    // Keep intentional live keystrokes ordered, with an explicit small bound.
    // Overflow stops that input mode, discards unsent events, and never retries.
    if (_queue.length >= 64 || _queuedBytes + bytes.length > 4096) {
      epoch++; mode = RemoteInputMode.observe; _discardQueued();
      lastResult = const RemoteInputResult.rejected('input_buffer_full'); _notify();
      return Future.value(lastResult!);
    }
    final entry = _QueuedInput(lease,bytes);
    _queue.add(entry); _queuedBytes += bytes.length;
    if (!sending) unawaited(_drain());
    return entry.result.future;
  }

  void _discardQueued() {
    while (_queue.isNotEmpty) {
      _queue.removeFirst().result.complete(const RemoteInputResult.rejected('input_cancelled_before_write'));
    }
    _queuedBytes = 0;
  }

  Future<void> _drain() async {
    while (_queue.isNotEmpty) {
      final entry = _queue.removeFirst(); _queuedBytes -= entry.bytes.length;
      if (!current(entry.lease)) {
        entry.result.complete(const RemoteInputResult.rejected('input_cancelled_before_write')); continue;
      }
      sending = true; _notify();
      final record = RemoteInputRecord(entry.lease.target,entry.bytes,DateTime.now());
      RemoteInputResult result;
      // A writer must distinguish its pre-write failures. An escaped exception
      // cannot prove that bytes were not accepted, so conservatively lock.
      try { result = await writer(entry.lease.target,entry.bytes,() => current(entry.lease)); }
      catch (_) { result = const RemoteInputResult.unknown(); }
      if (result.disposition == RemoteInputDisposition.unknown || result.requiresJournalRecovery) {
        unknown = RemoteInputRecord(record.target,record.bytes,record.at,
          knownDisposition:result.requiresJournalRecovery ? result.disposition : null);
        epoch++; mode = RemoteInputMode.observe; _discardQueued();
      } else if (result.code == 'input_journal_unavailable') {
        invalidate();
      }
      if (identical(entry.lease.target,target) || result.disposition == RemoteInputDisposition.unknown) lastResult = result;
      entry.result.complete(result); sending = false; _notify();
    }
  }
}

/// Matching guarded-server error is the only known remote rejection.
/// A success confirms runtime queue acceptance, never PTY/application execution.
RemoteInputResult parseInputResponse(Map<String,dynamic> value, String id,
    RemoteInputTarget target, int byteCount) {
  if (value['id'] != id) return const RemoteInputResult.unknown();
  final error = value['error'];
  if (error is Map && error['code'] == 'pocket_input_rejected' && value['result'] == null) {
    return const RemoteInputResult.rejected('pocket_input_rejected');
  }
  final result = value['result'];
  if (error != null || value['ok'] == false || result is! Map ||
      result['type'] != 'pocket_input_accepted' || result['pane_id'] != target.paneId ||
      result['terminal_id'] != target.terminalId || result['accepted_bytes'] is! int ||
      result['accepted_bytes'] != byteCount) return const RemoteInputResult.unknown();
  return RemoteInputResult.accepted(receipt:RemoteInputReceipt(id,target.paneId,target.terminalId,byteCount));
}
