import 'dart:async';
import 'dart:collection';
import 'dart:convert';
import 'dart:typed_data';

int utf8ByteLength(String value) => utf8.encode(value).length;

/// Implemented by the app-private native atomic marker bridge. No command body.
abstract class RemoteInputJournal {
  Future<List<String>> readAll();
  Future<String> prepare(String record);
  Future<void> complete(String record,String lease);
  Future<void> abandon(String record,String lease);
  Future<void> resolve(String record);
}

bool isRemoteInputJournalLease(Object? value) => value is String && RegExp(r'^[0-9a-f]{32}$').hasMatch(value);

/// Parse the entire bounded table before exposing any target. Corrupt unrelated
/// records fail closed, while valid records for other endpoints never lock this
/// endpoint. Legacy marker strings retain their original v1/v2 route binding.
List<RemoteInputPending> parseRemoteInputJournalRecords(List<String> records) {
  if (records.length > 32 || records.fold<int>(0,(total,raw) => total + utf8ByteLength(raw)) > 262144 ||
      utf8ByteLength(jsonEncode({'schemaVersion':3,'records':records})) > 262144) {
    throw const FormatException('input_journal_invalid');
  }
  final result = <RemoteInputPending>[],endpoints = <String>{};
  for (final raw in records) {
    final pending = RemoteInputPending.parse(raw);
    if (!endpoints.add(pending.target.endpointKey)) throw const FormatException('input_journal_invalid');
    result.add(pending);
  }
  return result;
}

/// Owns the original prepare and complete futures even after a caller times out
/// or cancels. Abandon waits for both to settle and can only retire this exact
/// raw/lease; it never deletes a durable marker or retries input.
class RemoteInputJournalClaim {
  RemoteInputJournalClaim(this.journal,this.pending) {
    prepared = Future<String>.sync(() => journal.prepare(pending.raw)).then((lease) {
      if (!isRemoteInputJournalLease(lease)) throw const FormatException('input_journal_invalid');
      return lease;
    });
    // Keep late failures handled even if the caller has already been cancelled.
    unawaited(prepared.then<void>((_) {},onError:(Object _,StackTrace __) {}));
  }
  final RemoteInputJournal journal;
  final RemoteInputPending pending;
  late final Future<String> prepared;
  Future<void>? _completion,_retirement;
  bool completed = false;
  Future<void> complete() {
    if (_retirement != null) return Future<void>.error(const FormatException('input_journal_unavailable'));
    return _completion ??= () async {
      final lease = await prepared;
      await journal.complete(pending.raw,lease);
      completed = true;
    }();
  }
  Future<void> abandon() => _retirement ??= () async {
    try { await _completion; } catch (_) { /* known result, persistent marker */ }
    if (completed) return;
    String lease;
    try { lease = await prepared; } catch (_) { return; }
    await journal.abandon(pending.raw,lease);
  }();
}

/// One adapter's view of the native target table. Native prepare is the shared
/// atomic lock across adapters; these local records also retain cancelled,
/// unsettled claims so a read cannot prematurely erase their ownership.
class RemoteInputJournalSession {
  RemoteInputJournalSession(this.journal);
  final RemoteInputJournal journal;
  final Map<String,RemoteInputPending> _records = {};
  final Map<String,RemoteInputJournalClaim> _claims = {};
  int _readEpoch = 0;
  bool ready = false;
  RemoteInputPending? pendingFor(RemoteInputTarget target) {
    for (final pending in _records.values) {
      if (pending.target.sameEndpoint(target)) return pending;
    }
    return null;
  }
  bool isCurrentRead(int revision) => ready && revision == _readEpoch;
  bool hasClaimFor(RemoteInputTarget target) => _claims.values.any((claim) => claim.pending.target.sameEndpoint(target));
  Future<int> refresh() async {
    final epoch = ++_readEpoch;
    try {
      final parsed = parseRemoteInputJournalRecords(await journal.readAll());
      if (epoch != _readEpoch) return epoch;
      final next = {for (final pending in parsed) pending.raw:_records[pending.raw] ?? pending};
      for (final claim in _claims.values) {
        if (!claim.completed) next[claim.pending.raw] = claim.pending;
      }
      _records..clear()..addAll(next); ready = true;
      return epoch;
    } catch (_) { if (epoch == _readEpoch) ready = false; rethrow; }
  }
  RemoteInputJournalClaim prepare(RemoteInputPending pending) {
    if (!ready || _claims.length >= 32 || _records.length >= 32 || pendingFor(pending.target) != null) {
      throw const FormatException('input_journal_unavailable');
    }
    _records[pending.raw] = pending;
    final claim = RemoteInputJournalClaim(journal,pending);
    _claims[pending.raw] = claim;
    return claim;
  }
  Future<void> complete(RemoteInputJournalClaim claim) async {
    if (!identical(_claims[claim.pending.raw],claim)) throw const FormatException('input_journal_unavailable');
    await claim.complete();
    _records.remove(claim.pending.raw);
  }
  Future<void> retire(RemoteInputJournalClaim claim) async {
    if (!identical(_claims[claim.pending.raw],claim)) throw const FormatException('input_journal_unavailable');
    try {
      await claim.abandon();
      if (identical(_claims[claim.pending.raw],claim)) _claims.remove(claim.pending.raw);
      await refresh();
    } catch (_) { ready = false; rethrow; }
  }
  Future<void> resolve(String reviewedRaw) async {
    // The backend checks exact raw plus absence of any active endpoint lease.
    await journal.resolve(reviewedRaw);
    _records.remove(reviewedRaw);
    await refresh();
  }
}

class RemoteInputPending {
  const RemoteInputPending(this.raw, this.requestId, this.target, this.at);
  final String raw, requestId;
  final RemoteInputTarget target;
  final DateTime at;
  static const fields = {'schemaVersion','requestId','host','port','username','hostFingerprint',
    'session','socketPath','paneId','terminalId','generation','createdAt'};
  static const routedFields = {...fields,'route'};
  factory RemoteInputPending.create(String id, RemoteInputTarget target) {
    final at = DateTime.now().toUtc();
    final raw = jsonEncode({'schemaVersion':target.route == 'system' ? 1 : 2,'requestId':id,'host':target.host,'port':target.port,
      'username':target.username,'hostFingerprint':target.hostFingerprint,'session':target.session,
      'socketPath':target.socketPath,'paneId':target.paneId,'terminalId':target.terminalId,
      'generation':target.generation,'createdAt':at.toIso8601String(),
      if (target.route != 'system') 'route':target.route});
    RemoteInputPending.parse(raw);
    return RemoteInputPending(raw,id,target,at);
  }
  factory RemoteInputPending.parse(String raw) {
    if (utf8ByteLength(raw) > 8192) throw const FormatException('input_journal_invalid');
    final data = jsonDecode(raw);
    if (data is! Map<String,dynamic>) throw const FormatException('input_journal_invalid');
    if (data['schemaVersion'] is! int) throw const FormatException('input_journal_invalid');
    final expected = data['schemaVersion'] == 1 ? fields : data['schemaVersion'] == 2 ? routedFields : <String>{};
    if (data.length != expected.length || data.keys.any((k) => !expected.contains(k)) || jsonEncode(data) != raw) {
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
    final route = data['schemaVersion'] == 1 || data['route'] == null ? 'system' : field('route',256);
    final at = DateTime.tryParse(field('createdAt',40));
    if (!RegExp(r'^[0-9a-f]{32}$').hasMatch(id) || !RegExp(r'^term_[0-9a-f]{1,123}$').hasMatch(terminal) ||
        session == 'default' || !RegExp(r'^[A-Za-z0-9_-]{1,64}$').hasMatch(session) ||
        !RegExp(r'^[A-Za-z0-9:_-]{1,128}$').hasMatch(pane) || !socket.startsWith('/') ||
        socket.split('/').skip(1).any((s) => s.isEmpty || s == '.' || s == '..') ||
        !RegExp(r'^[A-Za-z0-9:.\[\]_-]+$').hasMatch(host) || username.startsWith('-') || RegExp(r'\s').hasMatch(username) ||
        !RegExp(r'^SHA256:[A-Za-z0-9+/]{43}$').hasMatch(fingerprint) || at == null || !at.isUtc ||
        port is! int || port < 1 || port > 65535 || generation is! int || generation < 1 || generation > 2147483647 ||
        (data['schemaVersion'] == 2 && data['route'] != null && !isValidOverlayRoute(route))) {
      throw const FormatException('input_journal_invalid');
    }
    return RemoteInputPending(raw,id,RemoteInputTarget(connection:Object(),generation:generation,
      host:host,port:port,username:username,hostFingerprint:fingerprint,session:session,
      socketPath:socket,paneId:pane,terminalId:terminal,route:route),at);
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
    required this.paneId, required this.terminalId, this.route = 'system'});
  final Object connection;
  final int generation, port;
  final String host, username, hostFingerprint, session, socketPath, paneId, terminalId;
  final String route;
  String get label => '$username@$host:$port / $session / $paneId / $terminalId';
  String get endpointKey => jsonEncode([route,host,port,username,hostFingerprint,session,socketPath,paneId,terminalId]);
  bool sameEndpoint(RemoteInputTarget other) => host == other.host && port == other.port &&
    username == other.username && hostFingerprint == other.hostFingerprint &&
    session == other.session && socketPath == other.socketPath &&
    paneId == other.paneId && terminalId == other.terminalId && route == other.route;
}

/// Only public, stable metadata identifying the actual overlay socket route.
bool isValidOverlayRoute(String route) {
  final match = RegExp(r'^easy-tier:([a-f0-9]{32}):([1-9][0-9]{0,9}):([a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12})$').firstMatch(route);
  return match != null && int.parse(match.group(2)!) <= 2147483647;
}

enum RemoteInputMode { observe, direct, draft }
enum RemoteInputDisposition { rejected, accepted, unknown }

class RemoteInputResult {
  const RemoteInputResult(this.disposition, this.code, {this.requiresJournalRecovery = false, this.receipt,this.pending});
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
  final RemoteInputPending? pending;
  RemoteInputResult withPending(RemoteInputPending value) => RemoteInputResult(disposition,code,
    requiresJournalRecovery:requiresJournalRecovery,receipt:receipt,pending:value);
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
  RemoteInputRecord(this.target, Uint8List data, this.at, {this.requestId,this.knownDisposition,this.pendingRaw,this.receipt}) : bytes = Uint8List.fromList(data);
  final RemoteInputTarget target;
  final Uint8List bytes;
  final DateTime at;
  final String? requestId;
  final RemoteInputDisposition? knownDisposition;
  final String? pendingRaw;
  final RemoteInputReceipt? receipt;
  String get text => utf8.decode(bytes, allowMalformed: true);
}

/// Captured before the full frame's journal read starts. A successful read may
/// clear only this exact old display record while its UI epoch stays current.
class RemoteInputJournalReview {
  const RemoteInputJournalReview(this.gateTarget,this.refreshTarget,this.epoch,this.record);
  final RemoteInputTarget? gateTarget;
  final RemoteInputTarget refreshTarget;
  final int epoch;
  final RemoteInputRecord record;
  RemoteInputResult? get knownResult => switch (record.knownDisposition) {
    RemoteInputDisposition.accepted => RemoteInputResult.accepted(receipt:record.receipt),
    RemoteInputDisposition.rejected => const RemoteInputResult.rejected('input_prior_result_known'),
    _ => null,
  };
}
/// A plain, inspectable ticket. The adapter verifies current read revision,
/// connection and observation epoch before the GUI may coordinate old display.
class RemoteInputJournalReadTicket {
  const RemoteInputJournalReadTicket(this.review,this.target,this.observationEpoch,this.revision);
  final RemoteInputJournalReview review;
  final RemoteInputTarget target;
  final int observationEpoch,revision;
}

typedef RemoteInputWriter = Future<RemoteInputResult> Function(RemoteInputTarget target,
  Uint8List bytes, bool Function() stillCurrent);
class _QueuedInput {
  _QueuedInput(this.lease, this.bytes);
  final RemoteInputLease lease;
  final Uint8List bytes;
  final result = Completer<RemoteInputResult>();
}

class _InputLane {
  final queue = Queue<_QueuedInput>();
  int queuedBytes = 0;
  bool running = false;
}

/// Bounded connected-only ordering lanes, not offline/retry queues. Each target
/// keeps one writer; an unsettled old target never serializes a different one.
class RemoteInputGate {
  RemoteInputGate(this.writer, {this.onChanged});
  final RemoteInputWriter writer;
  void Function()? onChanged;
  RemoteInputTarget? target;
  RemoteInputCapability? capability;
  RemoteInputMode mode = RemoteInputMode.observe;
  bool fresh = false, focused = false;
  int epoch = 0;
  final Map<String,RemoteInputRecord> _unknownByEndpoint = {};
  RemoteInputRecord? get unknown => target == null ? null : _unknownByEndpoint[target!.endpointKey];
  RemoteInputResult? lastResult;
  final Map<String,_InputLane> _lanes = {};
  bool get sending => target != null && (_lanes[target!.endpointKey]?.running ?? false);
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
    final previous = _unknownByEndpoint[pending.target.endpointKey];
    if (previous?.pendingRaw == pending.raw) return;
    // Preserve richer bytes/known ACK only when they belong to this same raw.
    _unknownByEndpoint[pending.target.endpointKey] = RemoteInputRecord(pending.target,Uint8List(0),pending.at,
      requestId:pending.requestId,pendingRaw:pending.raw);
    if (target?.sameEndpoint(pending.target) == true) { epoch++; mode = RemoteInputMode.observe; _discardQueued(); }
    _notify();
  }

  RemoteInputJournalReview? captureJournalRefresh(RemoteInputTarget refreshTarget) {
    final previous = _unknownByEndpoint[refreshTarget.endpointKey];
    if (previous?.pendingRaw == null) return null;
    return RemoteInputJournalReview(target,refreshTarget,epoch,previous!);
  }
  bool reconcileJournalRefresh(RemoteInputJournalReview review) {
    final key = review.refreshTarget.endpointKey;
    if (epoch != review.epoch || !identical(target,review.gateTarget) ||
        !identical(_unknownByEndpoint[key],review.record) || review.record.pendingRaw == null) return false;
    _unknownByEndpoint.remove(key);
    if (target?.sameEndpoint(review.refreshTarget) == true) {
      epoch++; mode = RemoteInputMode.observe; _discardQueued(); lastResult = review.knownResult;
    }
    _notify(); return true;
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

  bool acknowledgeUnknown({RemoteInputRecord? reviewed}) {
    if (!canAcknowledgeUnknown || sending || (reviewed != null && !identical(reviewed,unknown))) return false;
    _unknownByEndpoint.remove(target!.endpointKey); lastResult = null; epoch++; mode = RemoteInputMode.observe;
    _notify(); return true;
  }

  Future<RemoteInputResult> submit(RemoteInputLease lease, String text) {
    final bytes = Uint8List.fromList(utf8.encode(text));
    if (!current(lease) || bytes.isEmpty || bytes.length > capability!.maxBytes) {
      return Future.value(const RemoteInputResult.rejected('input_not_ready'));
    }
    final key = lease.target.endpointKey;
    if (!_lanes.containsKey(key) && _lanes.length >= 32) {
      epoch++; mode = RemoteInputMode.observe; _discardQueued();
      lastResult = const RemoteInputResult.rejected('input_buffer_full'); _notify();
      return Future.value(lastResult!);
    }
    final lane = _lanes.putIfAbsent(key,_InputLane.new);
    if (lease.mode == RemoteInputMode.draft && (lane.running || lane.queue.isNotEmpty)) {
      return Future.value(const RemoteInputResult.rejected('input_not_ready'));
    }
    if (lane.queue.length >= 64 || lane.queuedBytes + bytes.length > 4096) {
      epoch++; mode = RemoteInputMode.observe; _discardQueued();
      lastResult = const RemoteInputResult.rejected('input_buffer_full'); _notify();
      return Future.value(lastResult!);
    }
    final entry = _QueuedInput(lease,bytes);
    lane.queue.add(entry); lane.queuedBytes += bytes.length;
    if (!lane.running) unawaited(_drain(key,lane));
    return entry.result.future;
  }

  void _discardQueued() {
    final lane = target == null ? null : _lanes[target!.endpointKey];
    if (lane == null) return;
    while (lane.queue.isNotEmpty) {
      lane.queue.removeFirst().result.complete(const RemoteInputResult.rejected('input_cancelled_before_write'));
    }
    lane.queuedBytes = 0;
  }

  Future<void> _drain(String key,_InputLane lane) async {
    lane.running = true; _notify();
    try {
      while (lane.queue.isNotEmpty) {
        final entry = lane.queue.removeFirst(); lane.queuedBytes -= entry.bytes.length;
        if (!current(entry.lease)) {
          entry.result.complete(const RemoteInputResult.rejected('input_cancelled_before_write')); continue;
        }
        final record = RemoteInputRecord(entry.lease.target,entry.bytes,DateTime.now());
        RemoteInputResult result;
        try { result = await writer(entry.lease.target,entry.bytes,() => current(entry.lease)); }
        catch (_) { result = const RemoteInputResult.unknown(); }
        final sameLease = current(entry.lease);
        if (result.disposition == RemoteInputDisposition.unknown || result.requiresJournalRecovery) {
          _unknownByEndpoint.putIfAbsent(key,() => RemoteInputRecord(record.target,record.bytes,record.at,
            requestId:result.pending?.requestId,pendingRaw:result.pending?.raw,receipt:result.receipt,
            knownDisposition:result.requiresJournalRecovery ? result.disposition : null));
          if (target?.sameEndpoint(record.target) == true) { epoch++; mode = RemoteInputMode.observe; _discardQueued(); }
        } else if (result.pending != null) {
          restorePending(result.pending!);
        } else if (result.code == 'input_journal_unavailable' && sameLease) {
          // A cancelled old read cannot declare a different current target's
          // storage unavailable. Its own fresh read remains the authority.
          invalidate();
        }
        if (sameLease) lastResult = result;
        entry.result.complete(result); _notify();
      }
    } finally {
      lane.running = false;
      if (lane.queue.isEmpty && identical(_lanes[key],lane)) _lanes.remove(key);
      _notify();
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
