import 'dart:async';
import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';
import 'package:dartssh2/dartssh2.dart';
import 'package:pointycastle/digests/sha256.dart';
import 'remote_failure.dart';
export 'remote_failure.dart';
import 'remote_input.dart';
import 'remote_frame_geometry.dart';
import 'network_runtime.dart' show RoutedSSHSocket;

String shellQuote(String value) => "'${value.replaceAll("'", "'\\''")}'";

class RemoteConfig {
  RemoteConfig._(this.host, this.port, this.username, this.expectedHostKey,
    this.privateKeyPem, this.socketPath, this.herdrPath, this.session, this.paneId,
    this.expectedFingerprint, [this.deviceIdentity,this.observationCols=80,this.observationRows=24,
    this.channelRetireTimeout=const Duration(seconds:2)]);
  final String host, username, expectedHostKey, privateKeyPem, socketPath, herdrPath, session, paneId, expectedFingerprint;
  final int port;
  final SSHIdentity? deviceIdentity;
  // Per-observation rendering preference; never serialized into host identity.
  final int observationCols,observationRows;
  // Budget the adapter waits for a retired channel's peer CLOSE; never
  // serialized into host identity. Slow mobile links may widen the default.
  final Duration channelRetireTimeout;
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

  RemoteConfig withObservationCanvas(int cols,int rows) {
    if (!validRemoteFrameGeometry(cols,rows)) throw const RemoteFailure('invalid_config');
    return RemoteConfig._(host,port,username,expectedHostKey,privateKeyPem,socketPath,
      herdrPath,session,paneId,expectedFingerprint,deviceIdentity,cols,rows,channelRetireTimeout);
  }

  /// Widens only the peer-CLOSE wait used when retiring channels; every
  /// reviewed identity field and the rendering canvas stay unchanged.
  RemoteConfig withChannelRetireTimeout(Duration timeout) {
    if (timeout <= Duration.zero) throw const RemoteFailure('invalid_config');
    return RemoteConfig._(host,port,username,expectedHostKey,privateKeyPem,socketPath,
      herdrPath,session,paneId,expectedFingerprint,deviceIdentity,observationCols,observationRows,timeout);
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
    return 'exec /usr/bin/env ${shellQuote('XDG_CONFIG_HOME=$configRoot')} ${shellQuote(herdrPath)} '
      '--session ${shellQuote(session)} terminal session observe ${shellQuote(terminalId)} --cols $observationCols --rows $observationRows';
  }

}

/// Retiring a channel waits for its peer CLOSE. Only the observation exec's
/// CLOSE doubles as the shared SSH transport's liveness proof; the other
/// channels are transient forwards that retire alone when CLOSE is missed.
enum RemoteChannelRole { observation, watch, snapshot, input }

class RemoteEvidence {
  bool hostKeyChecked = false, hostKeyMatched = false, authStarted = false;
  bool snapshotReceived = false, fullFrameReceived = false;
  int generation = 0, lateEventsIgnored = 0;
  int frameCount = 0, deltaFrames = 0, paneCount = 0, connectionCount = 0, bufferHighWaterBytes = 0;
  int? lastSeq;
  String? errorCode;
  // Which channel roles missed their CLOSE deadline; bounded to the enum.
  final Set<String> channelRetireFailures = {};
  // Bounded progress only; never contains an endpoint, frame, or input.
  String observationPhase = 'idle';
  Map<String,Object?> toReport(String testCase, bool passed) => {
    'status': passed ? 'passed' : 'failed', 'case':testCase,
    'hostKeyChecked':hostKeyChecked, 'hostKeyMatched':hostKeyMatched,
    'authStarted':authStarted, 'snapshotReceived':snapshotReceived,
    'fullFrameReceived':fullFrameReceived,'generation':generation,
    'lateEventsIgnored':lateEventsIgnored,'errorCode':errorCode,
    'frameCount':frameCount,'deltaFrames':deltaFrames,'lastSeq':lastSeq,'paneCount':paneCount,
    'connectionCount':connectionCount,'bufferHighWaterBytes':bufferHighWaterBytes,
    'channelRetireFailures':channelRetireFailures.toList()..sort(),
  };
}

/// Records a missed CLOSE deadline for `role`. Returns whether the miss
/// invalidates the whole connection: true only for the observation channel
/// (fail closed); watch, snapshot and input channels retire alone.
bool recordChannelRetireMiss(RemoteEvidence evidence, RemoteChannelRole role) {
  evidence.channelRetireFailures.add(role.name);
  return role == RemoteChannelRole.observation;
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
/// An observation opened from a blocked report requires the same endpoint,
/// pane and terminal to remain blocked until its first complete frame.
class BlockedSummaryTarget extends RemotePane {
  BlockedSummaryTarget(RemotePane pane,this.endpointKey) : super(pane.paneId,pane.terminalId,label:pane.label,
    agent:pane.agent,agentStatus:pane.agentStatus,workspace:pane.workspace,tab:pane.tab);
  final String endpointKey;
}

enum DashboardFreshness { stale, refreshing, fresh, unavailable }

/// Public provenance from the actual connected socket, never a GUI provider label.
class RemoteDashboardSource {
  const RemoteDashboardSource({required this.host,required this.port,required this.username,required this.hostFingerprint,
    required this.session,required this.socketPath,required this.herdrPath,required this.route});
  factory RemoteDashboardSource.connected(RemoteConfig config,String route) => RemoteDashboardSource(host:config.host,port:config.port,
    username:config.username,hostFingerprint:config.expectedFingerprint,session:config.session,socketPath:config.socketPath,herdrPath:config.herdrPath,route:route);
  final String host,username,hostFingerprint,session,socketPath,herdrPath,route;
  final int port;
  String get endpointKey => jsonEncode([route,host,port,username,hostFingerprint,session,socketPath,herdrPath]);
}

class RemoteDashboard {
  const RemoteDashboard(this.generation, this.session, this.panes,
      {this.freshness=DashboardFreshness.stale,this.revision=0,this.syncedAt,this.source,this.observationEpoch=0});
  final int generation, revision;
  final String session;
  final List<RemotePane> panes;
  final DashboardFreshness freshness;
  /// Local receipt time of this validated snapshot, independent of terminal frames.
  /// Legacy/custom sources without such evidence leave it unknown.
  final DateTime? syncedAt;
  final RemoteDashboardSource? source;
  final int observationEpoch;
  bool get selectable => freshness == DashboardFreshness.fresh || freshness == DashboardFreshness.unavailable;
  RemoteDashboard withFreshness(DashboardFreshness value,{int? revision}) => RemoteDashboard(generation,session,panes,
    freshness:value,revision:revision ?? this.revision,syncedAt:syncedAt,source:source,observationEpoch:observationEpoch);
}
/// Revalidate only before the first complete frame of a blocked-row intent.
bool stillBlockedSummaryTarget(BlockedSummaryTarget target,RemoteDashboard board) {
  if (board.source?.endpointKey != target.endpointKey) return false;
  final matches = board.panes.where((p) => p.paneId == target.paneId && p.terminalId == target.terminalId).toList();
  return matches.length == 1 && matches.single.agentStatus == 'blocked';
}
void requireInitialBlockedObservation(RemotePane target,RemoteDashboard board) {
  if (target is BlockedSummaryTarget && !stillBlockedSummaryTarget(target,board)) {
    throw const RemoteFailure('resume_target_changed');
  }
}
/// Selection and automatic requested-target restoration share this guard.
/// A matching ID in an old row is never permission to observe it.
void requireSelectableDashboardTarget(RemotePane target,RemoteDashboard board) {
  if (!board.selectable) throw const RemoteFailure('stale_selection');
  requireOriginalObservationTarget(target,board);
}
/// A resumed view is bound to both fields from its original snapshot.
void requireOriginalObservationTarget(RemotePane original,RemoteDashboard fresh) {
  final matches = fresh.panes.where((p) => p.paneId == original.paneId && p.terminalId == original.terminalId);
  if (matches.length != 1) throw const RemoteFailure('resume_target_changed');
}
/// Fixed herdr 0.9.5 protocol 22 subscription schema. Every status filter
/// requires a real pane ID from an authoritative snapshot.
List<Map<String,Object?>> dashboardSubscriptions(List<RemotePane> panes) => [
  for (final type in const ['workspace.created','workspace.updated','workspace.metadata_updated',
    'workspace.renamed','workspace.moved','workspace.reordered','workspace.closed','workspace.focused',
    'tab.created','tab.closed','tab.focused','tab.renamed','tab.moved',
    'pane.created','pane.closed','pane.updated','pane.focused','pane.moved','pane.exited',
    'pane.agent_detected','layout.updated']) {'type':type},
  for (final pane in panes) {'type':'pane.agent_status_changed','pane_id':pane.paneId},
];
enum DashboardWatchAck { started, unavailable, retry }
/// Fixed protocol-22 envelopes. Push records have no RPC ID; errors must echo
/// this subscription's ID. Payloads are checked only as invalidations and are
/// never used to update a pane, terminal, status or input target.
DashboardWatchAck validateDashboardWatchAck(Map<String,dynamic> record,String requestId,
    {required bool initialGlobal}) {
  if (record['id'] != requestId || record.keys.any((key) => !{'id','result','error'}.contains(key))) {
    throw const RemoteFailure('invalid_response');
  }
  final error = record['error'];
  if (error != null) {
    if (record.containsKey('result') || error is! Map || error['code'] is! String || error['message'] is! String) {
      throw const RemoteFailure('invalid_response');
    }
    final unavailable = {'unknown_method','method_not_found','invalid_method'}.contains(error['code']) ||
      (initialGlobal && error['code'] == 'invalid_request');
    return unavailable ? DashboardWatchAck.unavailable : DashboardWatchAck.retry;
  }
  final result = record['result'];
  if (record.containsKey('error') || result is! Map || result.length != 1 || result['type'] != 'subscription_started') {
    throw const RemoteFailure('invalid_response');
  }
  return DashboardWatchAck.started;
}
void validateDashboardWatchEvent(Map<String,dynamic> record,String requestId,Set<String> subscribedPanes) {
  if (record.containsKey('error')) {
    final error = record['error'];
    if (record.length != 2 || record['id'] != requestId || error is! Map ||
        error['code'] is! String || error['message'] is! String) throw const RemoteFailure('invalid_response');
    throw const RemoteFailure('watch_disconnected');
  }
  final event = record['event'],data = record['data'];
  if (record.length != 2 || event is! String || data is! Map) throw const RemoteFailure('invalid_response');
  bool id(Object? value) => value is String && RegExp(r'^[A-Za-z0-9:_-]{1,128}$').hasMatch(value);
  if (event == 'pane.agent_status_changed') {
    if (data.containsKey('type') || !subscribedPanes.contains(data['pane_id']) || !id(data['workspace_id']) ||
        !{'idle','working','blocked','done','unknown'}.contains(data['agent_status'])) throw const RemoteFailure('invalid_response');
    return;
  }
  final allowed = dashboardSubscriptions(const []).map((entry) => (entry['type'] as String).replaceAll('.','_')).toSet();
  if (!allowed.contains(event) || data['type'] != event) throw const RemoteFailure('invalid_response');
  bool objectId(String field,String key) => data[field] is Map && id((data[field] as Map)[key]);
  final valid = switch (event) {
    'workspace_created' || 'workspace_updated' || 'workspace_metadata_updated' => objectId('workspace','workspace_id'),
    'workspace_reordered' => data['workspace_ids'] is List && (data['workspace_ids'] as List).every(id) && data['workspaces'] is List,
    'workspace_closed' || 'workspace_focused' => id(data['workspace_id']),
    'workspace_renamed' => id(data['workspace_id']) && data['label'] is String,
    'workspace_moved' => id(data['workspace_id']) && data['insert_index'] is int && data['workspaces'] is List,
    'tab_created' => objectId('tab','tab_id') && objectId('tab','workspace_id'),
    'tab_closed' || 'tab_focused' => id(data['tab_id']) && id(data['workspace_id']),
    'tab_renamed' => id(data['tab_id']) && id(data['workspace_id']) && data['label'] is String,
    'tab_moved' => id(data['tab_id']) && id(data['workspace_id']) && data['insert_index'] is int && data['tabs'] is List,
    'pane_created' || 'pane_updated' => objectId('pane','pane_id') && objectId('pane','terminal_id') && objectId('pane','workspace_id'),
    'pane_moved' => id(data['previous_pane_id']) && id(data['previous_workspace_id']) && id(data['previous_tab_id']) && objectId('pane','pane_id'),
    'pane_closed' || 'pane_focused' || 'pane_exited' || 'pane_agent_detected' => id(data['pane_id']) && id(data['workspace_id']),
    'layout_updated' => objectId('layout','workspace_id') && objectId('layout','tab_id'),
    _ => false,
  };
  if (!valid) throw const RemoteFailure('invalid_response');
}
/// Every concurrent wait has an independent removable registration. A single
/// callback slot would lose a frame wait when a watch or cleanup starts.
class RemoteWaitGroup {
  final Set<void Function(RemoteFailure)> _waiters = {};
  void add(void Function(RemoteFailure) waiter) => _waiters.add(waiter);
  void remove(void Function(RemoteFailure) waiter) => _waiters.remove(waiter);
  void interrupt(RemoteFailure failure) {
    for (final waiter in _waiters.toList()) { waiter(failure); }
  }
}
/// Constant-space invalidation state. Snapshot contents remain authoritative;
/// no event payload or per-event work list is retained.
class DashboardInvalidations {
  int revision = 0;
  bool dirty = false, lost = false;
  bool mark({bool disconnected=false}) {
    if (revision >= 9007199254740991) throw const RemoteFailure('dashboard_revision_limit');
    final first = !dirty;
    revision++; dirty = true; lost = lost || disconnected;
    return first;
  }
  bool acceptSnapshot(int startedAt) {
    if (lost || revision != startedAt) { dirty = true; return false; }
    dirty = false; return true;
  }
  void resetSubscription() { dirty = false; lost = false; }
}
class RemoteFrame {
  const RemoteFrame(this.seq, this.full, this.ansi,{this.cols=80,this.rows=24,this.observationEpoch=0,this.inputJournalRead});
  final int seq;
  final int cols,rows;
  final int observationEpoch;
  final bool full;
  final String ansi;
  final RemoteInputJournalReadTicket? inputJournalRead;
}
typedef DashboardConsumer = void Function(RemoteDashboard dashboard);
// Awaited consumption provides backpressure: no unbounded UI frame queue.
typedef FrameConsumer = FutureOr<void> Function(int generation, String paneId, RemoteFrame frame);

typedef RemoteProgress = void Function(int generation, String phase);
typedef SocketConnector = Future<SSHSocket> Function(String host, int port);

/// Route metadata is read from the actual socket, never from GUI selection.
String connectedSocketRoute(SSHSocket socket) => socket is RoutedSSHSocket
  ? (socket as RoutedSSHSocket).actualRoute : 'system';

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
  int? _serialTicket;
  bool _serialOpening = false;
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
  // The adapter serializes actual opens. Trace confirmation is emitted before
  // dartssh2 completes the original open Future (4.1.0 _handleChannelConfirmation).
  void beginTicket() {
    if (_serialOpening) { _overflowed = true; onOverflow(); throw const RemoteFailure('channel_identity'); }
    _serialOpening = true; _serialTicket = null;
  }
  int? endTicket({required bool succeeded}) {
    final ticket = _serialTicket;
    _serialTicket = null; _serialOpening = false;
    if ((succeeded && ticket == null) || (!succeeded && ticket != null)) {
      if (!_overflowed) { _overflowed = true; onOverflow(); }
    }
    return ticket;
  }
  Future<void> waitTicket(int id) async {
    while (_active.contains(id)) { await (_change ??= Completer<void>()).future; }
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
  void trace(Object? message) {
    if (message is! String) return;
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
      if (_serialOpening) {
        if (_serialTicket != null) {
          if (!_overflowed) { _overflowed = true; onOverflow(); }
          return;
        }
        _serialTicket = id;
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
  final waits = RemoteWaitGroup(), inputWaits = RemoteWaitGroup(),
    observationWaits = RemoteWaitGroup(), watchWaits = RemoteWaitGroup();
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
  RemotePane? selectedTarget;
  RemoteConfig? config;
  RemoteInputCapability? inputCapability;
  RemoteInputTarget? inputTarget;
  bool inputBusy = false;
  bool observationPaused = false;
  int observationEpoch = 0;
  Completer<void>? resumeObservation;
  Future<void> openTail = Future<void>.value();
  Future<void> snapshotTail = Future<void>.value();
  final Map<Object,int> channelTickets = Map<Object,int>.identity();
  SSHForwardChannel? watch;
  int watchEpoch = 0, dashboardRevision = 0;
  Future<void>? watchRun;
  void Function()? restartWatch;
  void Function()? wakeWatch;
  ChannelRetirementTracker? channels;
  bool lateChannelDestroyFailed = false;
}

/// Stops only the no-PTY observer exec owned by this adapter, at most once.
class ObserverSessionTerminator {
  final Expando<bool> _stopped = Expando<bool>();
  void stop(SSHSession session) {
    if (_stopped[session] == true) return;
    _stopped[session] = true;
    try { session.kill(SSHSignal.TERM); } catch (_) { /* still destroy and await peer CLOSE */ }
    session.channel.destroy();
  }
}

/// Defaults to read-only. Writes require the separate guarded test extension;
/// stock herdr 0.9.5 never gains input through a pane-ID-only fallback.
class RemoteReadOnlyAdapter {
  RemoteReadOnlyAdapter({SocketConnector? connector, this.inputJournal,RemoteConnectionBudget? connectionBudget,DateTime Function()? clock}) : _clock = clock ?? DateTime.now,
    _budget = connectionBudget ?? _sharedConnectionBudget, _connector = connector ??
    ((host,port) => SSHSocket.connect(host,port,timeout:const Duration(seconds:8)));
  final SocketConnector _connector;
  final DateTime Function() _clock;
  final RemoteConnectionBudget _budget;
  final RemoteInputJournal? inputJournal;
  final ObserverSessionTerminator _observerTerminator = ObserverSessionTerminator();
  // This SSH exec runs only our `herdr ... terminal session observe` reader,
  // without a PTY. A quiet reader may not notice CLOSE until it writes again;
  // ask that reader to exit before closing its channel. Peer CLOSE is still
  // required by _retireChannel and a missing acknowledgement fails closed.
  void _stopObserver(SSHSession session) {
    _observerTerminator.stop(session);
  }
  RemoteInputJournalReview? Function(RemoteInputTarget target)? captureInputJournalReview;
  int generation = 0, _connectionCount = 0;
  _Attempt? _attempt;
  bool _activeRead = false, _dialPending = false;
  RemoteEvidence evidence = RemoteEvidence();
  late final RemoteInputJournalSession? _journalState = inputJournal == null ? null : RemoteInputJournalSession(inputJournal!);
  RemoteInputPending? get pendingInput {
    final target = inputTarget;
    return target == null ? null : _journalState?.pendingFor(target);
  }
  RemoteInputTarget? get inputTarget => _attempt?.inputTarget;
  RemoteInputCapability? get inputCapability => _journalState?.ready == true ? _attempt?.inputCapability : null;
  RemoteDashboard? get currentDashboard => _attempt?.dashboard;
  bool isInputJournalReadCurrent(RemoteInputJournalReadTicket ticket) {
    final a = _attempt,state = _journalState;
    return a != null && state != null && _valid(a) && a.failure == null && !a.observationPaused &&
      a.evidence.fullFrameReceived && a.observationEpoch == ticket.observationEpoch &&
      identical(a.inputTarget,ticket.target) && identical(ticket.review.refreshTarget,ticket.target) &&
      state.isCurrentRead(ticket.revision) &&
      !state.hasClaimFor(ticket.target) && state.pendingFor(ticket.target) == null;
  }

  bool _valid(_Attempt a) => identical(a,_attempt) && a.generation == generation && !a.closed;
  void _check(_Attempt a) {
    if (a.failure != null) throw a.failure!;
    if (!_valid(a)) { a.evidence.lateEventsIgnored++; throw const RemoteFailure('cancelled'); }
  }
  void _fail(_Attempt a, RemoteFailure failure) {
    a.failure ??= failure;
    a.waits.interrupt(a.failure!); a.wakeWatch?.call();
  }
  void _cleanupFailed(_Attempt a,RemoteFailure failure) {
    _fail(a,failure);
    // Late cleanup runs outside the owning read stack. Closing the transport
    // is required even if no main waiter is currently registered.
    unawaited(_close(a).then<void>((_) {},onError:(Object _,StackTrace __) {}));
  }
  Future<T> _wait<T>(_Attempt a, Future<T> future, {void Function(T)? disposeLate, void Function(bool,bool)? onSettled,
      bool timed = true, bool input = false, bool observation = false, bool watch = false,Duration timeout=const Duration(seconds:10)}) async {
    // Each scope retains all concurrent waits, then removes this registration
    // on completion instead of accumulating cancellation Future.any listeners.
    final completion = Completer<T>();
    void interrupt(RemoteFailure failure) {
      if (!completion.isCompleted) completion.completeError(failure);
    }
    a.waits.add(interrupt);
    if (watch) a.watchWaits.add(interrupt);
    if (input) a.inputWaits.add(interrupt);
    if (observation) a.observationWaits.add(interrupt);
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
      a.waits.remove(interrupt); a.watchWaits.remove(interrupt);
      a.inputWaits.remove(interrupt); a.observationWaits.remove(interrupt);
    }
  }
  Future<T> _openChannel<T extends Object>(_Attempt a,Future<T> Function() open,void Function(T) destroy,
      {bool input=false,bool observation=false,bool watch=false,required RemoteChannelRole role}) async {
    final tracker = a.channels;
    if (tracker == null) throw const RemoteFailure('connection_failed');
    final epoch = a.observationEpoch, watchEpoch = a.watchEpoch;
    tracker.startOpen(); // queued and late opens both retain their reservation
    final previous = a.openTail;
    final release = Completer<void>();
    a.openTail = release.future;
    var started = false;
    try {
      await _wait(a,previous,input:input,observation:observation,watch:watch);
      _check(a);
      if ((observation && (a.observationPaused || epoch != a.observationEpoch)) ||
          (watch && (a.observationPaused || watchEpoch != a.watchEpoch))) {
        throw const RemoteFailure('observation_paused');
      }
      tracker.beginTicket(); started = true;
      final pending = Future<T>.sync(open);
      var confirmed = false,settled = false;
      Timer? abandonment;
      final owned = pending.then<T>((value) {
        final ticket = tracker.endTicket(succeeded:true); confirmed = ticket != null;
        if (ticket == null || !_valid(a) || a.failure != null ||
            (observation && (a.observationPaused || epoch != a.observationEpoch)) ||
            (watch && (a.observationPaused || watchEpoch != a.watchEpoch))) {
          try { destroy(value); } catch (_) {
            a.lateChannelDestroyFailed = true; _cleanupFailed(a,const RemoteFailure('channel_cleanup_timeout'));
          }
          if (ticket != null) {
            unawaited(tracker.waitTicket(ticket).timeout(_channelRetireBudget(a)).catchError((Object _) {
              if (_valid(a) && recordChannelRetireMiss(a.evidence,role)) _cleanupFailed(a,const RemoteFailure('channel_cleanup_timeout'));
            }));
          }
          throw const RemoteFailure('cancelled');
        }
        a.channelTickets[value] = ticket;
        return value;
      },onError:(Object error,StackTrace stack) {
        confirmed = tracker.endTicket(succeeded:false) != null;
        Error.throwWithStackTrace(error,stack);
      });
      try { return await _wait(a,owned,input:input,observation:observation,watch:watch,
        onSettled:(_,__) {
          settled = true; abandonment?.cancel();
          tracker.finishOpen(succeeded:confirmed);
          if (!release.isCompleted) release.complete();
        },disposeLate:(value) {
          final ticket = a.channelTickets.remove(value);
          try { destroy(value); } catch (_) {
            a.lateChannelDestroyFailed = true; _cleanupFailed(a,const RemoteFailure('channel_cleanup_timeout'));
          }
          if (ticket == null) { _cleanupFailed(a,const RemoteFailure('channel_identity')); }
          else {
            unawaited(tracker.waitTicket(ticket).timeout(_channelRetireBudget(a)).catchError((Object _) {
              if (_valid(a) && recordChannelRetireMiss(a.evidence,role)) _cleanupFailed(a,const RemoteFailure('channel_cleanup_timeout'));
            }));
          }
        }); } catch (_) {
        // An abandoned original open still owns the serial lock and capacity.
        // If it never settles, retaining this SSH cannot safely recover.
        if (!settled && _valid(a)) {
          abandonment = Timer(const Duration(seconds:2),() {
            if (!settled && _valid(a)) {
              _cleanupFailed(a,const RemoteFailure('channel_cleanup_timeout'));
            }
          });
        }
        rethrow;
      }
    } finally {
      if (!started) {
        // A cancelled queued request must not release the next request ahead
        // of its predecessor; it must never issue an open after cancellation.
        unawaited(previous.whenComplete(() {
          tracker.finishOpen(succeeded:false);
          if (!release.isCompleted) release.complete();
        }));
      }
    }
  }
  Duration _channelRetireBudget(_Attempt a) => a.config?.channelRetireTimeout ?? const Duration(seconds:2);
  Future<void> _retireChannel(_Attempt a,Object channel,{required RemoteChannelRole role}) async {
    final id = a.channelTickets.remove(channel);
    if (id == null) { _cleanupFailed(a,const RemoteFailure('channel_identity')); throw const RemoteFailure('channel_identity'); }
    // A pause interrupts reads, not the independent obligation to observe
    // this ticket's CLOSE before keeping the SSH transport.
    try { await a.channels!.waitTicket(id).timeout(_channelRetireBudget(a)); }
    catch (_) {
      if (!_valid(a)) rethrow;
      // Only the observing channel's CLOSE is the shared transport's liveness
      // proof; a watch, snapshot or input channel retires alone when missed.
      if (recordChannelRetireMiss(a.evidence,role)) {
        _cleanupFailed(a,const RemoteFailure('channel_cleanup_timeout'));
        rethrow;
      }
    }
  }
  Future<void> _close(_Attempt a) => a.closing ??= _closeResources(a);
  Future<void> _closeResources(_Attempt a) async {
    a.closed = true;
    a.wakeWatch?.call(); a.waits.interrupt(const RemoteFailure('cancelled'));
    // Destroy owned channels synchronously; SSHSession.close discards a Future
    // in dartssh2 4.1.0. Let the client finish before destroying its socket.
    for (final destroy in <void Function()>[
      if (a.observe != null) () => _stopObserver(a.observe!),
      if (a.forward != null) () => a.forward!.destroy(),
      if (a.inputForward != null) () => a.inputForward!.destroy(),
      if (a.watch != null) () => a.watch!.destroy(),
    ]) {
      try { destroy(); } catch (_) { a.lateChannelDestroyFailed = true; }
    }
    try { await a.stderr?.cancel().timeout(const Duration(seconds:2)); } catch (_) { /* discarded remote stream */ }
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
    a.waits.interrupt(const RemoteFailure('cancelled')); a.wakeWatch?.call();
    await _close(a);
  }

  /// Revoke input immediately and retire only the observing channel. The SSH
  /// transport stays owned by this attempt until explicit cancel or failure.
  bool pauseObservation() {
    final a = _attempt;
    if (a == null || !_valid(a) || a.failure != null) return false;
    if (a.observationPaused) return true;
    a.observationPaused = true; a.observationEpoch++; a.watchEpoch++;
    a.evidence.observationPhase = 'paused';
    final board = a.dashboard;
    if (board != null) a.dashboard = board.withFreshness(DashboardFreshness.stale);
    // Revoke every write proof before any destructor can throw.
    a.evidence.fullFrameReceived = false; a.inputTarget = null;
    a.watchWaits.interrupt(const RemoteFailure('observation_paused')); a.wakeWatch?.call();
    a.inputWaits.interrupt(const RemoteFailure('cancelled'));
    a.observationWaits.interrupt(const RemoteFailure('observation_paused'));
    for (final destroy in <void Function()>[
      if (a.watch != null) () => a.watch!.destroy(),
      if (a.inputForward != null) () => a.inputForward!.destroy(),
      if (a.observe != null) () => _stopObserver(a.observe!),
    ]) {
      try { destroy(); } catch (_) { _cleanupFailed(a,const RemoteFailure('channel_cleanup_timeout')); }
    }
    return _valid(a) && a.failure == null;
  }

  /// An explicit user action only. A fresh target snapshot and first full are
  /// required before a new input capability can be used.
  bool resumeObservation() {
    final a = _attempt;
    if (a == null || !_valid(a) || a.failure != null || !a.observationPaused) return false;
    a.observationPaused = false; a.evidence.observationPhase = 'resuming';
    final signal = a.resumeObservation; a.resumeObservation = null;
    if (signal != null && !signal.isCompleted) signal.complete();
    a.restartWatch?.call();
    return true;
  }

  Future<RemoteSnapshot> read(RemoteConfig config, {RemoteProgress? onProgress}) =>
    // Legacy snapshots expose only ANSI, so their request stays 80x24 even if
    // a programmatic caller supplies a wider streaming canvas preference.
    _run(config.withObservationCanvas(80,24),onProgress:onProgress);

  /// Keeps the same authenticated connection open. Explicit selectPane is
  /// required after the dashboard; cancellation/EOF ends this attempt forever.
  Future<RemoteSnapshot> observe(RemoteConfig config, {required DashboardConsumer onDashboard,
      required FrameConsumer onFrame, RemoteProgress? onProgress}) =>
    _run(config,onProgress:onProgress,onDashboard:onDashboard,onFrame:onFrame);

  void selectPane(int expectedGeneration, String paneId) {
    final a = _attempt;
    if (a == null || !_valid(a) || a.failure != null || a.observationPaused || expectedGeneration != a.generation || a.selection.isCompleted) {
      throw const RemoteFailure('stale_selection');
    }
    final matches = a.dashboard?.panes.where((p) => p.paneId == paneId).toList();
    if (matches == null || matches.length != 1) throw const RemoteFailure('pane_missing');
    selectTarget(expectedGeneration,matches.single);
  }

  /// Freeze both fields supplied by the row, rather than resolving a reused
  /// pane ID to a different terminal after the row was rendered.
  void selectTarget(int expectedGeneration, RemotePane target) {
    final a = _attempt;
    if (a == null || !_valid(a) || a.failure != null || a.observationPaused || expectedGeneration != a.generation || a.selection.isCompleted) {
      throw const RemoteFailure('stale_selection');
    }
    final board = a.dashboard;
    if (board == null) throw const RemoteFailure('pane_missing');
    requireSelectableDashboardTarget(target,board);
    a.selectedTarget = target; a.selection.complete(target);
  }

  String _requestId() {
    final random = Random.secure();
    return List.generate(16, (_) => random.nextInt(256).toRadixString(16).padLeft(2,'0')).join();
  }

  bool _canWrite(_Attempt a, RemoteInputTarget target) => _valid(a) && a.failure == null && !a.observationPaused &&
    identical(target,a.inputTarget) && identical(target.connection,a) &&
    a.inputCapability != null && a.evidence.hostKeyMatched && a.evidence.fullFrameReceived;

  /// Resolve exactly the raw marker reviewed at the click, on a new full and
  /// connection for its endpoint. A later read can never substitute a new raw.
  Future<bool> acknowledgeInputUnknown(RemoteInputTarget target,{required String reviewedRecord}) async {
    final a = _attempt,state = _journalState;
    if (a == null || state == null || !_canWrite(a,target) || a.inputBusy || !state.ready) return false;
    RemoteInputPending reviewed;
    try { reviewed = RemoteInputPending.parse(reviewedRecord); } catch (_) { return false; }
    final original = state.pendingFor(target);
    if (original == null || original.raw != reviewedRecord || !target.sameEndpoint(reviewed.target) ||
        identical(target.connection,original.target.connection)) return false;
    a.inputBusy = true;
    try {
      await state.refresh().timeout(const Duration(seconds:10));
      final current = state.pendingFor(target);
      if (!_canWrite(a,target) || current == null || current.raw != reviewedRecord ||
          identical(target.connection,current.target.connection)) return false;
      await state.resolve(reviewedRecord).timeout(const Duration(seconds:10));
      return state.pendingFor(target) == null;
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
      catch (_) {
        final pending = _journalState?.pendingFor(target);
        if (!result.isCompleted) result.complete(pending == null
          ? const RemoteInputResult.rejected('input_journal_unavailable')
          : const RemoteInputResult.unknown());
      }
    },(error,stack) {
      if (owned != null) _fail(owned,const RemoteFailure('async_input_transport_failed'));
      else if (!result.isCompleted) result.complete(const RemoteInputResult.rejected('input_not_ready'));
    });
    return result.future;
  }

  Future<RemoteInputResult> _sendInput(RemoteInputTarget target, Uint8List bytes,
      {required bool Function() stillCurrent}) async {
    bytes = Uint8List.fromList(bytes);
    final a = _attempt,state = _journalState;
    if (a == null || !_canWrite(a,target) || a.inputBusy || state == null || !state.ready ||
        !stillCurrent() || bytes.isEmpty || bytes.length > a.inputCapability!.maxBytes) {
      return const RemoteInputResult.rejected('input_not_ready');
    }
    a.inputBusy = true;
    var submitted = false;
    RemoteInputPending? pending;
    RemoteInputJournalClaim? claim;
    SSHForwardChannel? channel;
    Future<String>? responseFuture;
    RemoteInputResult result = const RemoteInputResult.rejected('input_cancelled_before_write');
    try {
      // Refresh for this actual target, then acquire the native atomic endpoint
      // lease. Another adapter's marker for another endpoint is irrelevant.
      await _wait(a,state.refresh(),input:true);
      final blocked = state.pendingFor(target);
      if (blocked != null) return const RemoteInputResult.rejected('input_target_pending').withPending(blocked);
      if (!_canWrite(a,target) || !stillCurrent()) return result;
      final opened = await _openChannel<SSHForwardChannel>(a,() => a.client!.forwardLocalUnix(a.config!.socketPath),
        (c) => c.destroy(),input:true,role:RemoteChannelRole.input);
      channel = opened; a.inputForward = opened;
      if (!_canWrite(a,target) || !stillCurrent()) return result;
      final id = _requestId();
      final request = utf8.encode('${jsonEncode({'id':id,'method':'pocket.input.send','params':{
        'pane_id':target.paneId,'expected_terminal_id':target.terminalId,'bytes_base64':base64Encode(bytes),
      }})}\n');
      pending = RemoteInputPending.create(id,target);
      claim = state.prepare(pending);
      await _wait(a,claim.prepared,input:true);
      if (!_canWrite(a,target) || !stillCurrent()) {
        // Cancellation after persistence keeps the exact marker even though
        // this local path can prove it never submitted request bytes.
        return const RemoteInputResult.journalLocked(RemoteInputDisposition.rejected).withPending(pending);
      }
      submitted = true; // Even sink.add failure cannot prove remote rejection.
      opened.sink.add(request);
      responseFuture = boundedLines(opened.stream,maxTotal:16384).first;
      final line = await _wait(a,responseFuture,input:true);
      result = parseInputResponse(_decodeObject(line),id,target,bytes.length);
      if (result.disposition != RemoteInputDisposition.unknown) {
        try { await state.complete(claim).timeout(const Duration(seconds:10)); }
        catch (_) { result = RemoteInputResult.journalLocked(result.disposition,receipt:result.receipt); }
      }
    } catch (_) {
      result = submitted ? const RemoteInputResult.unknown()
        : RemoteInputResult.rejected(pending == null ? 'input_journal_unavailable' : 'input_cancelled_before_write');
      if (!submitted && pending != null) {
        // An error/timeout does not prove prepare never persisted. Keep the
        // original claim until it settles; refresh can distinguish a foreign
        // same-endpoint marker from unreadable storage without retrying input.
        try { await state.refresh().timeout(const Duration(seconds:10)); } catch (_) { /* ready is false */ }
        final blocked = state.pendingFor(target);
        if (blocked != null) {
          result = blocked.raw == pending.raw
            ? const RemoteInputResult.journalLocked(RemoteInputDisposition.rejected).withPending(blocked)
            : const RemoteInputResult.rejected('input_target_pending').withPending(blocked);
        }
      }
    } finally {
      var retired = true;
      try { channel?.destroy(); }
      catch (_) { retired = false; _cleanupFailed(a,const RemoteFailure('channel_cleanup_timeout')); }
      if (identical(a.inputForward,channel)) a.inputForward = null;
      if (channel != null) {
        try {
          if (_valid(a) && retired) { await _retireChannel(a,channel,role:RemoteChannelRole.input); }
          else { await _close(a); }
        } catch (_) {
          retired = false; _cleanupFailed(a,const RemoteFailure('channel_cleanup_timeout'));
          try { await _close(a); retired = true; } catch (_) { /* retain active lease */ }
        }
      }
      final ownedClaim = claim,ownedResponse = responseFuture;
      if (ownedClaim != null && retired) {
        unawaited(() async {
          // Cancellation of _wait is not settlement of the underlying stream
          // or prepare/complete. Hold this lease until every original operation
          // and channel cleanup has converged, then abandon only its own raw.
          try { await ownedResponse; } catch (_) { /* unknown response */ }
          await state.retire(ownedClaim);
        }().then<void>((_) {},onError:(Object _,StackTrace __) {}));
      }
      a.inputBusy = false;
    }
    if (result.pending != null) return result;
    if (pending != null && (result.disposition == RemoteInputDisposition.unknown || result.requiresJournalRecovery)) {
      return result.withPending(pending);
    }
    final unresolved = state.pendingFor(target);
    return unresolved == null ? result : result.withPending(unresolved);
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
      Future<RemoteDashboard> snapshot({bool observation=false,bool watch=false}) async {
        final previous = a.snapshotTail;
        final release = Completer<void>();
        final watchEpoch = a.watchEpoch, observationEpoch = a.observationEpoch;
        a.snapshotTail = release.future;
        var acquired = false;
        try {
          await _wait(a,previous,observation:observation,watch:watch);
          _check(a);
          if (((observation || watch) && a.observationPaused) ||
              (watch && watchEpoch != a.watchEpoch) ||
              (observation && observationEpoch != a.observationEpoch)) throw const RemoteFailure('observation_paused');
          acquired = true;
          final channel = await _openChannel<SSHForwardChannel>(a,() => client.forwardLocalUnix(config.socketPath),
            (c) => c.destroy(),observation:observation,watch:watch,role:RemoteChannelRole.snapshot);
          if (!watch) a.forward = channel;
          try {
            final id = _requestId();
            channel.sink.add(utf8.encode('${jsonEncode({'id':id,'method':'session.snapshot','params':<String,Object?>{}})}\n'));
            final line = await _wait(a,boundedLines(channel.stream,maxTotal:1048576).first,observation:observation,watch:watch);
            final rpc = _decodeObject(line);
            if (rpc['id'] != id || rpc['error'] != null || rpc['ok'] == false || rpc['result'] is! Map) {
              throw const RemoteFailure('snapshot_rejected');
            }
            final parsed = parseSnapshotDashboard(config,Map<String,dynamic>.from(rpc['result'] as Map),a.generation);
            return RemoteDashboard(parsed.generation,parsed.session,parsed.panes,syncedAt:_clock().toUtc(),
              source:RemoteDashboardSource.connected(config,connectedSocketRoute(socket)),observationEpoch:observationEpoch);
          } finally {
            channel.destroy(); if (identical(a.forward,channel)) a.forward = null;
            if (_valid(a)) await _retireChannel(a,channel,role:RemoteChannelRole.snapshot);
          }
        } finally {
          if (acquired) { if (!release.isCompleted) release.complete(); }
          else { unawaited(previous.whenComplete(() { if (!release.isCompleted) release.complete(); })); }
        }
      }
      phase('snapshot');
      final dashboard = await snapshot();
      e.snapshotReceived = true; a.dashboard = dashboard; e.paneCount = dashboard.panes.length;
      if (onDashboard != null) {
        // Capability discovery is side-effect-free; stock 0.9.5 replies with an
        // error and remains read-only. This is never inferred from version alone.
        final capabilityChannel = await _openChannel<SSHForwardChannel>(a,() => client.forwardLocalUnix(config.socketPath),
          (c) => c.destroy(),role:RemoteChannelRole.snapshot);
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
        await _retireChannel(a,capabilityChannel,role:RemoteChannelRole.snapshot);
        if (a.inputCapability != null) {
          try {
            final state = _journalState;
            if (state == null) throw const RemoteFailure('input_journal_unavailable');
            await _wait(a,state.refresh());
          } catch (_) { a.inputCapability = null; }
        }
      }
      // A watch owns one subscription channel and at most one snapshot at a
      // time. Event payloads are only invalidations, never row mutations.
      var initialBlockedObservationCompleted = false;
      void publishBoard(DashboardFreshness state,[RemoteDashboard? authority]) {
        if (!_valid(a) || a.observationPaused || onDashboard == null) return;
        if ((state == DashboardFreshness.fresh || state == DashboardFreshness.unavailable) && authority != null && a.selectedTarget != null) {
          try {
            requireOriginalObservationTarget(a.selectedTarget!,authority);
            if (!initialBlockedObservationCompleted) requireInitialBlockedObservation(a.selectedTarget!,authority);
          }
          on RemoteFailure catch (failure) {
            _fail(a,failure); if (a.observe != null) _stopObserver(a.observe!); return;
          }
        }
        final source = authority ?? a.dashboard;
        if (source == null) return;
        if (a.dashboardRevision >= 9007199254740991) { _fail(a,const RemoteFailure('dashboard_revision_limit')); return; }
        final value = source.withFreshness(state,revision:++a.dashboardRevision);
        a.dashboard = value;
        e.paneCount = value.panes.length;
        onDashboard(value);
      }
      Future<void> runWatch(int epoch) async {
        bool current() => _valid(a) && a.failure == null && !a.observationPaused && epoch == a.watchEpoch;
        var retries = 0;
        while (current()) {
          SSHForwardChannel? channel;
          StreamIterator<String>? lines;
          Completer<void>? changed;
          var unsupported = false;
          final invalidations = DashboardInvalidations();
          void wake() { final signal = changed; changed = null; if (signal != null && !signal.isCompleted) signal.complete(); }
          a.wakeWatch = wake;
          void invalidate({bool disconnected=false}) {
            if (!current()) return;
            bool first;
            try { first = invalidations.mark(disconnected:disconnected); }
            on RemoteFailure catch (failure) { _fail(a,failure); return; }
            if (disconnected) { publishBoard(DashboardFreshness.stale); }
            else if (first) { publishBoard(DashboardFreshness.refreshing); }
            wake();
          }
          Future<void> closeSubscription() async {
            final old = channel;
            final oldLines = lines;
            channel = null; lines = null;
            if (identical(a.watch,old)) a.watch = null;
            old?.destroy();
            final cancelLines = oldLines?.cancel() ?? Future<void>.value();
            final retired = old != null && _valid(a) ? _retireChannel(a,old,role:RemoteChannelRole.watch) : Future<void>.value();
            await Future.wait<void>([cancelLines,retired]).timeout(_channelRetireBudget(a));
          }
          Future<void> subscribe(List<RemotePane> panes,{required bool initialGlobal}) async {
            final opened = await _openChannel<SSHForwardChannel>(a,() => client.forwardLocalUnix(config.socketPath),
              (c) => c.destroy(),watch:true,role:RemoteChannelRole.watch);
            if (!current()) { opened.destroy(); await _retireChannel(a,opened,role:RemoteChannelRole.watch); throw const RemoteFailure('observation_paused'); }
            channel = opened; a.watch = opened;
            final id = _requestId();
            final subscriptions = dashboardSubscriptions(panes);
            opened.sink.add(utf8.encode('${jsonEncode({'id':id,'method':'events.subscribe','params':{'subscriptions':subscriptions}})}\n'));
            lines = StreamIterator<String>(boundedLines(opened.stream,maxTotal:null));
            if (!await _wait(a,lines!.moveNext(),watch:true)) throw const RemoteFailure('watch_disconnected');
            final ack = _decodeObject(lines!.current);
            final accepted = validateDashboardWatchAck(ack,id,initialGlobal:initialGlobal);
            if (accepted != DashboardWatchAck.started) {
              // A missing pane filter must rebuild, not downgrade to a
              // selectable one-shot board. Other server errors also retry.
              unsupported = accepted == DashboardWatchAck.unavailable;
              throw RemoteFailure(unsupported ? 'watch_unavailable' : 'watch_rebuild');
            }
            final subscribedPanes = panes.map((pane) => pane.paneId).toSet();
            final ownedLines = lines!;
            unawaited(() async {
              try {
                while (current() && identical(lines,ownedLines) && await ownedLines.moveNext()) {
                  if (!current() || !identical(lines,ownedLines)) return;
                  final record = _decodeObject(ownedLines.current);
                  validateDashboardWatchEvent(record,id,subscribedPanes);
                  invalidate();
                }
              } catch (_) { /* EOF, malformed record or cancelled stream */ }
              if (current() && identical(lines,ownedLines)) invalidate(disconnected:true);
            }());
          }
          bool sameMembers(RemoteDashboard first,RemoteDashboard second) {
            final left = first.panes.map((p) => p.paneId).toSet();
            final right = second.panes.map((p) => p.paneId).toSet();
            return left.length == right.length && left.containsAll(right);
          }
          try {
            publishBoard(DashboardFreshness.refreshing);
            await subscribe(const [],initialGlobal:true);
            final first = await snapshot(watch:true);
            if (!current() || invalidations.lost) throw const RemoteFailure('watch_disconnected');
            await closeSubscription();
            if (!current()) return;
            invalidations.resetSubscription();
            await subscribe(first.panes,initialGlobal:false);
            var members = first;
            while (current() && !invalidations.lost) {
              final before = invalidations.revision;
              final latest = await snapshot(watch:true);
              if (!current() || invalidations.lost) break;
              if (!sameMembers(members,latest)) {
                members = latest;
                await closeSubscription();
                if (!current()) return;
                invalidations.resetSubscription();
                await subscribe(members.panes,initialGlobal:false);
                continue; // Always read again after the subscription ACK.
              }
              members = latest;
              if (invalidations.acceptSnapshot(before)) {
                retries = 0; publishBoard(DashboardFreshness.fresh,latest);
              } else { publishBoard(DashboardFreshness.refreshing); }
              if (!invalidations.dirty && !invalidations.lost) {
                changed = Completer<void>();
                final signal = changed!;
                final timer = Timer(const Duration(seconds:30),wake);
                try { await signal.future; } finally { timer.cancel(); changed = null; }
              }
              if (current() && !invalidations.lost) {
                publishBoard(DashboardFreshness.refreshing);
                await Future<void>.delayed(const Duration(milliseconds:100));
              }
            }
          } catch (_) {
            if (current() && unsupported) {
              try {
                await closeSubscription();
                final authority = await snapshot(watch:true);
                if (current()) publishBoard(DashboardFreshness.unavailable,authority);
              } catch (_) { unsupported = false; if (current()) publishBoard(DashboardFreshness.stale); }
            } else if (current()) { publishBoard(DashboardFreshness.stale); }
          } finally {
            if (identical(a.wakeWatch,wake)) a.wakeWatch = null;
            // A watch channel's missed CLOSE deadline is recorded by
            // retirement and retires that channel alone; only a local
            // teardown failure can invalidate the shared transport here.
            try { await closeSubscription(); } catch (error) { if (_valid(a) && error is! TimeoutException) _cleanupFailed(a,const RemoteFailure('channel_cleanup_timeout')); }
          }
          if (!current() || unsupported || a.failure != null) return;
          if (++retries > 3) {
            // A visible stopped attempt can be explicitly reviewed/reconnected;
            // do not leave a permanently stale board beside a live observer.
            _fail(a,const RemoteFailure('watch_retry_exhausted'));
            return;
          }
          await Future<void>.delayed(Duration(milliseconds:500 << (retries - 1)));
        }
      }
      void restartWatch() {
        if (onDashboard == null || !_valid(a) || a.observationPaused) return;
        final epoch = ++a.watchEpoch;
        final previous = a.watchRun;
        final future = () async {
          if (previous != null) await previous;
          if (_valid(a) && !a.observationPaused && a.watchEpoch == epoch) await runWatch(epoch);
        }();
        a.watchRun = future;
        unawaited(future.then<void>((_) {},onError:(Object _,StackTrace __) {
          if (_valid(a)) _fail(a,const RemoteFailure('watch_failed'));
        }));
      }
      a.restartWatch = restartWatch;
      phase('snapshot_received');
      RemotePane selected;
      if (onDashboard == null) {
        final matches = dashboard.panes.where((p) => p.paneId == config.paneId).toList();
        if (matches.length != 1) throw const RemoteFailure('pane_missing');
        selected = matches.single;
      } else {
        onDashboard(dashboard); _check(a);
        restartWatch();
        // User selection has no timeout and owns no additional channel/queue.
        selected = await _wait(a,a.selection.future,timed:false);
      }
      _check(a);
      final route = connectedSocketRoute(socket);
      // A row can be replaced between rendering and selection. Validate the
      // frozen pane and terminal against a new authoritative snapshot before
      // opening the observer, including for the first selection.
      var needsSnapshot = onDashboard != null || a.observationEpoch != 0;
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
            e.observationPhase = 'snapshot';
            final fresh = await snapshot(observation:true); checkObservation();
            checkObservation();
            requireOriginalObservationTarget(selected,fresh);
            if (!initialBlockedObservationCompleted) requireInitialBlockedObservation(selected,fresh);
          }
          checkObservation();
          a.inputTarget = RemoteInputTarget(connection:a,generation:a.generation,
            host:config.host,port:config.port,username:config.username,hostFingerprint:config.expectedFingerprint,
            session:config.session,socketPath:config.socketPath,paneId:selected.paneId,terminalId:selected.terminalId,route:route);
          e.fullFrameReceived = false;
          e.observationPhase = 'opening';
          observe = await _openChannel<SSHSession>(a,() => client.execute(config.observeCommand(selected.terminalId)),
            _stopObserver,observation:true,role:RemoteChannelRole.observation);
          checkObservation(); a.observe = observe;
          final current = observe;
          final budget = ObserveByteBudget(continuous:onDashboard != null);
          stderr = current.stderr.listen((chunk) {
            if (!_valid(a) || a.observationPaused || a.observationEpoch != epoch) return;
            try { budget.add(chunk.length,stderr:true); } on RemoteFailure catch (error) {
              e.errorCode = error.code; _fail(a,error); _stopObserver(current);
            }
          },onError:(Object _) {});
          a.stderr = stderr;
          phase('observing'); checkObservation();
          e.observationPhase = 'awaiting_full';
          frames = StreamIterator<RemoteFrame>(validatedFrames(
            current.stdout.map((chunk) { budget.add(chunk.length); return chunk; }),continuous:onDashboard != null));
          var first = true;
          while (await _wait(a,frames.moveNext(),timed:first,observation:true)) {
            checkObservation();
            if (a.failure != null) throw a.failure!;
            final frame = frames.current;
            RemoteInputJournalReadTicket? inputJournalRead;
            if (frame.full && a.inputCapability != null) {
              final inputTarget = a.inputTarget!;
              final review = captureInputJournalReview?.call(inputTarget);
              try {
                final revision = await _wait(a,_journalState!.refresh(),observation:true);
                if (review != null) inputJournalRead = RemoteInputJournalReadTicket(review,inputTarget,epoch,revision);
              } catch (_) { a.inputCapability = null; }
              checkObservation();
            }
            e.frameCount++; if (!frame.full) e.deltaFrames++;
            e.lastSeq = frame.seq; e.fullFrameReceived = true;
            final byteLength = utf8.encode(frame.ansi).length;
            if (byteLength > e.bufferHighWaterBytes) e.bufferHighWaterBytes = byteLength;
            if (first) phase('full_received');
            first = false;
            completed = RemoteSnapshot(a.generation,config.session,selected.paneId,frame.ansi);
            if (onFrame != null) await _wait(a,Future<void>.sync(() => onFrame(a.generation,selected.paneId,
              RemoteFrame(frame.seq,frame.full,frame.ansi,cols:frame.cols,rows:frame.rows,
                observationEpoch:epoch,inputJournalRead:inputJournalRead))),timed:false,observation:true);
            checkObservation();
            if (frame.full) initialBlockedObservationCompleted = true;
            if (frame.full) e.observationPhase = 'streaming';
            if (onDashboard == null) break;
          }
          checkObservation();
          if (onDashboard != null || completed == null) throw const RemoteFailure('observe_ended');
          break;
        } on RemoteFailure catch (error) {
          if (error.code != 'observation_paused' && a.observationEpoch == epoch) rethrow;
          _check(a); needsSnapshot = true;
        } finally {
          if (!a.observationPaused && a.observationEpoch == epoch) e.observationPhase = 'retiring';
          a.inputTarget = null;
          if (onDashboard != null) e.fullFrameReceived = false;
          if (observe != null) _stopObserver(observe);
          if (identical(a.observe,observe)) a.observe = null;
          if (observe != null && _valid(a)) await _retireChannel(a,observe,role:RemoteChannelRole.observation);
          try { await stderr?.cancel(); } catch (_) { /* retired observer */ }
          if (identical(a.stderr,stderr)) a.stderr = null;
          try { await frames?.cancel().timeout(const Duration(seconds:2)); } catch (_) { /* retired observer */ }
        }
        // The observer's exact inbound CLOSE was awaited above.
        }

    } catch (error) {
      e.observationPhase = 'failed';
      final failure = a.failure ?? (error is RemoteFailure ? error : RemoteFailure(e.errorCode ??
        (error is SSHAuthFailError ? 'authentication_failed' : error is SSHAuthAbortError && e.hostKeyMatched ? 'authentication_aborted' : 'connection_failed')));
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
  int? fullCols,fullRows;
  await for (final line in boundedLines(source,maxTotal:continuous ? null : 2097152)) {
    final frame = _decodeObject(line);
    final first = previous == null;
    final code = first ? 'invalid_first_frame' : 'invalid_frame';
    final seq = frame['seq'];
    final cols = frame['width'],rows = frame['height'];
    if (frame['type'] != 'terminal.frame' || frame['encoding'] != 'ansi' || !validRemoteFrameGeometry(cols,rows) ||
        (!continuous && (cols != 80 || rows != 24)) ||
        seq is! int || seq < 0 || seq > 9007199254740991 ||
        frame['full'] is! bool || (first && frame['full'] != true) || frame['bytes'] is! String) {
      throw RemoteFailure(code);
    }
    if (previous != null && seq != previous + 1) throw const RemoteFailure('sequence_gap');
    if (frame['full'] != true && (cols != fullCols || rows != fullRows)) throw RemoteFailure(code);
    String ansi;
    try {
      final bytes = base64Decode(frame['bytes'] as String);
      if (bytes.length > 65536) throw const RemoteFailure('output_limit');
      ansi = utf8.decode(bytes);
    } on FormatException { throw RemoteFailure(code); }
    previous = seq;
    if (frame['full'] == true) { fullCols = cols as int; fullRows = rows as int; }
    yield RemoteFrame(seq,frame['full'] as bool,ansi,cols:cols as int,rows:rows as int);
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
