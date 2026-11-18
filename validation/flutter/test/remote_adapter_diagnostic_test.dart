import 'dart:async';
import 'package:dartssh2/dartssh2.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';

void main() {
  test('channel denial is bounded and only classified at initial snapshot open', () {
    final denied = SSHChannelOpenError(1, 'private address and arbitrary server description');
    expect(remoteDiagnosticErrorKind(denied), 'ssh_channel_open');
    expect(remoteInitialFailureCode(denied, 'snapshot_forward_open'), 'snapshot_forward_denied');
    expect(remoteInitialFailureCode(denied, 'capabilities_forward_open'), 'connection_failed');
    expect(remoteInitialFailureCode(SSHChannelOpenError(2, 'private'), 'snapshot_forward_open'), 'connection_failed');
    expect(remoteInitialFailureCode(denied, 'snapshot_forward_open', previous:'host_key_mismatch'), 'host_key_mismatch');
    expect(remoteDiagnosticErrorKind(TimeoutException('private')), 'timeout');
    expect(remoteDiagnosticErrorKind(StateError('private')), 'state_error');
    expect(remoteDiagnosticErrorKind(Exception('private')), 'other');
  });
}
