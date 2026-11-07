import 'dart:convert';
import 'pairing_public_key.dart';

/// Untrusted public connection details. Importing them does not grant trust.
class ConnectionProfile {
  ConnectionProfile._(this.values, this.fingerprint);
  final Map<String, dynamic> values;
  final String fingerprint;

  static ConnectionProfile parse(String text) {
    try {
      if (utf8.encode(text).isEmpty || utf8.encode(text).length > 2048) throw const FormatException();
      var at = 0;
      void ws() { while (at < text.length && ' \r\n\t'.contains(text[at])) { at++; } }
      String token(RegExp pattern) {
        ws(); final match = pattern.matchAsPrefix(text, at);
        if (match == null) throw const FormatException();
        at = match.end; return match[0]!;
      }
      final quoted = RegExp(r'"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"');
      final primitive = RegExp(r'"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"|true|false|0|[1-9][0-9]*');
      token(RegExp(r'\{'));
      final data = <String,dynamic>{};
      while (true) {
        final key = jsonDecode(token(quoted)) as String;
        if (data.containsKey(key)) throw const FormatException();
        token(RegExp(':')); data[key] = jsonDecode(token(primitive)); ws();
        if (at < text.length && text[at] == ',') { at++; continue; }
        token(RegExp(r'\}')); ws(); if (at != text.length) throw const FormatException(); break;
      }
      if (data.values.whereType<String>().any((value) => !_validUnicode(value))) throw const FormatException();
      const expected = {'version','type','host','port','username','provider','session','socketPath','herdrPath','expectedHostKey'};
      if (data.length != expected.length || !data.keys.every(expected.contains) ||
          data['version'] is! int || data['version'] != 1 || data['type'] != 'herdr-connection-profile' ||
          data['port'] is! int || data['port'] < 1 || data['port'] > 65535) throw const FormatException();
      bool matches(String key, String pattern) => data[key] is String && RegExp('^(?:$pattern)\$').hasMatch(data[key] as String);
      if (!matches('username',r'[a-z_][a-z0-9_-]{0,31}') || !matches('session',r'[A-Za-z0-9_-]{1,64}') || data['session'] == 'default' ||
          !['direct','tailscale','easytier','zerotier'].contains(data['provider'])) throw const FormatException();
      final host = data['host'];
      if (host is! String || !_validHost(host)) throw const FormatException();
      for (final key in ['socketPath','herdrPath']) {
        final path = data[key];
        if (path is! String || !_validPath(path)) throw const FormatException();
      }
      final suffix = '/herdr/sessions/${data['session']}/herdr.sock';
      if (!(data['socketPath'] as String).endsWith(suffix) || (data['socketPath'] as String).length <= suffix.length) throw const FormatException();
      if (data['expectedHostKey'] is! String) throw const FormatException();
      final fingerprint = pairingFingerprint(data['expectedHostKey'] as String);
      return ConnectionProfile._(Map.unmodifiable(data), fingerprint);
    } catch (_) { throw const FormatException('invalid_connection_profile'); }
  }
}

bool _validHost(String host) {
  if (host.isEmpty || host.length > 253) return false;
  if (host.contains(':')) {
    // URI literals also allow IPvFuture. The profile protocol accepts IPv6 only.
    if (!RegExp(r'^[0-9A-Fa-f:.]+$').hasMatch(host)) return false;
    try { return Uri.parse('http://[$host]/').host.isNotEmpty; } catch (_) { return false; }
  }
  return host.split('.').every((label) => label.length <= 63 && RegExp(r'^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$').hasMatch(label));
}

bool _validPath(String path) {
  if (!path.startsWith('/') || utf8.encode(path).length > 1024 || RegExp(r'[\x00-\x1f\x7f-\x9f]').hasMatch(path)) return false;
  return path.substring(1).split('/').every((part) => part.isNotEmpty && part != '.' && part != '..');
}

bool _validUnicode(String value) {
  final units = value.codeUnits;
  for (var i = 0; i < units.length; i++) {
    final unit = units[i];
    if (unit >= 0xd800 && unit <= 0xdbff) {
      if (++i >= units.length || units[i] < 0xdc00 || units[i] > 0xdfff) return false;
    } else if (unit >= 0xdc00 && unit <= 0xdfff) { return false; }
  }
  return true;
}
