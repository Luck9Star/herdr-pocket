import 'dart:async';
import 'dart:collection';
import 'dart:convert';

import 'package:dartssh2/dartssh2.dart';
import 'package:flutter/foundation.dart' show TargetPlatform, defaultTargetPlatform, kIsWeb;
import 'package:flutter/services.dart';

import 'network_identity.dart';
import 'network_profiles.dart';
import 'remote_adapter.dart';
import 'remote_input.dart';

/// Public binding only; identity material remains in the native vault.
class NetworkNodeBinding {
  const NetworkNodeBinding(this.profileId,this.profileRevision,this.networkName,this.identityRef);
  final String profileId,networkName,identityRef;
  final int profileRevision;
  Map<String,Object> toMap() => {'profileId':profileId,'profileRevision':profileRevision,
    'networkName':networkName,'identityRef':identityRef};
  factory NetworkNodeBinding.fromMap(Object? value) {
    if (value is! Map || value.length != 4 || !{'profileId','profileRevision','networkName','identityRef'}.containsAll(value.keys) ||
        value['profileId'] is! String || value['profileRevision'] is! int || value['networkName'] is! String || value['identityRef'] is! String) {
      throw const RemoteFailure('network_runtime_unavailable');
    }
    final binding = NetworkNodeBinding(value['profileId'] as String,value['profileRevision'] as int,
      value['networkName'] as String,value['identityRef'] as String);
    if (!isValidOverlayRoute('easy-tier:${binding.profileId}:${binding.profileRevision}:${binding.identityRef}') ||
        binding.networkName.trim().isEmpty || utf8.encode(binding.networkName).length > 64 || RegExp(r'[\x00-\x1f\x7f-\x9f]').hasMatch(binding.networkName)) {
      throw const RemoteFailure('network_runtime_unavailable');
    }
    return binding;
  }
  bool same(NetworkNodeBinding other) => profileId == other.profileId && profileRevision == other.profileRevision &&
    networkName == other.networkName && identityRef == other.identityRef;
}

class NetworkNodeSnapshot {
  const NetworkNodeSnapshot(this.state,this.binding);
  final String state;
  final NetworkNodeBinding? binding;
  factory NetworkNodeSnapshot.fromMap(Object? value) {
    if (value is! Map || value.length != 2 || !value.containsKey('state') || !value.containsKey('binding') ||
        !{'unavailable','starting','engine-started','closing','stopped'}.contains(value['state'])) {
      throw const RemoteFailure('network_runtime_unavailable');
    }
    return NetworkNodeSnapshot(value['state'] as String,value['binding'] == null ? null : NetworkNodeBinding.fromMap(value['binding']));
  }
}

class NativeNetworkRuntime {
  const NativeNetworkRuntime();
  static const channel = MethodChannel('dev.herdr/network-runtime');
  static int _nextOpenId = 0;
  static final Set<String> _uncertainStops = {};
  static final Map<String,int> _stopEpoch = {}, _stopsInFlight = {};
  bool stopUncertain(String profileId) => _uncertainStops.contains(profileId);
  bool get supported => !kIsWeb && defaultTargetPlatform == TargetPlatform.android;
  Future<Object?> call(String method,Map<String,Object> args) async {
    if (!supported) throw const RemoteFailure('provider_unavailable');
    try { return await channel.invokeMethod<Object?>(method,args); }
    catch (_) { throw const RemoteFailure('network_runtime_unavailable'); }
  }
  Future<bool> available() async {
    if (!supported) return false;
    final reply = await call('available',{});
    if (reply is! Map || reply.length != 2 || !reply.containsKey('available') || !reply.containsKey('reason') || reply['available'] is! bool ||
        (reply['reason'] != null && reply['reason'] is! String)) throw const RemoteFailure('network_runtime_unavailable');
    return reply['available'] == true;
  }
  Future<NetworkNodeSnapshot> status(String profileId) async {
    final epoch = _stopEpoch[profileId] ?? 0;
    final duringStop = (_stopsInFlight[profileId] ?? 0) != 0;
    final result = NetworkNodeSnapshot.fromMap(await call('nodeStatus',{'profileId':profileId}));
    if (result.binding != null && result.binding!.profileId != profileId) throw const RemoteFailure('network_binding_changed');
    if (result.state == 'stopped' && !duringStop && (_stopsInFlight[profileId] ?? 0) == 0 &&
        (_stopEpoch[profileId] ?? 0) == epoch) _uncertainStops.remove(profileId);
    return result;
  }
  Future<NetworkNodeSnapshot> start(NetworkNodeBinding binding,List<String> peers) async {
    final result = NetworkNodeSnapshot.fromMap(await call('nodeStart',{'binding':binding.toMap(),'peers':peers}));
    if (result.binding != null && !result.binding!.same(binding)) throw const RemoteFailure('network_binding_changed');
    return result;
  }
  Future<NetworkNodeSnapshot> stop(NetworkNodeBinding binding) async {
    final id = binding.profileId;
    _stopEpoch[id] = (_stopEpoch[id] ?? 0) + 1;
    _stopsInFlight[id] = (_stopsInFlight[id] ?? 0) + 1;
    _uncertainStops.add(id);
    try {
      final result = NetworkNodeSnapshot.fromMap(await call('nodeStop',{'binding':binding.toMap()}));
      if (result.binding != null && !result.binding!.same(binding)) throw const RemoteFailure('network_binding_changed');
      if (result.state == 'stopped' && _stopsInFlight[id] == 1) { _uncertainStops.remove(binding.profileId); }
      else { _uncertainStops.add(binding.profileId); }
      return result;
    } catch (_) { _uncertainStops.add(binding.profileId); rethrow; }
    finally {
      _stopsInFlight[id] = _stopsInFlight[id]! - 1;
      _stopEpoch[id] = (_stopEpoch[id] ?? 0) + 1;
    }
  }

  Future<NetworkNodeBinding> freeze(NetworkProfile profile,NetworkIdentityStore identities) async {
    if (!supported || profile.provider != 'easytier' || !profile.enabled || !await available()) throw const RemoteFailure('provider_unavailable');
    final identity = await identities.status(profile);
    if (identity == null || identity.mode != 'PRIVATE') throw const RemoteFailure('network_identity_unavailable');
    final binding = NetworkNodeBinding(profile.id,profile.revision,profile.settings['networkName'] as String,identity.handle);
    final snapshot = await status(profile.id);
    if (snapshot.state != 'engine-started' || snapshot.binding == null || !snapshot.binding!.same(binding)) {
      throw const RemoteFailure('network_node_not_started');
    }
    return binding;
  }

  /// Used before changing public configuration or local identity. A stop with
  /// unknown result never authorizes the subsequent write.
  Future<void> stopBeforeChange(NetworkProfile profile) async {
    if (!supported || profile.provider != 'easytier') return;
    final current = await status(profile.id);
    if (current.state == 'stopped' && !stopUncertain(profile.id)) return;
    // Status is checked first so an already owned node is not hidden by a
    // later capability change. Only explicit unavailable with no binding and
    // a negative capability result permits offline configuration changes.
    if (current.state == 'unavailable' && current.binding == null && !stopUncertain(profile.id) && !await available()) return;
    if (stopUncertain(profile.id)) throw const RemoteFailure('network_stop_unknown');
    if (current.binding == null || current.binding!.profileId != profile.id) throw const RemoteFailure('network_runtime_unavailable');
    final stopped = await stop(current.binding!);
    if (stopped.state != 'stopped') throw const RemoteFailure('network_stop_unknown');
  }

  Future<SSHSocket> open(NetworkNodeBinding binding,String host,int port,{Duration timeout=const Duration(seconds:8)}) async {
    if (_nextOpenId >= 9223372036854775807) throw const RemoteFailure('network_runtime_unavailable');
    final openId = (++_nextOpenId).toString();
    var abandoned = false, retired = false;
    Object? completed;
    void disposeLate(Object? value) {
      if (retired || value is! Map || value['streamId'] is! String) return;
      retired = true;
      unawaited(call('streamClose',{'streamId':value['streamId'] as String}).then<void>((_) {},onError:(Object _,StackTrace __) {}));
    }
    final pending = call('streamOpen',{'binding':binding.toMap(),'host':host,'port':port,'openId':openId});
    unawaited(pending.then((value) {
      completed = value;
      if (abandoned) disposeLate(value);
    },onError:(Object _,StackTrace __) {}));
    Object? result;
    try { result = await pending.timeout(timeout); }
    catch (_) {
      abandoned = true;
      disposeLate(completed);
      unawaited(call('cancelOpen',{'openId':openId}).then<void>((_) {},onError:(Object _,StackTrace __) {}));
      rethrow;
    }
    if (result is! Map || result.length != 2 || result['streamId'] is! String || result['route'] is! Map) {
      if (result is Map && result['streamId'] is String) {
        unawaited(call('streamClose',{'streamId':result['streamId'] as String}).then<void>((_) {},onError:(Object _,StackTrace __) {}));
      }
      throw const RemoteFailure('network_runtime_unavailable');
    }
    final id = result['streamId'] as String,route = result['route'] as Map;
    if (!RegExp(r'^[A-Za-z0-9_-]{1,96}$').hasMatch(id) || route.length != 4 ||
        !{'provider','profile_id','profile_revision','identity_ref'}.containsAll(route.keys) ||
        route['provider'] != 'easy-tier' || route['profile_id'] != binding.profileId ||
        route['profile_revision'] != binding.profileRevision || route['identity_ref'] != binding.identityRef) {
      unawaited(call('streamClose',{'streamId':id}).then<void>((_) {},onError:(Object _,StackTrace __) {}));
      throw const RemoteFailure('network_binding_changed');
    }
    // Route is derived from the stream response, after matching the frozen binding.
    final actual = '${route['provider']}:${route['profile_id']}:${route['profile_revision']}:${route['identity_ref']}';
    if (!isValidOverlayRoute(actual)) {
      disposeLate(result);
      throw const RemoteFailure('network_runtime_unavailable');
    }
    return NetworkSSHSocket(this,id,actual);
  }
}

/// Actual route accompanies the stream; callers must not fabricate it from GUI state.
abstract interface class RoutedSSHSocket { String get actualRoute; }

class NetworkSSHSocket implements SSHSocket, RoutedSSHSocket {
  NetworkSSHSocket(this.runtime,this.id,this.actualRoute) {
    _incoming = StreamController<Uint8List>(sync:true,onListen:_read,onResume:_read,onCancel:destroy);
    _output = _NetworkSink(this);
    unawaited(_done.future.then<void>((_) {},onError:(Object _,StackTrace __) {}));
  }
  final NativeNetworkRuntime runtime;
  final String id;
  @override final String actualRoute;
  late final StreamController<Uint8List> _incoming;
  late final _NetworkSink _output;
  final _done = Completer<void>();
  final Queue<Uint8List> _writes = Queue();
  int _queued = 0;
  bool _closed = false,_reading = false,_writing = false,_flushing = false;
  Completer<void>? _drained;
  Future<void> _flushTail = Future<void>.value();
  @override Stream<Uint8List> get stream => _incoming.stream;
  @override StreamSink<List<int>> get sink => _output;
  @override Future<void> get done => _done.future;
  Future<Object?> _call(String name,[Map<String,Object> extra = const {}]) => runtime.call(name,{'streamId':id,...extra});
  void _read() {
    if (_reading || _closed || !_incoming.hasListener || _incoming.isPaused) return;
    _reading = true;
    unawaited(() async {
      try {
        while (!_closed && _incoming.hasListener && !_incoming.isPaused) {
          final reply = await _call('streamRead',{'maxBytes':65536});
          if (_closed) break;
          if (reply is! Map || reply.length != 2 || reply['bytes'] is! Uint8List || reply['eof'] is! bool ||
              (reply['bytes'] as Uint8List).length > 65536 || (reply['eof'] == true && (reply['bytes'] as Uint8List).isNotEmpty)) {
            throw const RemoteFailure('network_runtime_unavailable');
          }
          final bytes = reply['bytes'] as Uint8List;
          if (bytes.isNotEmpty) _incoming.add(bytes);
          if (reply['eof'] == true) { destroy(); break; }
          if (bytes.isEmpty) await Future<void>.delayed(const Duration(milliseconds:25));
        }
      } catch (_) { _fail(); }
      finally { _reading = false; }
    }());
  }
  void _add(List<int> bytes) {
    if (_closed || _output.closed || bytes.length > 65536 - _queued) { _fail(); throw const RemoteFailure('network_write_unavailable'); }
    if (bytes.isEmpty) return;
    final copy = Uint8List.fromList(bytes); _writes.add(copy); _queued += copy.length;
    final drain = _drained ??= Completer<void>();
    unawaited(drain.future.then<void>((_) {},onError:(Object _,StackTrace __) {}));
    _write();
  }
  void _write() {
    if (_writing || _closed || _flushing) return;
    _writing = true;
    unawaited(() async {
      try {
        while (!_closed && _writes.isNotEmpty) {
          final chunk = _writes.first;
          final reply = await _call('streamWrite',{'bytes':chunk});
          if (_closed) break;
          if (reply is! Map || reply.length != 1 || reply['accepted'] is! int ||
              (reply['accepted'] as int) < 1 || (reply['accepted'] as int) > chunk.length) throw const RemoteFailure('network_write_unknown');
          final accepted = reply['accepted'] as int;
          _queued -= accepted; _writes.removeFirst();
          if (accepted < chunk.length) _writes.addFirst(Uint8List.fromList(chunk.sublist(accepted)));
        }
        if (!_closed && _writes.isEmpty) { _drained?.complete(); _drained = null; }
      } catch (_) { _fail(); }
      finally { _writing = false; }
    }());
  }
  void _fail() {
    if (_closed) return;
    if (!_incoming.isClosed) _incoming.addError(const RemoteFailure('network_transport_failed'));
    _finish(error:true);
  }
  void _finish({bool error=false}) {
    if (_closed) return;
    _closed = true; _writes.clear(); _queued = 0;
    final drain = _drained; _drained = null;
    if (drain != null && !drain.isCompleted) drain.completeError(const RemoteFailure('network_write_unknown'));
    if (!_incoming.isClosed) unawaited(_incoming.close());
    unawaited(_call('streamClose').then<void>((_) {},onError:(Object _,StackTrace __) {}));
    if (!_done.isCompleted) { if (error) { _done.completeError(const RemoteFailure('network_transport_failed')); } else { _done.complete(); } }
  }
  @override void destroy() => _finish();
  @override Future<void> close() async { _finish(); return done; }
  @override Future<void> flush() {
    final next = _flushTail.then((_) => _flushOne());
    _flushTail = next.then<void>((_) {},onError:(Object _,StackTrace __) {});
    return next;
  }
  Future<void> _flushOne() async {
    if (_closed) throw const RemoteFailure('network_transport_failed');
    // Existing writes drain before native flush; later writes wait behind it.
    _flushing = true;
    try {
      await _drained?.future;
      if (_closed) throw const RemoteFailure('network_transport_failed');
      final result = await _call('streamFlush');
      if (result is! Map || result.length != 1 || result['flushed'] != true) throw const RemoteFailure('network_write_unknown');
    } catch (_) { _fail(); rethrow; }
    finally { _flushing = false; _write(); }
  }
}

class _NetworkSink implements StreamSink<List<int>> {
  _NetworkSink(this.socket);
  final NetworkSSHSocket socket;
  bool closed = false;
  @override void add(List<int> data) => socket._add(data);
  @override void addError(Object error,[StackTrace? stackTrace]) => socket._fail();
  @override Future<void> addStream(Stream<List<int>> stream) async { await for (final data in stream) { add(data); } }
  @override Future<void> close() async { if (!closed) { closed = true; await socket.close(); } }
  @override Future<void> get done => socket.done;
}
