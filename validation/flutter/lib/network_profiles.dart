import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';
import 'package:flutter/foundation.dart' show Listenable;
import 'package:pointycastle/digests/sha256.dart';
import 'remote_adapter.dart';

const maxNetworkProfiles = 32;
const overlayProviders = ['tailscale','easytier','zerotier'];
const maxNetworkRevision = 2147483647;
const defaultTailscaleControlUrl = 'https://controlplane.tailscale.com';
const defaultTailscaleHostname = 'herdr-pocket';

bool _tailscaleDnsLabel(String value,{bool limitLength=true}) =>
  value.isNotEmpty && (!limitLength || value.length <= 63) &&
  RegExp(r'^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$').hasMatch(value);

/// Shared authority rules; control settings additionally limit each DNS label.
/// Read the raw spelling so URI normalization cannot erase an invalid port.
bool isValidTailscaleAuthority(String authority,{bool limitLabelLength=true,int? maxLength}) {
  if (authority.isEmpty || (maxLength != null && authority.length > maxLength) ||
      RegExp(r'[@%\[\]]').hasMatch(authority)) return false;
  final separator = authority.lastIndexOf(':');
  final host = separator < 0 ? authority : authority.substring(0,separator);
  if (host.isEmpty || host.length > 253 ||
      host.split('.').any((label) => !_tailscaleDnsLabel(label,limitLength:limitLabelLength))) return false;
  if (separator >= 0) {
    final rawPort = authority.substring(separator+1);
    if (!RegExp(r'^[0-9]+$').hasMatch(rawPort)) return false;
    final port = int.tryParse(rawPort);
    if (port == null || port < 1 || port > 65535) return false;
  }
  return true;
}

/// Mirrors shared TailscaleSettings before save/import, preserving URL bytes.
bool isValidTailscaleControlUrl(String value) {
  if (value.length > 2048 || !value.startsWith('https://') ||
      !RegExp(r'^[\x21-\x7e]+$').hasMatch(value) || RegExp(r'[\\?#]').hasMatch(value) ||
      RegExp(r'%(?![0-9A-Fa-f]{2})').hasMatch(value)) return false;
  final authority = value.substring(8).split('/').first;
  return isValidTailscaleAuthority(authority) && _publicUri(value,{'https'}) != null;
}

/// Public configuration, using the same defaults and byte sequence as native.
/// No URI normalization: a reviewed spelling is part of the binding identity.
Map<String,String> tailscaleEffectiveSettings(NetworkProfile profile) {
  if (profile.provider != 'tailscale') throw const RemoteFailure('invalid_network_profile');
  return Map<String,String>.unmodifiable({
    'controlUrl':profile.settings['controlUrl'] == '' ? defaultTailscaleControlUrl : profile.settings['controlUrl'] as String,
    'hostname':profile.settings['hostname'] == '' ? defaultTailscaleHostname : profile.settings['hostname'] as String,
  });
}

String tailscaleNetworkName(NetworkProfile profile) {
  final settings = tailscaleEffectiveSettings(profile);
  final bytes = Uint8List.fromList(utf8.encode('herdr-tailscale-config-v1\u0000${settings['controlUrl']}\u0000${settings['hostname']}'));
  return 'ts1:${SHA256Digest().process(bytes).map((b) => b.toRadixString(16).padLeft(2,'0')).join()}';
}

bool _publicText(dynamic value,int limit,{bool empty=false}) => value is String &&
  (empty || value.trim().isNotEmpty) && utf8.encode(value).length <= limit &&
  utf8.decode(utf8.encode(value)) == value && !RegExp(r'[\x00-\x1f\x7f-\x9f]').hasMatch(value);

Uri? _publicUri(dynamic value,Set<String> schemes) {
  if (value is! String || value.length > 2048 || value.contains('?') || value.contains('#') || value.contains('\\') || !RegExp(r'^[\x21-\x7e]+$').hasMatch(value)) return null;
  try {
    // Uri can normalize an explicit :0 away for schemes without a registered
    // default port. Check the original authority before parsing/normalization.
    final separator = value.indexOf('://');
    if (separator >= 0) {
      final start = separator+3,end = value.indexOf('/',start);
      final authority = value.substring(start,end < 0 ? value.length : end);
      if (RegExp(r':0+$').hasMatch(authority)) return null;
    }
    final uri = Uri.parse(value);
    if (!schemes.contains(uri.scheme) || !uri.hasAuthority || uri.host.isEmpty || uri.authority.contains('@') || uri.userInfo.isNotEmpty ||
        uri.hasQuery || uri.hasFragment || (uri.hasPort && (uri.port < 1 || uri.port > 65535))) return null;
    return uri;
  } catch (_) { return null; }
}

/// Public descriptions only. No provider identity, join secret or SSH key is
/// accepted by this schema; an overlay description cannot enable TCP fallback.
class NetworkProfile {
  NetworkProfile._(this.id,this.label,this.provider,this.enabled,this.revision,this.settings,[this.expectedPrevious]);
  final String id,label,provider;
  final bool enabled;
  final int revision;
  final Map<String,dynamic> settings;
  final String? expectedPrevious;
  factory NetworkProfile.fromJson(Map<String,dynamic> value) {
    const fields = {'id','label','provider','enabled','revision','settings'};
    if (value.length != fields.length || !value.keys.every(fields.contains) || value['id'] is! String ||
        !RegExp(r'^[a-f0-9]{32}$').hasMatch(value['id'] as String) || !_publicText(value['label'],96) ||
        !overlayProviders.contains(value['provider']) || value['enabled'] is! bool || value['revision'] is! int ||
        (value['revision'] as int) < 1 || (value['revision'] as int) > maxNetworkRevision ||
        value['settings'] is! Map<String,dynamic>) throw const RemoteFailure('invalid_network_profile');
    final settings = Map<String,dynamic>.from(value['settings'] as Map);
    bool exact(Set<String> names) => settings.length == names.length && settings.keys.every(names.contains);
    switch (value['provider']) {
      case 'tailscale':
        if (!exact({'controlUrl','hostname'}) || settings['controlUrl'] is! String || settings['hostname'] is! String ||
            (settings['controlUrl'] != '' && !isValidTailscaleControlUrl(settings['controlUrl'] as String)) ||
            (settings['hostname'] != '' && !_tailscaleDnsLabel(settings['hostname'] as String))) {
          throw const RemoteFailure('invalid_network_profile');
        }
      case 'easytier':
        if (!exact({'networkName','peers'}) || !_publicText(settings['networkName'],64) || settings['peers'] is! List ||
            (settings['peers'] as List).isEmpty || (settings['peers'] as List).length > 16) throw const RemoteFailure('invalid_network_profile');
        final peers = settings['peers'] as List;
        if (peers.toSet().length != peers.length) throw const RemoteFailure('invalid_network_profile');
        for (final value in peers) {
          final uri = _publicUri(value,{'tcp','udp','ws','wss'});
          if (uri == null || (['tcp','udp'].contains(uri.scheme) &&
              (!uri.hasPort || (uri.path.isNotEmpty && uri.path != '/')))) throw const RemoteFailure('invalid_network_profile');
        }
        settings['peers'] = List<String>.unmodifiable(peers.cast<String>());
      case 'zerotier':
        if (!exact({'networkId'}) || settings['networkId'] is! String ||
            !RegExp(r'^[a-f0-9]{16}$').hasMatch(settings['networkId'] as String) || settings['networkId'] == '0000000000000000') {
          throw const RemoteFailure('invalid_network_profile');
        }
    }
    return NetworkProfile._(value['id'] as String,value['label'] as String,value['provider'] as String,
      value['enabled'] as bool,value['revision'] as int,Map<String,dynamic>.unmodifiable(settings));
  }
  factory NetworkProfile.create(String label,String provider,Map<String,dynamic> settings) {
    final random = Random.secure();
    return NetworkProfile.fromJson({'id':List.generate(16,(_) => random.nextInt(256).toRadixString(16).padLeft(2,'0')).join(),
      'label':label,'provider':provider,'enabled':true,'revision':1,'settings':settings});
  }
  Map<String,dynamic> toJson() => {'id':id,'label':label,'provider':provider,'enabled':enabled,'revision':revision,'settings':settings};
  NetworkProfile change({String? label,bool? enabled,Map<String,dynamic>? settings}) {
    if (revision == maxNetworkRevision) throw const RemoteFailure('network_revision_limit');
    final checked = NetworkProfile.fromJson({...toJson(),'revision':revision+1,
      if (label != null) 'label':label,if (enabled != null) 'enabled':enabled,if (settings != null) 'settings':settings});
    return NetworkProfile._(checked.id,checked.label,checked.provider,checked.enabled,checked.revision,checked.settings,jsonEncode(toJson()));
  }
}

/// A connection freezes one explicit provider revision. Readiness must come
/// from the native provider and exact local identity, never a GUI label.
class NetworkConnectionBinding {
  const NetworkConnectionBinding(this.profile,this.stillCurrent,{this.changes,this.fontSize});
  final NetworkProfile? profile;
  final bool Function() stillCurrent;
  final Listenable? changes;
  final int Function()? fontSize;
  int get terminalFontSize => fontSize?.call() ?? 14;
  String get label => profile == null ? '系统直连（沿用系统路由）' : '${profile!.label} · ${profile!.provider}';
  void requireTransport({bool overlayReady=false}) {
    if (!stillCurrent()) throw const RemoteFailure('network_binding_changed');
    if (profile != null && (!overlayReady || !profile!.enabled || !{'easytier','tailscale'}.contains(profile!.provider))) throw const RemoteFailure('provider_unavailable');
  }
}
