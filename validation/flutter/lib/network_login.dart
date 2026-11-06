import 'dart:async';
import 'package:flutter/foundation.dart';
import 'network_runtime.dart';

/// One visible review of one native node. Authorization URLs live only here.
/// Polling is read-only and bounded; an unknown authorization is never replayed.
class NetworkLoginSession extends ChangeNotifier {
  NetworkLoginSession({required this.binding,required this.runtime,required this.stillCurrent,
    this.dispatchLogin,this.dispatchOpen,this.maxPolls=12,this.pollInterval=const Duration(seconds:2)});
  final NetworkNodeBinding binding;
  final NativeNetworkRuntime runtime;
  final bool Function() stillCurrent;
  final Future<NetworkLoginSnapshot> Function()? dispatchLogin;
  final Future<void> Function(String,String)? dispatchOpen;
  final int maxPolls;
  final Duration pollInterval;
  String state = 'unknown';
  String? authUrl,notice;
  String? _reviewToken;
  bool known = false,busy = false,foreground = true,authorizationRequested = false;
  bool _disposed = false;
  int _epoch = 0,_polls = 0;
  Timer? _timer;
  bool get current => !_disposed && foreground && stillCurrent() && binding.provider == 'tailscale';
  bool get canAuthorize => current && known && !busy && state == 'needs-login' && authUrl == null && !authorizationRequested;
  bool get canOpen => current && known && !busy && {'needs-login','needs-machine-auth'}.contains(state) && authUrl != null && _reviewToken != null;
  void _publish() { if (!_disposed) notifyListeners(); }
  void _cancelTimer() { _timer?.cancel(); _timer = null; }
  bool _accept(int epoch) => current && epoch == _epoch;

  void checkCurrent() {
    if (!stillCurrent()) {
      _epoch++; _cancelTimer(); authUrl = null; _reviewToken = null; known = false; busy = false;
      notice = '网络资料已变化 · 此授权审查已失效，请关闭后重新核对。'; _publish();
    }
  }
  void suspend() {
    foreground = false; _epoch++; _cancelTimer(); authUrl = null; _reviewToken = null; known = false; busy = false;
    state = 'unknown'; _publish();
  }
  Future<void> resume() async {
    if (_disposed) return;
    foreground = true;
    // Read only the original binding, even if an earlier login completed late.
    await refresh();
  }
  Future<void> refresh() async {
    if (!current || busy) return;
    _polls = 0; await _query(false);
  }
  Future<void> authorize() async {
    if (!canAuthorize) return;
    authorizationRequested = true;
    _polls = 0; await _query(true);
  }
  Future<void> _query(bool authorize) async {
    if (!current || busy) return;
    _cancelTimer(); final ticket = ++_epoch;
    busy = true; known = false; authUrl = null; _reviewToken = null; notice = null; _publish();
    try {
      final result = authorize ? await (dispatchLogin?.call() ?? runtime.login(binding)) : await runtime.loginStatus(binding);
      if (!_accept(ticket)) return;
      if (!result.binding.same(binding)) throw StateError('network_binding_changed');
      state = result.state; authUrl = result.authUrl; _reviewToken = result.reviewToken; known = true;
    } catch (_) {
      if (!_accept(ticket)) return;
      state = 'unknown'; known = false; authUrl = null; _reviewToken = null;
      notice = authorize ? '授权请求结果未确认 · 仅重新读取原节点，不会再次请求或自动打开浏览器。'
        : '原节点状态无法确认 · 不自动登录或连接，请重新读取。';
    } finally {
      if (_accept(ticket)) { busy = false; _publish(); _schedulePoll(); }
    }
  }
  void _schedulePoll() {
    if (!current || !known || !{'starting','needs-login','needs-machine-auth'}.contains(state)) return;
    if (_polls >= maxPolls) {
      notice = '本轮状态读取已暂停 · 可明确刷新；不会重复请求授权。'; _publish(); return;
    }
    _timer = Timer(pollInterval,() {
      _timer = null;
      if (!current || busy) return;
      _polls++; unawaited(_query(false));
    });
  }
  Future<void> open() async {
    if (!canOpen) return;
    final url = authUrl!,token = _reviewToken!,ticket = ++_epoch;
    _cancelTimer(); busy = true; authUrl = null; _reviewToken = null; known = false; _publish();
    try {
      await (dispatchOpen?.call(url,token) ?? runtime.openLogin(binding,url,token));
      if (_accept(ticket)) notice = '已请求打开系统浏览器 · 返回后重新读取原节点状态，SSH 仍需主动连接。';
    } catch (_) {
      if (_accept(ticket)) notice = '打开结果未确认 · 先重新读取原节点，不会重复打开链接。';
    } finally { if (_accept(ticket)) { busy = false; _publish(); } }
  }
  @override
  void dispose() { _disposed = true; _epoch++; _cancelTimer(); authUrl = null; _reviewToken = null; super.dispose(); }
}
