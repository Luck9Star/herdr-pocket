/// Actual route accompanies the stream; callers must not fabricate it from GUI state.
/// Pure Dart so the headless CLI probe never pulls in Flutter bindings.
abstract interface class RoutedSSHSocket { String get actualRoute; }
