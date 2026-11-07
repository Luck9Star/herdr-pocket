/// Stable safe codes only: never include server output, config or private keys.
class RemoteFailure implements Exception {
  const RemoteFailure(this.code);
  final String code;
  @override
  String toString() => 'RemoteFailure($code)';
}
