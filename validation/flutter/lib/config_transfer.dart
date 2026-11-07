import 'dart:convert';
import 'dart:isolate';
import 'dart:io' show InternetAddress;
import 'dart:math';
import 'package:flutter/foundation.dart' show visibleForTesting;
import 'package:flutter/services.dart';
import 'package:pointycastle/export.dart';
import 'host_catalog.dart';
import 'remote_adapter.dart';
import 'network_profiles.dart';

const maxTransferPlaintext = 65536, maxTransferArchive = 65586;
const transferTargetFields = {'host','port','username','expectedHostKey','socketPath','herdrPath','session'};

class TransferFailure implements Exception {
  const TransferFailure(this.code);
  final String code;
}

bool _portableHost(String value) {
  if (!value.contains(':')) {
    return value.split('.').every((label) => label.isNotEmpty && label.length <= 63 &&
      RegExp(r'^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$').hasMatch(label));
  }
  if (!RegExp(r'^[0-9A-Fa-f:.]+$').hasMatch(value)) return false;
  // Rust IpAddr rejects scoped/bracketed addresses and octal-looking embedded
  // IPv4 octets. Keep those envelope restrictions explicit, use the SDK for IP.
  if (value.contains('.')) {
    final octets = value.substring(value.lastIndexOf(':')+1).split('.');
    if (octets.length != 4 || octets.any((s) => !RegExp(r'^(?:0|[1-9][0-9]{0,2})$').hasMatch(s) || int.parse(s) > 255)) return false;
  }
  return InternetAddress.tryParse(value) != null;
}

class PortableHost {
  PortableHost._(this.label,this.provider,this.target,this.networkKey,this.requiresNetworkBinding);
  final String label,provider;
  final String? networkKey;
  final bool requiresNetworkBinding;
  final Map<String,dynamic> target;
  factory PortableHost.fromJson(Map<String,dynamic> value,{int version=1}) {
    if ((version == 2 ? ![4,5].contains(value.length) : value.length != 3) || !value.keys.every((version == 2 ? {'label','provider','target','networkKey','requiresNetworkBinding'} : {'label','provider','target'}).contains) ||
        (version == 2 && (!value.keys.toSet().containsAll({'label','provider','target','networkKey'}) || (value.containsKey('requiresNetworkBinding') && value['requiresNetworkBinding'] is! bool) ||
          (value['requiresNetworkBinding'] == true && (value['networkKey'] != null || !['tailscale','easytier','zerotier'].contains(value['provider']))))) ||
        (version == 2 && value['networkKey'] != null && (value['networkKey'] is! String || !RegExp(r'^[A-Za-z0-9_-]{1,32}$').hasMatch(value['networkKey'] as String))) ||
        value['label'] is! String || (value['label'] as String).trim().isEmpty ||
        utf8.encode(value['label'] as String).length > 96 ||
        utf8.decode(utf8.encode(value['label'] as String)) != value['label'] ||
        RegExp(r'[\x00-\x1f\x7f-\x9f]').hasMatch(value['label'] as String) ||
        !hostProviders.contains(value['provider']) || value['target'] is! Map<String,dynamic>) {
      throw const TransferFailure('transfer_invalid_schema');
    }
    final target = Map<String,dynamic>.from(value['target'] as Map);
    if (target.length != transferTargetFields.length || !target.keys.every(transferTargetFields.contains)) {
      throw const TransferFailure('transfer_invalid_schema');
    }
    try {
      final checked = RemoteConfig.fromJson({...target,'paneId':'','schemaVersion':1,
        'reviewConfirmed':true,'privateKeyPem':'portable-metadata-validation'});
      checked.configRoot;
      if (!_portableHost(checked.host)) throw const TransferFailure('transfer_invalid_schema');
      for (final entry in const {'host':253,'username':128,'expectedHostKey':4096,'socketPath':1024,'herdrPath':1024,'session':64}.entries) {
        final text = target[entry.key] as String, encoded = utf8.encode(target[entry.key] as String);
        if (encoded.length > entry.value || utf8.decode(encoded) != text || RegExp(r'[\x00-\x1f\x7f-\x9f]').hasMatch(text)) {
          throw const TransferFailure('transfer_invalid_schema');
        }
      }
    } catch (_) { throw const TransferFailure('transfer_invalid_schema'); }
    return PortableHost._(value['label'] as String,value['provider'] as String,Map<String,dynamic>.unmodifiable(target),value['networkKey'] as String?,value['requiresNetworkBinding'] == true);
  }
  factory PortableHost.fromProfile(HostProfile profile) {
    if (profile.networkProfileId != null || profile.requiresNetworkBinding) throw const TransferFailure('transfer_network_unavailable');
    return PortableHost.fromJson({'label':profile.label,'provider':profile.provider,'target':{for (final key in transferTargetFields) key:profile.target[key]}});
  }
  Map<String,dynamic> toJson() {
    if (requiresNetworkBinding) throw const TransferFailure('transfer_network_unavailable');
    return {'label':label,'provider':provider,'target':target};
  }
  Map<String,dynamic> toV2Json() => {'label':label,'provider':provider,'target':target,'networkKey':networkKey,if (requiresNetworkBinding) 'requiresNetworkBinding':true};
}

List<PortableHost> decodePortableHosts(Uint8List plaintext) {
  if (plaintext.isEmpty || plaintext.length > maxTransferPlaintext) throw const TransferFailure('transfer_invalid_schema');
  try {
    final data = decodeCatalogJson(utf8.decode(plaintext));
    if (data is! Map<String,dynamic> || data.length != 2 || !data.keys.every({'version','hosts'}.contains) ||
        data['version'] != 1 || data['hosts'] is! List || (data['hosts'] as List).isEmpty || (data['hosts'] as List).length > 16) {
      throw const TransferFailure('transfer_invalid_schema');
    }
    return List.unmodifiable((data['hosts'] as List).map((item) {
      if (item is! Map<String,dynamic>) throw const TransferFailure('transfer_invalid_schema');
      return PortableHost.fromJson(item);
    }));
  } catch (_) { throw const TransferFailure('transfer_invalid_schema'); }
}

Uint8List encodePortableHosts(List<PortableHost> hosts) {
  if (hosts.any((host) => host.networkKey != null || host.requiresNetworkBinding)) throw const TransferFailure('transfer_network_unavailable');
  final text = Uint8List.fromList(utf8.encode(jsonEncode({'version':1,'hosts':hosts.map((h) => h.toJson()).toList()})));
  decodePortableHosts(text); return text;
}

class PortableNetwork {
  PortableNetwork._(this.key,this.label,this.provider,this.settings);
  final String key,label,provider;
  final Map<String,dynamic> settings;
  factory PortableNetwork.fromJson(Map<String,dynamic> value) {
    if (value.length != 4 || !value.keys.every({'key','label','provider','settings'}.contains) || value['key'] is! String ||
        !RegExp(r'^[A-Za-z0-9_-]{1,32}$').hasMatch(value['key'] as String)) throw const TransferFailure('transfer_invalid_schema');
    try {
      final checked = NetworkProfile.fromJson({'id':'00000000000000000000000000000000','label':value['label'],
        'provider':value['provider'],'enabled':false,'revision':1,'settings':value['settings']});
      return PortableNetwork._(value['key'] as String,checked.label,checked.provider,checked.settings);
    } catch (_) { throw const TransferFailure('transfer_invalid_schema'); }
  }
  Map<String,dynamic> toJson() => {'key':key,'label':label,'provider':provider,'settings':settings};
}

int validateTerminalFontSize(dynamic value) {
  if (value is! int || value < 10 || value > 28) throw const TransferFailure('transfer_invalid_schema');
  return value;
}

class PortableConfig {
  PortableConfig._(this.version,this.hosts,this.networks,this.terminalFontSize);
  final int version;
  final List<PortableHost> hosts;
  final List<PortableNetwork> networks;
  final int? terminalFontSize;
  factory PortableConfig.fromJson(Map<String,dynamic> value) {
    if (value['version'] is! int) throw const TransferFailure('transfer_invalid_schema');
    if (value['version'] == 1) {
      final hosts = decodePortableHosts(Uint8List.fromList(utf8.encode(jsonEncode(value))));
      return PortableConfig._(1,hosts,const [],null);
    }
    if (value.length != 4 || !value.keys.every({'version','hosts','networks','preferences'}.contains) || value['version'] != 2 ||
        value['hosts'] is! List || (value['hosts'] as List).length > 16 || value['networks'] is! List || (value['networks'] as List).length > 16) {
      throw const TransferFailure('transfer_invalid_schema');
    }
    final hosts = <PortableHost>[],networks = <PortableNetwork>[];
    for (final item in value['networks'] as List) {
      if (item is! Map<String,dynamic>) throw const TransferFailure('transfer_invalid_schema');
      final network = PortableNetwork.fromJson(item);
      if (networks.any((n) => n.key == network.key)) throw const TransferFailure('transfer_invalid_schema');
      networks.add(network);
    }
    for (final item in value['hosts'] as List) {
      if (item is! Map<String,dynamic>) throw const TransferFailure('transfer_invalid_schema');
      final host = PortableHost.fromJson(item,version:2);
      if (host.networkKey != null && !networks.any((n) => n.key == host.networkKey && n.provider == host.provider)) throw const TransferFailure('transfer_invalid_schema');
      hosts.add(host);
    }
    int? fontSize;
    if (value['preferences'] != null) {
      final prefs = value['preferences'];
      if (prefs is! Map<String,dynamic> || prefs.length != 1 || !prefs.containsKey('terminalFontSize')) throw const TransferFailure('transfer_invalid_schema');
      fontSize = validateTerminalFontSize(prefs['terminalFontSize']);
    }
    if (hosts.isEmpty && networks.isEmpty && fontSize == null) throw const TransferFailure('transfer_invalid_schema');
    return PortableConfig._(2,List.unmodifiable(hosts),List.unmodifiable(networks),fontSize);
  }
  Map<String,dynamic> toJson() => version == 1 ? {'version':1,'hosts':hosts.map((h) => h.toJson()).toList()} :
    {'version':2,'hosts':hosts.map((h) => h.toV2Json()).toList(),'networks':networks.map((n) => n.toJson()).toList(),
      'preferences':terminalFontSize == null ? null : {'terminalFontSize':terminalFontSize}};
}
PortableConfig decodePortableConfig(Uint8List clear) {
  if (clear.isEmpty || clear.length > maxTransferPlaintext) throw const TransferFailure('transfer_invalid_schema');
  try {
    final value = decodeCatalogJson(utf8.decode(clear));
    if (value is! Map<String,dynamic>) throw const TransferFailure('transfer_invalid_schema');
    return PortableConfig.fromJson(value);
  } catch (_) { throw const TransferFailure('transfer_invalid_schema'); }
}
Uint8List encodePortableConfig(PortableConfig config) {
  final clear = Uint8List.fromList(utf8.encode(jsonEncode(config.toJson())));
  decodePortableConfig(clear); return clear;
}

Uint8List _password(String password, {bool exporting = false}) {
  final bytes = Uint8List.fromList(utf8.encode(password));
  if (bytes.isEmpty || bytes.length > 1024 || utf8.decode(bytes) != password ||
      (exporting && password.runes.length < 12)) throw const TransferFailure('transfer_invalid_password');
  return bytes;
}

void validateTransferEnvelope(Uint8List archive) {
  if (archive.length < 51 || archive.length > maxTransferArchive ||
      archive[0] != 72 || archive[1] != 80 || archive[2] != 75 || archive[3] != 84) {
    throw const TransferFailure('transfer_invalid_format');
  }
  if (archive[4] != 1 || archive[5] != 1) throw const TransferFailure('transfer_unsupported_version');
}

Uint8List _key(Uint8List password,Uint8List salt) {
  final derivator = KeyDerivator('SHA-256/HMAC/PBKDF2')..init(Pbkdf2Parameters(salt,600000,32));
  return derivator.process(password);
}

@visibleForTesting
Uint8List encryptTransferWithMaterial(String password,Uint8List plaintext,Uint8List salt,Uint8List nonce,
    {bool enforceNewPassword = true}) {
  final pass = _password(password,exporting:enforceNewPassword);
  if (salt.length != 16 || nonce.length != 12 || plaintext.isEmpty || plaintext.length > maxTransferPlaintext) {
    throw const TransferFailure('transfer_invalid_plaintext');
  }
  decodePortableConfig(plaintext);
  final header = Uint8List.fromList([72,80,75,84,1,1,...salt,...nonce]);
  final key = _key(pass,salt);
  try {
    final cipher = GCMBlockCipher(AESEngine())..init(true,AEADParameters(KeyParameter(key),128,nonce,header));
    return Uint8List.fromList([...header,...cipher.process(plaintext)]);
  } finally { key.fillRange(0,key.length,0); pass.fillRange(0,pass.length,0); }
}

Uint8List _decryptTransfer(String password,Uint8List archive) {
  validateTransferEnvelope(archive); // Bounds/version checks precede the KDF.
  final pass = _password(password), salt = Uint8List.sublistView(archive,6,22);
  final key = _key(pass,salt);
  try {
    final cipher = GCMBlockCipher(AESEngine())..init(false,AEADParameters(KeyParameter(key),128,
      Uint8List.sublistView(archive,22,34),Uint8List.sublistView(archive,0,34)));
    Uint8List clear;
    try { clear = cipher.process(Uint8List.sublistView(archive,34)); }
    catch (_) { throw const TransferFailure('transfer_auth_failed'); }
    decodePortableConfig(clear); return clear;
  } finally { key.fillRange(0,key.length,0); pass.fillRange(0,pass.length,0); }
}

Future<Uint8List> encryptConfigTransfer(String password,List<PortableHost> hosts) {
  final checked = _password(password,exporting:true); checked.fillRange(0,checked.length,0);
  final plaintext = encodePortableHosts(hosts);
  return Isolate.run(() {
    final random = Random.secure();
    final salt = Uint8List.fromList(List.generate(16,(_) => random.nextInt(256)));
    final nonce = Uint8List.fromList(List.generate(12,(_) => random.nextInt(256)));
    return encryptTransferWithMaterial(password,plaintext,salt,nonce);
  });
}

Future<List<PortableHost>> decryptConfigTransfer(String password,Uint8List archive) async {
  validateTransferEnvelope(archive);
  final checked = _password(password); checked.fillRange(0,checked.length,0);
  final copy = Uint8List.fromList(archive);
  return Isolate.run(() {
    final clear = _decryptTransfer(password,copy);
    try { return decodePortableHosts(clear); }
    finally { clear.fillRange(0,clear.length,0); }
  });
}

Future<Uint8List> encryptPortableConfig(String password,PortableConfig config) {
  final checked = _password(password,exporting:true); checked.fillRange(0,checked.length,0);
  final clear = encodePortableConfig(config);
  return Isolate.run(() {
    final random = Random.secure();
    return encryptTransferWithMaterial(password,clear,Uint8List.fromList(List.generate(16,(_) => random.nextInt(256))),
      Uint8List.fromList(List.generate(12,(_) => random.nextInt(256))));
  });
}
Future<PortableConfig> decryptPortableConfig(String password,Uint8List archive) async {
  validateTransferEnvelope(archive);
  final checked = _password(password); checked.fillRange(0,checked.length,0);
  final copy = Uint8List.fromList(archive);
  return Isolate.run(() {
    final clear = _decryptTransfer(password,copy);
    try { return decodePortableConfig(clear); } finally { clear.fillRange(0,clear.length,0); }
  });
}

abstract interface class ConfigDocuments {
  Future<Uint8List?> open();
  Future<bool> save(Uint8List archive);
}
class NativeConfigDocuments implements ConfigDocuments {
  static const channel = MethodChannel('herdr.pocket/config_document');
  @override Future<Uint8List?> open() => channel.invokeMethod<Uint8List>('open');
  @override Future<bool> save(Uint8List archive) async => await channel.invokeMethod<bool>('save',archive) == true;
}
