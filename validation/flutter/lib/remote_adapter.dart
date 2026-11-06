import 'dart:async';
import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';
import 'package:dartssh2/dartssh2.dart';
import 'package:pointycastle/digests/sha256.dart';
import 'remote_input.dart';
import 'network_runtime.dart' show RoutedSSHSocket;

/// Stable safe codes only: never include server output, config or private keys.
class RemoteFailure implements Exception {
  const RemoteFailure(this.code);
  final String code;
  @override
  String toString() => 'RemoteFailure($code)';
}

String shellQuote(String value) => "'${value.replaceAll("'", "'\\''")}'";

class RemoteConfig {
  RemoteConfig._(this.host, this.port, this.username, this.expectedHostKey,
    this.privateKeyPem, this.socketPath, this.herdrPath, this.session, this.paneId,
    this.expectedFingerprint, [this.deviceIdentity]);
  final String host, username, expectedHostKey, privateKeyPem, socketPath, herdrPath, session, paneId, expectedFingerprint;
  final int port;
  final SSHIdentity? deviceIdentity;
  static const fields = {'schemaVersion','host','port','username','expectedHostKey',
    'privateKeyPem','socketPath','herdrPath','session','paneId','reviewConfirmed'};

  factory RemoteConfig.fromJson(Map<String, dynamic> data) {
    if (data.keys.any((k) => !fields.contains(k)) || data['schemaVersion'] != 1 ||
        data['reviewConfirmed'] != true || utf8.encode(jsonEncode(data)).length > 32768) {
      throw const RemoteFailure('review_required');
    }
    String field(String key, int max, {bool secret = false}) {
      final value = data[key];
      if (value is! String || value.isEmpty || value.length > max ||
          (!secret && RegExp(r'[\x00-\x1f\x7f]').hasMatch(value))) {
        throw const RemoteFailure('invalid_config');
      }
      return value;
    }
    final host = field('host',253), username = field('username',128);
    if (!RegExp(r'^[A-Za-z0-9:.\[\]_-]+$').hasMatch(host) ||
        RegExp(r'\s').hasMatch(username) || username.startsWith('-')) {
      throw const RemoteFailure('invalid_config');
    }
    final port = data['port'];
    if (port is! int || port < 1 || port > 65535) throw const RemoteFailure('invalid_config');
    final session = field('session',64);
    final pane = data['paneId'] ?? '';
    if (pane is! String || pane.length > 128) throw const RemoteFailure('invalid_target');
    if (session == 'default' || !RegExp(r'^[A-Za-z0-9_-]{1,64}$').hasMatch(session) ||
        (pane.isNotEmpty && !RegExp(r'^[A-Za-z0-9:_-]{1,128}$').hasMatch(pane))) throw const RemoteFailure('invalid_target');
    String path(String key) {
      final p = field(key,1024);
      if (!p.startsWith('/') || p.split('/').skip(1).any((s) => s.isEmpty || s == '.' || s == '..')) {
        throw const RemoteFailure('invalid_path');
      }
      return p;
    }
    final key = field('expectedHostKey',4096);
    final match = RegExp(r'^ssh-ed25519 ([A-Za-z0-9+/]+={0,2})$').firstMatch(key);
    if (match == null) throw const RemoteFailure('invalid_host_key');
    Uint8List blob;
    try { blob = base64Decode(match.group(1)!); } catch (_) { throw const RemoteFailure('invalid_host_key'); }
    if (blob.length != 51 || base64Encode(blob) != match.group(1) ||
        ByteData.sublistView(blob).getUint32(0) != 11 ||
        ascii.decode(blob.sublist(4,15),allowInvalid:true) != 'ssh-ed25519' ||
        ByteData.sublistView(blob).getUint32(15) != 32) throw const RemoteFailure('invalid_host_key');
    final fingerprint = 'SHA256:${base64Encode(SHA256Digest().process(blob)).replaceAll('=', '')}';
    return RemoteConfig._(host,port,username,key,field('privateKeyPem',16384,secret:true),
      path('socketPath'),path('herdrPath'),session,pane,fingerprint);
  }

  /// Device credential path accepts no private key field or fallback identity.
  factory RemoteConfig.fromDeviceJson(Map<String,dynamic> data, SSHIdentity identity) {
    if (data.containsKey('privateKeyPem')) throw const RemoteFailure('invalid_config');
    final c = RemoteConfig.fromJson({...data,'privateKeyPem':'device-handle-only'});
    return RemoteConfig._(c.host,c.port,c.username,c.expectedHostKey,'',c.socketPath,
      c.herdrPath,c.session,c.paneId,c.expectedFingerprint,identity);
  }

  String get configRoot {
    final suffix = '/herdr/sessions/$session/herdr.sock';
    if (!socketPath.endsWith(suffix) || socketPath.length <= suffix.length) {
      throw const RemoteFailure('session_mismatch');
    }
    return socketPath.substring(0,socketPath.length-suffix.length);
  }

  String observeCommand(String terminalId) {
    if (!RegExp(r'^term_[0-9a-f]{1,123}$').hasMatch(terminalId)) throw const RemoteFailure('invalid_terminal_id');
    return '/usr/bin/env ${shellQuote('XDG_CONFIG_HOME=$configRoot')} ${shellQuote(herdrPath)} '
      '--session ${shellQuote(session)} terminal session observe ${shellQuote(terminalId)} --cols 80 --rows 24';
  }

}

class RemoteEvidence {
  bool hostKeyChecked = false, hostKeyMatched = false, authStarted = false;
  bool snapshotReceived = false, fullFrameReceived = false;
  int generation = 0, lateEventsIgnored = 0;
  int frameCount = 0, deltaFrames = 0, paneCount = 0, connectionCount = 0, bufferHighWaterBytes = 0;
  int? lastSeq;
  String? errorCode;
  Map<String,Object?> toReport(String testCase, bool passed) => {
    'status': passed ? 'passed' : 'failed', 'case':testCase,
    'hostKeyChecked':hostKeyChecked, 'hostKeyMatched':hostKeyMatched,
    'authStarted':authStarted, 'snapshotReceived':snapshotReceived,
    'fullFrameReceived':fullFrameReceived,'generation':generation,
    'lateEventsIgnored':lateEventsIgnored,'errorCode':errorCode,
    'frameCount':frameCount,'deltaFrames':deltaFrames,'lastSeq':lastSeq,'paneCount':paneCount,
    'connectionCount':connectionCount,'bufferHighWaterBytes':bufferHighWaterBytes,
  };
}

class RemoteSnapshot {
  const RemoteSnapshot(this.generation, this.session, this.paneId, this.ansi);
  final int generation;
  final String session, paneId, ansi;
}

/// Only identities supplied by the reviewed named session's snapshot.
class RemotePane {
  const RemotePane(this.paneId, this.terminalId, {this.label,this.agent,this.agentStatus='unknown',this.workspace,this.tab});
  final String paneId, terminalId, agentStatus;
  final String? label, agent, workspace, tab;

  String get statusLabel => switch (agentStatus) {
    'working' => '工作中', 'blocked' => '受阻', 'idle' => '空闲', 'done' => '已完成', _ => '状态未知',
  };
}
class RemoteDashboard {
  const RemoteDashboard(this.generation, this.session, this.panes);
  final int generation;
  final String session;
  final List<RemotePane> panes;
}
/// A resumed view is bound to both fields from its original snapshot.
void requireOriginalObservationTarget(RemotePane original,RemoteDashboard fresh) {
  final matches = fresh.panes.where((p) => p.paneId == original.paneId && p.terminalId == original.terminalId);
  if (matches.length != 1) throw const RemoteFailure('resume_target_changed');
}
class RemoteFrame {
  const RemoteFrame(this.seq, this.full, this.ansi,{this.observationEpoch=0});
  final int seq;
  final int observationEpoch;
  final bool full;
  final String ansi;
}
typedef DashboardConsumer = void Function(RemoteDashboard dashboard);
// Awaited consumption provides backpressure: no unbounded UI frame queue.
typedef FrameConsumer = FutureOr<void> Function(int generation, String paneId, RemoteFrame frame);

typedef RemoteProgress = void Function(int generation, String phase);
typedef SocketConnector = Future<SSHSocket> Function(String host, int port);

/// Shared by all views, including system TCP; an interrupted pending dial keeps
/// its slot until the late socket has been retired.
class RemoteConnectionBudget {
  RemoteConnectionBudget({this.limit=8});
  final int limit;
  int _inUse = 0;
  int get inUse => _inUse;
  bool acquire() { if (_inUse >= limit) return false; _inUse++; return true; }
  void release() { assert(_inUse > 0); _inUse--; }
}
final _sharedConnectionBudget = RemoteConnectionBudget();

/// Pinned dartssh2 4.1 trace messages are consumed, never logged. A local
/// channel destroy completes `done` before the peer CLOSE removes the channel
/// from SSHClient's internal table; only the inbound CLOSE is retirement.
/// Per SSH the confirmed-active set and unsettled-open count are independently
/// bounded to 8 each; a confirmed open can temporarily be counted in both.
class ChannelRetirementTracker {
  ChannelRetirementTracker(this.socketText,{required this.onOverflow});
  final String socketText;
  final void Function() onOverflow;
  final Set<int> _active = {};
  int _pending = 0,_confirmations = 0;
  Completer<void>? _change,_pendingIdle;
  bool _overflowed = false;
  int get activeCount => _active.length;
  int get pendingCount => _pending;
  void startOpen() {
    if (_pending >= 8 || _active.length >= 8 || _overflowed) {
      if (!_overflowed) { _overflowed = true; onOverflow(); }
      throw const RemoteFailure('channel_capacity');
    }
    _pending++;
  }
  void verifyOpen() {
    if (_confirmations == 0 && !_overflowed) { _overflowed = true; onOverflow(); }
  }
  void finishOpen({required bool succeeded}) {
    assert(_pending > 0);
    if (succeeded && _confirmations == 0) {
      verifyOpen();
    } else if (_confirmations > 0) { _confirmations--; }
    _pending--; _notify();
  }
  void trace(String message) {
    final prefix = '<- $socketText: ';
    if (!message.startsWith(prefix)) return;
    final event = message.substring(prefix.length);
    final open = RegExp(r'^SSH_Message_Channel_Confirmation\(recipientChannel: ([0-9]+), senderChannel: [0-9]+, initialWindowSize: [0-9]+, maximumPacketSize: [0-9]+\)$').firstMatch(event);
    if (open != null) {
      final id = int.tryParse(open.group(1)!);
      if (id == null || id > 65535 || _active.contains(id)) return;
      if (_active.length >= 8 || _confirmations >= _pending) {
        if (!_overflowed) { _overflowed = true; onOverflow(); } return;
      }
      _active.add(id); _confirmations++; _notify(); return;
    }
    final close = RegExp(r'^SSH_Message_Channel_Close\(recipientChannel: ([0-9]+)\)$').firstMatch(event);
    if (close == null) return;
    final id = int.tryParse(close.group(1)!);
    if (id != null) { _active.remove(id); _notify(); }
  }
  Future<void> waitIdle() => waitOnly(null);
  Future<void> waitOnly(int? allowedId) async {
    while (_pending != 0 || _active.any((id) => id != allowedId)) {
      await (_change ??= Completer<void>()).future;
    }
  }
  Future<void> waitPending() => _pending == 0 ? Future<void>.value() : (_pendingIdle ??= Completer<void>()).future;
  void _notify() {
    if (_pending == 0) { final pending = _pendingIdle; _pendingIdle = null; if (pending != null && !pending.isCompleted) pending.complete(); }
    final change = _change; _change = null; if (change != null && !change.isCompleted) change.complete();
  }
}

class _Attempt {
  _Attempt(this.generation, this.evidence);
  final int generation;
  final RemoteEvidence evidence;
  final cancelled = Completer<void>();
  RemoteFailure? failure;
  void Function(RemoteFailure)? interruptWait;
  void Function(RemoteFailure)? interruptInput;
  bool closed = false;
  Future<void>? closing;
  SSHSocket? socket;
  SSHClient? client;
  Future<void>? clientClosing;
  SSHForwardChannel? forward;
  SSHForwardChannel? inputForward;
  SSHSession? observe;
  StreamSubscription<Uint8List>? stderr;
  final selection = Completer<RemotePane>();
  RemoteDashboard? dashboard;
  RemoteConfig? config;
  RemoteInputCapability? inputCapability;
  RemoteInputTarget? inputTarget;
  bool inputBusy = false;
  bool observationPaused = false;
  int observationEpoch = 0;
  Completer<void>? resumeObservation;
  void Function(RemoteFailure)? interruptObservation;
  ChannelRetirementTracker? channels;
  bool lateChannelDestroyFailed = false;
}

/// Defaults to read-only. Writes require the separate guarded test extension;
/// stock herdr 0.9.5 never gains input through a pane-ID-only fallback.
class RemoteReadOnlyAdapter {
  RemoteReadOnlyAdapter({SocketConnector? connector, this.inputJournal,RemoteConnectionBudget? connectionBudget}) : _budget = connectionBudget ?? _sharedConnectionBudget, _connector = connector ??
    ((host,port) => SSHSocket.connect(host,port,timeout:const Duration(seconds:8)));
  final SocketConnector _connector;
  final RemoteConnectionBudget _budget;
  final RemoteInputJournal? inputJournal;
  int generation = 0, _connectionCount = 0;
  _Attempt? _attempt;
  bool _activeRead = false, _dialPending = false;
  RemoteEvidence evidence = RemoteEvidence();
  RemoteInputTarget? _unknownInputTarget;
  RemoteInputPending? _pendingInput;
  bool _journalReady = false;
  RemoteInputPending? get pendingInput => _pendingInput;
  RemoteInputTarget? get inputTarget => _attempt?.inputTarget;
  RemoteInputCapability? get inputCapability => _attempt?.inputCapability;
  RemoteDashboard? get currentDashboard => _attempt?.dashboard;

  bool _valid(_Attempt a) => identical(a,_attempt) && a.generation == generation && !a.closed;
  void _check(_Attempt a) {
    if (!_valid(a)) { a.evidence.lateEventsIgnored++; throw const RemoteFailure('cancelled'); }
  }
  void _fail(_Attempt a, RemoteFailure failure) {
    a.failure ??= failure;
    a.interruptWait?.call(a.failure!);
    a.interruptInput?.call(a.failure!);
  }
  Future<T> _wait<T>(_Attempt a, Future<T> future, {void Function(T)? disposeLate, void Function(bool,bool)? onSettled,
      bool timed = true, bool input = false, bool observation = false,Duration timeout=const Duration(seconds:10)}) async {
    // One removable waiter, rather than accumulating cancellation Future.any
    // listeners on every frame of a long-running observe.
    final completion = Completer<T>();
    void interrupt(RemoteFailure failure) {
      if (!completion.isCompleted) completion.completeError(failure);
    }
    if (input) { a.interruptInput = interrupt; } else { a.interruptWait = interrupt; }
    if (observation) a.interruptObservation = interrupt;
    unawaited(future.then<void>((value) {
      final wasLate = !_valid(a) || completion.isCompleted;
      try {
        if (wasLate) {
          disposeLate?.call(value); a.evidence.lateEventsIgnored++;
          interrupt(const RemoteFailure('cancelled'));
        } else { completion.complete(value); }
      } finally { onSettled?.call(true,wasLate); }
    },onError:(Object error,StackTrace stack) {
      try { if (!completion.isCompleted) completion.completeError(error,stack); }
      finally { onSettled?.call(false,true); }
    }));
    if (!_valid(a)) interrupt(const RemoteFailure('cancelled'));
    if (a.failure != null) interrupt(a.failure!);
    final timer = timed ? Timer(timeout,() => interrupt(const RemoteFailure('timeout'))) : null;
    try {
      return await completion.future;
    } finally {
      timer?.cancel();
      if (identical(a.interruptObservation,interrupt)) a.interruptObservation = null;
      if (input) {
        if (identical(a.interruptInput,interrupt)) a.interruptInput = null;
      } else if (identical(a.interruptWait,interrupt)) { a.interruptWait = null; }
    }
  }
  Future<T> _openChannel<T>(_Attempt a,Future<T> Function() open,void Function(T) destroy,
      {bool input=false,bool observation=false}) async {
    final tracker = a.channels;
    if (tracker == null) throw const RemoteFailure('connection_failed');
    final epoch = a.observationEpoch;
    tracker.startOpen();
    var delivered = false;
    try {
      final value = await _wait(a,Future<T>.sync(open),input:input,observation:observation,
        onSettled:(success,wasLate) {
          if (success && !wasLate) { delivered = true; return; }
          tracker.finishOpen(succeeded:success);
          if (!success && _valid(a) && !a.observationPaused) _fail(a,const RemoteFailure('channel_open_failed'));
        },disposeLate:(value) {
        try { destroy(value); } catch (_) { a.lateChannelDestroyFailed = true; }
      });
      tracker.verifyOpen();
      if (a.failure != null || !_valid(a) || (observation && (a.observationPaused || a.observationEpoch != epoch))) {
        try { destroy(value); } catch (_) { a.lateChannelDestroyFailed = true; }
        throw a.failure ?? (!_valid(a) ? const RemoteFailure('cancelled') : const RemoteFailure('observation_paused'));
      }
      return value;
    } finally { if (delivered) tracker.finishOpen(succeeded:true); }
  }
  Future<void> _close(_Attempt a) => a.closing ??= _closeResources(a);
  Future<void> _closeResources(_Attempt a) async {
    a.closed = true;
    a.interruptInput?.call(const RemoteFailure('cancelled'));
    // Destroy owned channels synchronously; SSHSession.close discards a Future
    // in dartssh2 4.1.0. Let the client finish before destroying its socket.
    a.observe?.channel.destroy(); a.forward?.destroy(); a.inputForward?.destroy();
    try { await a.stderr?.cancel(); } catch (_) { /* discarded remote stream */ }
    try {
      final closing = a.client?.close(); a.clientClosing = closing;
      await closing?.timeout(const Duration(seconds:2));
    } catch (_) { /* socket cleanup below; slot still waits for original future */ }
    finally { a.socket?.destroy(); }
  }
  Future<void> cancel() async {
    generation++;
    final a = _attempt;
    if (a == null) return;
    a.evidence.generation = generation;
    if (!a.cancelled.isCompleted) a.cancelled.complete();
    a.interruptWait?.call(const RemoteFailure('cancelled'));
    a.interruptInput?.call(const RemoteFailure('cancelled'));
    await _close(a);
  }

  /// Revoke input immediately and retire only the observing channel. The SSH
  /// transport stays owned by this attempt until explicit cancel or failure.
  bool pauseObservation() {
    final a = _attempt;
    if (a == null || !_valid(a)) return false;
    if (a.observationPaused) return true;
    a.observationPaused = true; a.observationEpoch++;
    a.evidence.fullFrameReceived = false; a.inputTarget = null;
    a.interruptInput?.call(const RemoteFailure('cancelled'));
    a.inputForward?.destroy();
    a.interruptObservation?.call(const RemoteFailure('observation_paused'));
    a.observe?.channel.destroy();
    return true;
  }

  /// An explicit user action only. A fresh target snapshot and first full are
  /// required before a new input capability can be used.
  bool resumeObservation() {
    final a = _attempt;
    if (a == null || !_valid(a) || !a.observationPaused) return false;
    a.observationPaused = false;
    final signal = a.resumeObservation; a.resumeObservation = null;
    if (signal != null && !signal.isCompleted) signal.complete();
    return true;
  }

  Future<RemoteSnapshot> read(RemoteConfig config, {RemoteProgress? onProgress}) =>
    _run(config,onProgress:onProgress);

  /// Keeps the same authenticated connection open. Explicit selectPane is
  /// required after the dashboard; cancellation/EOF ends this attempt forever.
  Future<RemoteSnapshot> observe(RemoteConfig config, {required DashboardConsumer onDashboard,
      required FrameConsumer onFrame, RemoteProgress? onProgress}) =>
    _run(config,onProgress:onProgress,onDashboard:onDashboard,onFrame:onFrame);

  void selectPane(int expectedGeneration, String paneId) {
    final a = _attempt;
    if (a == null || !_valid(a) || a.observationPaused || expectedGeneration != a.generation || a.selection.isCompleted) {
      throw const RemoteFailure('stale_selection');
    }
    final matches = a.dashboard?.panes.where((p) => p.paneId == paneId).toList();
    if (matches == null || matches.length != 1) throw const RemoteFailure('pane_missing');
    a.selection.complete(matches.single);
  }

  String _requestId() {
    final random = Random.secure();
    return List.generate(16, (_) => random.nextInt(256).toRadixString(16).padLeft(2,'0')).join();
  }

  bool _canWrite(_Attempt a, RemoteInputTarget target) => _valid(a) && a.failure == null &&
    identical(target,a.inputTarget) && identical(target.connection,a) &&
    a.inputCapability != null && a.evidence.hostKeyMatched && a.evidence.fullFrameReceived;

  /// A new full of the same endpoint plus an explicit human action is required.
  Future<bool> acknowledgeInputUnknown(RemoteInputTarget target) async {
    final a = _attempt, previous = _unknownInputTarget;
    if (a == null || previous == null || !_canWrite(a,target) || a.inputBusy ||
        !_journalReady || inputJournal == null ||
        identical(target.connection,previous.connection) || !target.sameEndpoint(previous)) return false;
    if (_pendingInput == null) { _unknownInputTarget = null; return true; }
    final pending = _pendingInput!;
    a.inputBusy = true;
    try {
      await inputJournal!.clear(pending.raw).timeout(const Duration(seconds:10));
      if (!identical(pending,_pendingInput)) return false;
      _pendingInput = null; _unknownInputTarget = null; return true;
    } catch (_) { return false; }
    finally { a.inputBusy = false; }
  }

  /// Exactly one raw-byte request, on the observing attempt's authenticated SSH
  /// transport and reviewed socket. No flush, write retry, PTY or control mode.
  Future<RemoteInputResult> sendInput(RemoteInputTarget target, Uint8List bytes,
      {required bool Function() stillCurrent}) {
    final result = Completer<RemoteInputResult>();
    final owned = _attempt;
    // Forward-channel pipe futures can fail outside the awaited call. Contain
    // those errors here as well as the observe zone; never log raw transport data.
    runZonedGuarded(() async {
      try { result.complete(await _sendInput(target,bytes,stillCurrent:stillCurrent)); }
      catch (_) { if (!result.isCompleted) result.complete(const RemoteInputResult.unknown()); }
    },(error,stack) {
      if (owned != null) _fail(owned,const RemoteFailure('async_input_transport_failed'));
      else if (!result.isCompleted) result.complete(const RemoteInputResult.rejected('input_not_ready'));
    });
    return result.future;
  }

  Future<RemoteInputResult> _sendInput(RemoteInputTarget target, Uint8List bytes,
      {required bool Function() stillCurrent}) async {
    bytes = Uint8List.fromList(bytes);
    final a = _attempt;
    if (a == null || !_canWrite(a,target) || _unknownInputTarget != null || a.inputBusy ||
        !_journalReady || inputJournal == null || _pendingInput != null ||
        !stillCurrent() || bytes.isEmpty || bytes.length > a.inputCapability!.maxBytes) {
      return const RemoteInputResult.rejected('input_not_ready');
    }
    a.inputBusy = true;
    var submitted = false;
    RemoteInputPending? pending;
    SSHForwardChannel? channel;
    RemoteInputResult result = const RemoteInputResult.rejected('input_cancelled_before_write');
    try {
      final opened = await _openChannel<SSHForwardChannel>(a,() => a.client!.forwardLocalUnix(a.config!.socketPath),
        (c) => c.destroy(),input:true);
      channel = opened;
      a.inputForward = opened;
      if (!_canWrite(a,target) || _unknownInputTarget != null || !stillCurrent()) return result;
      final id = _requestId();
      final request = utf8.encode('${jsonEncode({'id':id,'method':'pocket.input.send','params':{
        'pane_id':target.paneId,'expected_terminal_id':target.terminalId,'bytes_base64':base64Encode(bytes),
      }})}\n');
      pending = RemoteInputPending.create(id,target);
      // Before any write, persist an exact public target + request marker. A
      // crash/cancel during preparation leaves the slot locked, never replayed.
      _pendingInput = pending;
      await _wait(a,inputJournal!.prepare(pending.raw),input:true);
      if (!_canWrite(a,target) || !stillCurrent()) {
        await inputJournal!.clear(pending.raw).timeout(const Duration(seconds:10));
        _pendingInput = null;
        return result;
      }
      // Set before sink.add: even an error here cannot prove remote rejection.
      submitted = true;
      opened.sink.add(request);
      final line = await _wait(a,boundedLines(opened.stream,maxTotal:16384).first,input:true);
      result = parseInputResponse(_decodeObject(line),id,target,bytes.length);
      if (result.disposition != RemoteInputDisposition.unknown) {
        // Only a matching accepted ACK or proven pre-queue rejection clears it.
        try {
          await inputJournal!.clear(pending.raw).timeout(const Duration(seconds:10));
          _pendingInput = null;
        } catch (_) {
          // The remote result is known; a local persistence failure must not
          // erase that fact. Keep the durable lock until explicit recovery.
          result = RemoteInputResult.journalLocked(result.disposition,receipt:result.receipt);
        }
      }
    } catch (_) {
      result = submitted ? const RemoteInputResult.unknown()
        : RemoteInputResult.rejected(pending == null ? 'input_cancelled_before_write' : 'input_journal_unavailable');
      if (pending != null && !submitted) {
        _journalReady = false; a.inputCapability = null;
      }
    } finally {
      channel?.destroy();
      if (identical(a.inputForward,channel)) a.inputForward = null;
      if (channel != null && _valid(a) && !a.observationPaused && a.channels != null) {
        try { await _wait(a,a.channels!.waitOnly(a.observe?.channel.channelId),input:true,timeout:const Duration(seconds:2)); }
        catch (_) { if (_valid(a) && !a.observationPaused) _fail(a,const RemoteFailure('channel_cleanup_timeout')); }
      }
      a.inputBusy = false;
    }
    if (_pendingInput != null) _unknownInputTarget = target;
    return result;
  }

  Future<RemoteSnapshot> _run(RemoteConfig config, {RemoteProgress? onProgress,
      DashboardConsumer? onDashboard, FrameConsumer? onFrame}) {
    final result = Completer<RemoteSnapshot>();
    _Attempt? owned;
    // An SSH transport can report an error from an internally detached Future.
    // Contain it within this attempt, never expose raw remote error text, and
    // make the same adapter fail safely in both GUI and command-line callers.
    runZonedGuarded(() async {
      try {
        result.complete(await _read(config,onProgress:onProgress,onDashboard:onDashboard,onFrame:onFrame,onAttempt:(a) { owned = a; }));
      } catch (error,stack) { result.completeError(error,stack); }
    }, (error,stack) {
      final a = owned;
      final failure = RemoteFailure(error is SSHStateError ? 'async_ssh_state_error' :
        error is StateError ? switch (error.message) {
          'StreamSink is bound to a stream' => 'async_sink_bound',
          'Stream has already been listened to.' => 'async_stream_listened',
          'Cannot add new events after calling close' || 'Cannot add event after closing' => 'async_sink_closed',
          _ => 'async_state_error',
        } : 'async_transport_failed');
      if (a == null) {
        if (!result.isCompleted) result.completeError(failure,stack);
      } else if (!result.isCompleted) {
        a.evidence.errorCode ??= failure.code;
        _fail(a,failure);
      }
    });
    return result.future;
  }

  Future<RemoteSnapshot> _read(RemoteConfig config, {RemoteProgress? onProgress,
      DashboardConsumer? onDashboard, FrameConsumer? onFrame,
      required void Function(_Attempt) onAttempt}) async {
    if (_activeRead || _dialPending) throw const RemoteFailure('connection_busy');
    if (!_budget.acquire()) throw const RemoteFailure('connection_capacity');
    _activeRead = true;
    try { if (_attempt != null) await cancel(); }
    catch (_) { _activeRead = false; _budget.release(); rethrow; }
    final a = _Attempt(++generation,RemoteEvidence());
    a.config = config;
    onAttempt(a);
    _attempt = a; final e = a.evidence; evidence = e; e.generation = generation; e.connectionCount = ++_connectionCount;
    RemoteSnapshot? completed;
    Future<SSHSocket>? ownedDial;
    var lateDestroyFailed = false;
    void phase(String name) { _check(a); onProgress?.call(a.generation,name); _check(a); }
    try {
      phase('connecting');
      List<SSHIdentity> identities;
      try {
        final device = config.deviceIdentity;
        identities = device != null ? [SSHIdentity.custom(type:device.type,publicKey:device.toPublicKey(),shouldProbe:true,
          signer:(payload) async {
            _check(a);
            if (!e.hostKeyChecked || !e.hostKeyMatched) throw const RemoteFailure('host_key_mismatch');
            try {
              final signature = await device.sign(payload);
              _check(a); return signature;
            } on RemoteFailure catch (failure) { e.errorCode = failure.code; rethrow; }
          })] : SSHKeyPair.fromPem(config.privateKeyPem);
        if (identities.length != 1 || identities.single.type != 'ssh-ed25519') throw const RemoteFailure('invalid_private_key');
      } catch (_) { throw const RemoteFailure('invalid_private_key'); }
      _dialPending = true;
      final pending = Future<SSHSocket>.sync(() => _connector(config.host,config.port))
        .whenComplete(() { _dialPending = false; });
      ownedDial = pending;
      final socket = await _wait(a,pending,disposeLate:(s) {
        try { s.destroy(); } catch (_) { lateDestroyFailed = true; }
      });
      a.socket = socket;
      final tracker = ChannelRetirementTracker(socket.toString(),onOverflow:() => _fail(a,const RemoteFailure('channel_capacity')));
      a.channels = tracker;
      final client = SSHClient(socket,username:config.username,identities:identities,
        keepAliveInterval:null,handshakeTimeout:const Duration(seconds:8),authTimeout:const Duration(seconds:8),
        printTrace:tracker.trace,
        onVerifyHostKey:(type,fingerprint) {
          if (!_valid(a)) return false;
          e.hostKeyChecked = true;
          e.hostKeyMatched = type == 'ssh-ed25519' && utf8.decode(fingerprint,allowMalformed:true) == config.expectedFingerprint;
          if (!e.hostKeyMatched) e.errorCode = 'host_key_mismatch';
          return e.hostKeyMatched;
        },
        printDebug:(message) { // Read only a pinned-library lifecycle marker; never retain/debug-log raw messages.
          if (_valid(a) && message == 'SSHClient._startAuthentication') e.authStarted = true;
        });
      a.client = client;
      // Consume closure errors in addition to authenticated; no unhandled socket errors escape to logs.
      unawaited(client.done.then<void>((_) {},onError:(Object _,StackTrace __) {}));
      await _wait(a,client.authenticated);
      if (!e.hostKeyChecked || !e.hostKeyMatched) throw const RemoteFailure('host_key_mismatch');
      Future<void> waitRetired() => _wait(a,tracker.waitIdle(),timeout:const Duration(seconds:2));
      Future<RemoteDashboard> snapshot({bool observation=false}) async {
        final channel = await _openChannel<SSHForwardChannel>(a,() => client.forwardLocalUnix(config.socketPath),
          (c) => c.destroy(),observation:observation);
        a.forward = channel;
        try {
          final id = _requestId();
          channel.sink.add(utf8.encode('${jsonEncode({'id':id,'method':'session.snapshot','params':<String,Object?>{}})}\n'));
          final line = await _wait(a,boundedLines(channel.stream,maxTotal:1048576).first,observation:observation);
          final rpc = _decodeObject(line);
          if (rpc['id'] != id || rpc['error'] != null || rpc['ok'] == false || rpc['result'] is! Map) {
            throw const RemoteFailure('snapshot_rejected');
          }
          return parseSnapshotDashboard(config,Map<String,dynamic>.from(rpc['result'] as Map),a.generation);
        } finally { channel.destroy(); if (identical(a.forward,channel)) a.forward = null; }
      }
      phase('snapshot');
      final dashboard = await snapshot();
      await waitRetired();
      e.snapshotReceived = true; a.dashboard = dashboard; e.paneCount = dashboard.panes.length;
      if (onDashboard != null) {
        // Capability discovery is side-effect-free; stock 0.9.5 replies with an
        // error and remains read-only. This is never inferred from version alone.
        final capabilityChannel = await _openChannel<SSHForwardChannel>(a,() => client.forwardLocalUnix(config.socketPath),
          (c) => c.destroy());
        a.forward = capabilityChannel;
        final capabilityId = _requestId();
        capabilityChannel.sink.add(utf8.encode('${jsonEncode({'id':capabilityId,
          'method':'pocket.input.capabilities','params':<String,Object?>{}})}\n'));
        final capabilityLine = await _wait(a,boundedLines(capabilityChannel.stream,maxTotal:16384).first);
        final response = _decodeObject(capabilityLine);
        if (response['id'] != capabilityId) throw const RemoteFailure('invalid_response');
        if (response['error'] == null && response['ok'] != false) {
          a.inputCapability = RemoteInputCapability.parse(response['result']);
        }
        capabilityChannel.destroy(); a.forward = null;
        await waitRetired();
        _journalReady = false;
        if (a.inputCapability != null) {
          try {
            if (inputJournal == null) throw const RemoteFailure('input_journal_unavailable');
            final pending = await _wait(a,inputJournal!.read());
            _pendingInput = pending == null ? null : RemoteInputPending.parse(pending);
            if (_pendingInput != null) _unknownInputTarget = _pendingInput!.target;
            _journalReady = true;
          } catch (_) { a.inputCapability = null; }
        }
      }
      phase('snapshot_received');
      RemotePane selected;
      if (onDashboard == null) {
        final matches = dashboard.panes.where((p) => p.paneId == config.paneId).toList();
        if (matches.length != 1) throw const RemoteFailure('pane_missing');
        selected = matches.single;
      } else {
        onDashboard(dashboard); _check(a);
        // User selection has no timeout and owns no additional channel/queue.
        selected = await _wait(a,a.selection.future,timed:false);
      }
      _check(a);
      final route = socket is RoutedSSHSocket ? socket.actualRoute : 'system';
      var needsSnapshot = a.observationEpoch != 0;
      while (true) {
        while (a.observationPaused) {
          needsSnapshot = true;
          final signal = a.resumeObservation ??= Completer<void>();
          await _wait(a,signal.future,timed:false);
          if (identical(a.resumeObservation,signal)) a.resumeObservation = null;
        }
        final epoch = a.observationEpoch;
        void checkObservation() {
          _check(a);
          if (a.observationPaused || a.observationEpoch != epoch) throw const RemoteFailure('observation_paused');
        }
        SSHSession? observe;
        StreamIterator<RemoteFrame>? frames;
        StreamSubscription<Uint8List>? stderr;
        try {
          if (needsSnapshot) {
            final fresh = await snapshot(observation:true); checkObservation();
            await waitRetired(); checkObservation();
            requireOriginalObservationTarget(selected,fresh);
            a.dashboard = fresh;
          }
          checkObservation();
          a.inputTarget = RemoteInputTarget(connection:a,generation:a.generation,
            host:config.host,port:config.port,username:config.username,hostFingerprint:config.expectedFingerprint,
            session:config.session,socketPath:config.socketPath,paneId:selected.paneId,terminalId:selected.terminalId,route:route);
          e.fullFrameReceived = false;
          observe = await _openChannel<SSHSession>(a,() => client.execute(config.observeCommand(selected.terminalId)),
            (s) => s.channel.destroy(),observation:true);
          checkObservation(); a.observe = observe;
          final current = observe;
          final budget = ObserveByteBudget(continuous:onDashboard != null);
          stderr = current.stderr.listen((chunk) {
            if (!_valid(a) || a.observationPaused || a.observationEpoch != epoch) return;
            try { budget.add(chunk.length,stderr:true); } on RemoteFailure catch (error) {
              e.errorCode = error.code; _fail(a,error); current.channel.destroy();
            }
          },onError:(Object _) {});
          a.stderr = stderr;
          phase('observing'); checkObservation();
          frames = StreamIterator<RemoteFrame>(validatedFrames(
            current.stdout.map((chunk) { budget.add(chunk.length); return chunk; }),continuous:onDashboard != null));
          var first = true;
          while (await _wait(a,frames.moveNext(),timed:first,observation:true)) {
            checkObservation();
            if (a.failure != null) throw a.failure!;
            final frame = frames.current;
            e.frameCount++; if (!frame.full) e.deltaFrames++;
            e.lastSeq = frame.seq; e.fullFrameReceived = true;
            final byteLength = utf8.encode(frame.ansi).length;
            if (byteLength > e.bufferHighWaterBytes) e.bufferHighWaterBytes = byteLength;
            if (first) phase('full_received');
            first = false;
            completed = RemoteSnapshot(a.generation,config.session,selected.paneId,frame.ansi);
            if (onFrame != null) await _wait(a,Future<void>.sync(() => onFrame(a.generation,selected.paneId,
              RemoteFrame(frame.seq,frame.full,frame.ansi,observationEpoch:epoch))),timed:false,observation:true);
            checkObservation();
            if (onDashboard == null) break;
          }
          checkObservation();
          if (onDashboard != null || completed == null) throw const RemoteFailure('observe_ended');
          break;
        } on RemoteFailure catch (error) {
          if (error.code != 'observation_paused' && a.observationEpoch == epoch) rethrow;
          _check(a); needsSnapshot = true;
        } finally {
          a.inputTarget = null;
          if (onDashboard != null) e.fullFrameReceived = false;
          observe?.channel.destroy();
          if (identical(a.observe,observe)) a.observe = null;
          try { await stderr?.cancel(); } catch (_) { /* retired observer */ }
          if (identical(a.stderr,stderr)) a.stderr = null;
          try { await frames?.cancel().timeout(const Duration(seconds:2)); } catch (_) { /* retired observer */ }
        }
        // Local destroy alone leaves dartssh2's channel table occupied until
        // peer CLOSE. Never re-open or keep an indefinitely hidden SSH if the
        // prior observer, input channel or late open does not retire in time.
        await waitRetired();
      }

    } catch (error) {
      final failure = error is RemoteFailure ? error : RemoteFailure(e.errorCode ??
        (error is SSHAuthFailError ? 'authentication_failed' : error is SSHAuthAbortError && e.hostKeyMatched ? 'authentication_aborted' : 'connection_failed'));
      e.errorCode ??= failure.code;
      throw failure;
    } finally {
      var closed = false;
      try { await _close(a); closed = true; }
      finally {
        _activeRead = false;
        final pending = ownedDial;
        if (!closed) {
          // Failed teardown does not prove that this slot is reusable.
        } else {
          // Wait for every underlying channel open and its late disposer, as
          // well as the dial, even though cancellation already returned.
          final dial = pending == null ? Future<void>.value() :
            pending.then<void>((_) {},onError:(Object _,StackTrace __) {});
          final channels = a.channels?.waitPending() ?? Future<void>.value();
          final closing = a.clientClosing?.then<void>((_) {},onError:(Object _,StackTrace __) {}) ?? Future<void>.value();
          unawaited(Future.wait<void>([dial,channels,closing]).then<void>((_) {
            if (!lateDestroyFailed && !a.lateChannelDestroyFailed) _budget.release();
          }));
        }
      }
    }
    if (a.generation != generation || !identical(a,_attempt)) {
      e.errorCode = 'cancelled'; e.lateEventsIgnored++; throw const RemoteFailure('cancelled');
    }
    if (a.failure != null) throw a.failure!;
    return completed;
  }
}

Map<String,dynamic> _decodeObject(String line) {
  try { final value = jsonDecode(line); if (value is Map<String,dynamic>) return value; }
  catch (_) { /* safe stable error, never raw output */ }
  throw const RemoteFailure('invalid_response');
}

String? _paneCaption(dynamic value) {
  if (value is! String) return null;
  final text = value.trim();
  if (text.isEmpty || text.runes.length > 64 ||
      RegExp(r'[\x00-\x1f\x7f-\x9f\u061c\u200e\u200f\u2028-\u202e\u2066-\u2069]').hasMatch(text)) return null;
  return text;
}

RemoteDashboard parseSnapshotDashboard(RemoteConfig config, Map<String,dynamic> result, int generation) {
  // Pinned v0.9.5 has no session echo; enforce the reviewed socket/exec root.
  config.configRoot;
  final snapshot = result['snapshot'];
  if (result['type'] != 'session_snapshot' || snapshot is! Map ||
      snapshot['version'] != '0.9.5' || snapshot['protocol'] != 22) throw const RemoteFailure('unsupported_protocol');
  final panes = snapshot['panes'];
  if (panes is! List || panes.length > 256) throw const RemoteFailure('invalid_snapshot');
  final ids = <String>{}, terminals = <String>{};
  final parsed = <RemotePane>[];
  for (final pane in panes) {
    if (pane is! Map || pane['pane_id'] is! String || pane['terminal_id'] is! String) {
      throw const RemoteFailure('invalid_snapshot');
    }
    final id = pane['pane_id'] as String, terminal = pane['terminal_id'] as String;
    if (!RegExp(r'^[A-Za-z0-9:_-]{1,128}$').hasMatch(id) || !ids.add(id)) {
      throw const RemoteFailure('invalid_snapshot');
    }
    if (!RegExp(r'^term_[0-9a-f]{1,123}$').hasMatch(terminal) || !terminals.add(terminal)) {
      throw const RemoteFailure('invalid_terminal_id');
    }
    final status = pane['agent_status'];
    parsed.add(RemotePane(id,terminal,label:_paneCaption(pane['label']),
      agent:_paneCaption(pane['display_agent']) ?? _paneCaption(pane['agent']),
      agentStatus:const {'idle','working','blocked','done'}.contains(status) ? status as String : 'unknown',
      workspace:_paneCaption(pane['workspace_id']),tab:_paneCaption(pane['tab_id'])));
  }
  return RemoteDashboard(generation,config.session,List.unmodifiable(parsed));
}

String validateSnapshotTarget(RemoteConfig config, Map<String,dynamic> result) {
  final panes = parseSnapshotDashboard(config,result,0).panes.where((p) => p.paneId == config.paneId).toList();
  if (panes.length != 1) throw const RemoteFailure('pane_missing');
  return panes.single.terminalId;
}

Stream<String> boundedLines(Stream<Uint8List> source, {int? maxTotal = 2097152}) async* {
  var total = 0;
  var line = BytesBuilder(copy:false);
  await for (final chunk in source) {
    total += chunk.length;
    if (maxTotal != null && total > maxTotal) throw const RemoteFailure('output_limit');
    var offset = 0;
    while (offset < chunk.length) {
      final newline = chunk.indexOf(10,offset);
      final end = newline < 0 ? chunk.length : newline;
      if (line.length + end - offset > 1048576) throw const RemoteFailure('output_limit');
      line.add(Uint8List.sublistView(chunk,offset,end));
      if (newline < 0) break;
      try { yield utf8.decode(line.takeBytes()); }
      on FormatException { throw const RemoteFailure('invalid_response'); }
      offset = newline + 1;
    }
  }
  if (line.length != 0) throw const RemoteFailure('truncated_response');
}

/// One bounded record at a time; no dropping deltas, recovery or retries.
Stream<RemoteFrame> validatedFrames(Stream<Uint8List> source, {bool continuous = true}) async* {
  int? previous;
  await for (final line in boundedLines(source,maxTotal:continuous ? null : 2097152)) {
    final frame = _decodeObject(line);
    final first = previous == null;
    final code = first ? 'invalid_first_frame' : 'invalid_frame';
    final seq = frame['seq'];
    if (frame['type'] != 'terminal.frame' || frame['encoding'] != 'ansi' || frame['width'] != 80 ||
        frame['height'] != 24 || seq is! int || seq < 0 || seq > 9007199254740991 ||
        frame['full'] is! bool || (first && frame['full'] != true) || frame['bytes'] is! String) {
      throw RemoteFailure(code);
    }
    if (previous != null && seq != previous + 1) throw const RemoteFailure('sequence_gap');
    String ansi;
    try {
      final bytes = base64Decode(frame['bytes'] as String);
      if (bytes.length > 65536) throw const RemoteFailure('output_limit');
      ansi = utf8.decode(bytes);
    } on FormatException { throw RemoteFailure(code); }
    previous = seq;
    yield RemoteFrame(seq,frame['full'] as bool,ansi);
  }
}

Future<String> firstFullFrame(Stream<Uint8List> source) async {
  await for (final frame in validatedFrames(source,continuous:false)) { return frame.ansi; }
  throw const RemoteFailure('observe_ended');
}

/// Shared stdout/stderr budget; stderr cannot evade the total read bound.
class ObserveByteBudget {
  ObserveByteBudget({this.continuous = false});
  final bool continuous;
  int total = 0, errors = 0;
  void add(int count,{bool stderr=false}) {
    total += count; if (stderr) errors += count;
    if ((!continuous && total > 2097152) || errors > 65536) throw const RemoteFailure('output_limit');
  }
}
