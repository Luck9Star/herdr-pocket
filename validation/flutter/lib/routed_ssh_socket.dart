/// Actual route accompanies the stream; callers must not fabricate it from GUI state.
/// Pure Dart so the headless CLI probe never pulls in Flutter bindings.
abstract interface class RoutedSSHSocket { String get actualRoute; }

/// Managed transports acknowledge native retirement separately from local EOF.
/// False retains an unknown cleanup result without crossing error-zone boundaries.
abstract interface class RetiringSSHSocket { Future<bool> get retired; }

/// Explicit user shutdown preserves reads for peer EOF before forced retirement.
/// True proves that EOF arrived within budget; native retirement is separate.
abstract interface class GracefulSSHSocket {
  Future<bool> finishGracefully({Duration budget = const Duration(seconds:1)});
}
