import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'package:dartssh2/dartssh2.dart';
import 'package:pointycastle/digests/sha256.dart';

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
    this.expectedFingerprint);
  final String host, username, expectedHostKey, privateKeyPem, socketPath, herdrPath, session, paneId, expectedFingerprint;
  final int port;
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
    final session = field('session',64), pane = field('paneId',128);
    if (session == 'default' || !RegExp(r'^[A-Za-z0-9_-]{1,64}$').hasMatch(session) ||
        !RegExp(r'^[A-Za-z0-9:_-]{1,128}$').hasMatch(pane)) throw const RemoteFailure('invalid_target');
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
  String? errorCode;
  Map<String,Object?> toReport(String testCase, bool passed) => {
    'status': passed ? 'passed' : 'failed', 'case':testCase,
    'hostKeyChecked':hostKeyChecked, 'hostKeyMatched':hostKeyMatched,
    'authStarted':authStarted, 'snapshotReceived':snapshotReceived,
    'fullFrameReceived':fullFrameReceived,'generation':generation,
    'lateEventsIgnored':lateEventsIgnored,'errorCode':errorCode,
  };
}

class RemoteSnapshot {
  const RemoteSnapshot(this.generation, this.session, this.paneId, this.ansi);
  final int generation;
  final String session, paneId, ansi;
}

typedef RemoteProgress = void Function(int generation, String phase);
typedef SocketConnector = Future<SSHSocket> Function(String host, int port);

class _Attempt {
  _Attempt(this.generation, this.evidence);
  final int generation;
  final RemoteEvidence evidence;
  final cancelled = Completer<void>();
  final failed = Completer<RemoteFailure>();
  bool closed = false;
  Future<void>? closing;
  SSHSocket? socket;
  SSHClient? client;
  SSHForwardChannel? forward;
  SSHSession? observe;
  StreamSubscription<Uint8List>? stderr;
}

/// One-shot read-only adapter; no input/PTY/resize API and no persistent storage.
class RemoteReadOnlyAdapter {
  RemoteReadOnlyAdapter({SocketConnector? connector}) : _connector = connector ??
    ((host,port) => SSHSocket.connect(host,port,timeout:const Duration(seconds:8)));
  final SocketConnector _connector;
  int generation = 0;
  _Attempt? _attempt;
  bool _activeRead = false, _dialPending = false;
  RemoteEvidence evidence = RemoteEvidence();

  bool _valid(_Attempt a) => identical(a,_attempt) && a.generation == generation && !a.closed;
  void _check(_Attempt a) {
    if (!_valid(a)) { a.evidence.lateEventsIgnored++; throw const RemoteFailure('cancelled'); }
  }
  Future<T> _wait<T>(_Attempt a, Future<T> future, {void Function(T)? disposeLate}) async {
    final guarded = future.then((value) {
      if (!_valid(a)) { disposeLate?.call(value); _check(a); }
      return value;
    });
    return Future.any<T>([guarded,a.cancelled.future.then<T>((_) => throw const RemoteFailure('cancelled')),
      a.failed.future.then<T>((failure) => throw failure)])
      .timeout(const Duration(seconds:10),onTimeout:() => throw const RemoteFailure('timeout'));
  }
  Future<void> _close(_Attempt a) => a.closing ??= _closeResources(a);
  Future<void> _closeResources(_Attempt a) async {
    a.closed = true;
    // Destroy owned channels synchronously; SSHSession.close discards a Future
    // in dartssh2 4.1.0. Let the client finish before destroying its socket.
    a.observe?.channel.destroy(); a.forward?.destroy();
    try { await a.stderr?.cancel(); } catch (_) { /* discarded remote stream */ }
    try { await a.client?.close().timeout(const Duration(seconds:2)); } catch (_) { /* socket cleanup below */ }
    finally { a.socket?.destroy(); }
  }
  Future<void> cancel() async {
    generation++;
    final a = _attempt;
    if (a == null) return;
    a.evidence.generation = generation;
    if (!a.cancelled.isCompleted) a.cancelled.complete();
    await _close(a);
  }

  Future<RemoteSnapshot> read(RemoteConfig config, {RemoteProgress? onProgress}) {
    final result = Completer<RemoteSnapshot>();
    _Attempt? owned;
    // An SSH transport can report an error from an internally detached Future.
    // Contain it within this attempt, never expose raw remote error text, and
    // make the same adapter fail safely in both GUI and command-line callers.
    runZonedGuarded(() async {
      try {
        result.complete(await _read(config,onProgress:onProgress,onAttempt:(a) { owned = a; }));
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
        if (!a.failed.isCompleted) a.failed.complete(failure);
      }
    });
    return result.future;
  }

  Future<RemoteSnapshot> _read(RemoteConfig config, {RemoteProgress? onProgress,
      required void Function(_Attempt) onAttempt}) async {
    if (_activeRead || _dialPending) throw const RemoteFailure('connection_busy');
    _activeRead = true;
    if (_attempt != null) await cancel();
    final a = _Attempt(++generation,RemoteEvidence());
    onAttempt(a);
    _attempt = a; final e = a.evidence; evidence = e; e.generation = generation;
    RemoteSnapshot? completed;
    void phase(String name) { _check(a); onProgress?.call(a.generation,name); _check(a); }
    try {
      phase('connecting');
      List<SSHKeyPair> identities;
      try {
        identities = SSHKeyPair.fromPem(config.privateKeyPem);
        if (identities.length != 1 || identities.single.type != 'ssh-ed25519') throw const RemoteFailure('invalid_private_key');
      } catch (_) { throw const RemoteFailure('invalid_private_key'); }
      _dialPending = true;
      final pending = Future<SSHSocket>.sync(() => _connector(config.host,config.port))
        .whenComplete(() { _dialPending = false; });
      final socket = await _wait(a,pending,disposeLate:(s) => s.destroy());
      a.socket = socket;
      final client = SSHClient(socket,username:config.username,identities:identities,
        keepAliveInterval:null,handshakeTimeout:const Duration(seconds:8),authTimeout:const Duration(seconds:8),
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
      phase('snapshot');
      final channel = await _wait(a,client.forwardLocalUnix(config.socketPath),disposeLate:(c) => c.destroy());
      a.forward = channel;
      final id = 'pocket-readonly-${a.generation}';
      channel.sink.add(utf8.encode('${jsonEncode({'id':id,'method':'session.snapshot','params':<String,Object?>{}})}\n'));
      // The channel upload loop writes asynchronously. Its flush() forwards
      // directly to the transport's IOSink and is not a channel write barrier.
      // The matching RPC response is the acknowledgement; do not race flush
      // against the SSH transport's other writes on the same socket.
      final rpcLine = await _wait(a,boundedLines(channel.stream,maxTotal:1048576).first);
      final rpc = _decodeObject(rpcLine);
      if (rpc['id'] != id || rpc['error'] != null || rpc['ok'] == false || rpc['result'] is! Map) {
        throw const RemoteFailure('snapshot_rejected');
      }
      e.snapshotReceived = true;
      final terminalId = validateSnapshotTarget(config,Map<String,dynamic>.from(rpc['result'] as Map));
      channel.destroy(); a.forward = null;
      phase('snapshot_received');
      final observe = await _wait(a,client.execute(config.observeCommand(terminalId)),disposeLate:(s) => s.channel.destroy());
      a.observe = observe;
      final budget = ObserveByteBudget();
      a.stderr = observe.stderr.listen((chunk) {
        try { budget.add(chunk.length,stderr:true); } on RemoteFailure catch (error) {
          e.errorCode = error.code;
          if (!a.failed.isCompleted) a.failed.complete(error);
          observe.channel.destroy();
        }
      },onError:(Object _) {});
      phase('observing');
      final result = await _wait(a,firstFullFrame(observe.stdout.map((chunk) { budget.add(chunk.length); return chunk; })));
      _check(a);
      if (a.failed.isCompleted) throw await a.failed.future;
      e.fullFrameReceived = true;
      phase('full_received');
      completed = RemoteSnapshot(a.generation,config.session,config.paneId,result);
    } catch (error) {
      final failure = error is RemoteFailure ? error : RemoteFailure(e.errorCode ??
        (error is SSHAuthFailError ? 'authentication_failed' : error is SSHAuthAbortError && e.hostKeyMatched ? 'authentication_aborted' : 'connection_failed'));
      e.errorCode ??= failure.code;
      throw failure;
    } finally { await _close(a); _activeRead = false; }
    if (a.generation != generation || !identical(a,_attempt)) {
      e.errorCode = 'cancelled'; e.lateEventsIgnored++; throw const RemoteFailure('cancelled');
    }
    if (a.failed.isCompleted) throw await a.failed.future;
    return completed;
  }
}

Map<String,dynamic> _decodeObject(String line) {
  try { final value = jsonDecode(line); if (value is Map<String,dynamic>) return value; }
  catch (_) { /* safe stable error, never raw output */ }
  throw const RemoteFailure('invalid_response');
}

String validateSnapshotTarget(RemoteConfig config, Map<String,dynamic> result) {
  // v0.9.5 does not echo session identity. Require the named socket layout and
  // derive the same XDG config root for exec; server bytes remain untrusted.
  config.configRoot;
  // ResponseResult is serde tagged; SessionSnapshot lives inside snapshot.
  // Reject flat historical test shapes instead of treating them as a server reply.
  final snapshot = result['snapshot'];
  if (result['type'] != 'session_snapshot' || snapshot is! Map ||
      snapshot['version'] != '0.9.5' || snapshot['protocol'] != 22) throw const RemoteFailure('unsupported_protocol');
  final panes = snapshot['panes'];
  if (panes is! List) throw const RemoteFailure('pane_missing');
  final matches = panes.where((p) => p is Map && p['pane_id'] == config.paneId).toList();
  if (matches.length != 1) throw const RemoteFailure('pane_missing');
  final terminalId = matches.single['terminal_id'];
  if (terminalId is! String || !RegExp(r'^term_[0-9a-f]{1,123}$').hasMatch(terminalId)) {
    throw const RemoteFailure('invalid_terminal_id');
  }
  return terminalId;
}

Stream<String> boundedLines(Stream<Uint8List> source, {int maxTotal = 2097152}) async* {
  var total = 0;
  var line = BytesBuilder(copy:false);
  await for (final chunk in source) {
    total += chunk.length;
    if (total > maxTotal) throw const RemoteFailure('output_limit');
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

Future<String> firstFullFrame(Stream<Uint8List> source) async {
  await for (final line in boundedLines(source)) {
    final frame = _decodeObject(line);
    // Pinned herdr CLI emits no ready metadata; the first record must be full.
    if (frame['type'] != 'terminal.frame' || frame['full'] != true || frame['encoding'] != 'ansi' || frame['width'] != 80 ||
        frame['height'] != 24 || frame['seq'] is! int || (frame['seq'] as int) < 0 || frame['bytes'] is! String) {
      throw const RemoteFailure('invalid_first_frame');
    }
    try {
      final bytes = base64Decode(frame['bytes'] as String);
      if (bytes.length > 1048576) throw const RemoteFailure('output_limit');
      return utf8.decode(bytes); // strict UTF-8; no synthetic replacement screen
    } on FormatException { throw const RemoteFailure('invalid_first_frame'); }
  }
  throw const RemoteFailure('observe_ended');
}

/// Shared stdout/stderr budget; stderr cannot evade the total read bound.
class ObserveByteBudget {
  int total = 0, errors = 0;
  void add(int count,{bool stderr=false}) {
    total += count; if (stderr) errors += count;
    if (total > 2097152 || errors > 65536) throw const RemoteFailure('output_limit');
  }
}
