import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'design_tokens.dart';
import 'device_keys.dart';
import 'pairing.dart';
import 'remote_adapter.dart';
import 'remote_page.dart';

/// Public request/response review. Native identity creation is always explicit;
/// missing/locked storage has no fallback, and responses never establish SSH trust.
class PairingPage extends StatefulWidget {
  const PairingPage({super.key,required this.tokens,this.keys,this.adapter,this.onRequest,this.clock});
  final DesignTokens tokens;
  final DeviceKeys? keys;
  final RemoteReadOnlyAdapter? adapter;
  final void Function(Map<String,dynamic>)? onRequest;
  static PendingDevicePairing? retainedPairing;
  static Map<String,dynamic>? retainedTarget;
  static String? retainedOrphan;
  static bool retainedCreationUnknown = false;
  @visibleForTesting
  static void resetMemorySession() { retainedPairing = null; retainedTarget = null; retainedOrphan = null; retainedCreationUnknown = false; }
  final int Function()? clock;
  @override
  State<PairingPage> createState() => _PairingPageState();
}
class _PairingPageState extends State<PairingPage> with WidgetsBindingObserver {
  late final keys = widget.keys ?? NativeDeviceKeys();
  final fields = <String,TextEditingController>{
    for (final name in ['host','port','username','expectedHostKey','socketPath','herdrPath','session','device'])
      name:TextEditingController(text:name == 'port' ? '22' : name == 'device' ? 'Pocket phone' : ''),
  };
  final response = TextEditingController();
  PendingDevicePairing? pairing;
  Map<String,dynamic>? target;
  bool busy = false, targetReviewed = false, sourceReviewed = false;
  bool creationUnknown = false;
  bool get platformAvailable => widget.keys != null || (!kIsWeb && [TargetPlatform.android,TargetPlatform.iOS,TargetPlatform.macOS].contains(defaultTargetPlatform));
  String status = '先审查目标，再由此设备生成独立身份。仅公开请求可以交给主机。';
  int revision = 0;
  Timer? timer;
  Map<String,dynamic>? responsePreview;
  int get now => widget.clock?.call() ?? DateTime.now().millisecondsSinceEpoch ~/ 1000;
  @override
  void initState() {
    super.initState(); WidgetsBinding.instance.addObserver(this);
    pairing = PairingPage.retainedPairing; target = PairingPage.retainedTarget;
    creationUnknown = PairingPage.retainedCreationUnknown;
    if (pairing != null) status = '已恢复本进程保留的原身份 · 不会重新创建；请核验状态或明确删除';
    if (creationUnknown) status = '上次身份创建或清理结果未知 · 不会重放创建；可删除已返回的原身份引用';
    timer = Timer.periodic(const Duration(seconds:1),(_) {
      final p = pairing; if (p == null) return;
      final previous = p.state; p.tick(now);
      if (mounted && p.state != previous) setState(() { status = '请求已到期 · 授权结果仍未知，不会重放请求'; });
    });
  }
  void invalidate([String message = '已取消等待 · 主机授权可能已发生；取消不等于撤销']) {
    revision++;
    final p = pairing;
    if (p != null) {
      if (['awaiting-host','authorized-unverified'].contains(p.state)) p.cancel();
      if (['connecting','paired'].contains(p.state)) { p.generation++; p.state = 'waiting-connectivity'; }
    }
    if (mounted) setState(() { busy = false; targetReviewed = false; sourceReviewed = false; status = message; });
  }
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed) invalidate('应用已暂停 · 不会自动重建身份、重放授权或重连');
  }
  @override
  void dispose() {
    revision++; timer?.cancel(); WidgetsBinding.instance.removeObserver(this);
    pairing?.cancel(); for (final field in fields.values) { field.dispose(); } response.dispose(); super.dispose();
  }
  Future<void> create() async {
    if (busy || pairing != null || !targetReviewed || creationUnknown || !platformAvailable) return;
    final ticket = ++revision;
    String? handle;
    var createStarted = false;
    setState(() { busy = true; sourceReviewed = false; });
    try {
      final values = <String,dynamic>{'schemaVersion':1,'reviewConfirmed':true,'paneId':'',
        for (final e in fields.entries) if (e.key != 'port' && e.key != 'device') e.key:e.value.text,
        'port':int.tryParse(fields['port']!.text)};
      final checked = RemoteConfig.fromJson({...values,'privateKeyPem':'validation-only'});
      checked.configRoot; // reject target/socket mismatch before creating an identity
      final device = fields['device']!.text;
      if (!RegExp(r'^[A-Za-z0-9 -]{1,48}$').hasMatch(device)) throw const RemoteFailure('invalid_pairing');
      createStarted = true;
      handle = await keys.create();
      PairingPage.retainedOrphan = handle;
      final publicKey = await keys.public(handle);
      if (!mounted || ticket != revision) {
        try { await keys.delete(handle); PairingPage.retainedOrphan = null; } catch (_) { PairingPage.retainedCreationUnknown = true; }
        return;
      }
      final p = PendingDevicePairing(handle:handle,publicKey:publicKey,account:checked.username,
        hostKey:checked.expectedFingerprint,device:device,now:now);
      PairingPage.retainedPairing = p; PairingPage.retainedTarget = Map.unmodifiable(values); PairingPage.retainedOrphan = null;
      setState(() { pairing = p; target = Map.unmodifiable(values); busy = false; targetReviewed = false;
        status = '等待主机审查 · 授权结果未知；公开请求有效 600 秒'; });
      widget.onRequest?.call(Map.unmodifiable(p.request));
    } catch (_) {
      if (handle != null) { try { await keys.delete(handle); PairingPage.retainedOrphan = null; } catch (_) { PairingPage.retainedOrphan = handle; } }
      PairingPage.retainedCreationUnknown = createStarted;
      if (mounted && ticket == revision) setState(() { busy = false; targetReviewed = false;
        creationUnknown = createStarted;
        status = createStarted ? '设备安全存储不可用或创建结果未知 · 禁止重放创建；已有引用可明确删除，不会使用明文' : '目标无效 · 未创建设备身份'; });
    }
  }
  void accept() {
    final p = pairing; if (p == null || busy) return;
    try {
      p.accept(response.text,now:now,reviewed:sourceReviewed);
      setState(() { sourceReviewed = false; response.clear(); responsePreview = null; status = p.state == 'revoked'
        ? '已审查匹配的主机撤销响应 · 此请求不能再授权' : '主机报告已授权 · 尚未验证 SSH，需主动连接'; });
    } catch (_) { setState(() { sourceReviewed = false; status = '响应无效、过期、重放或绑定不符 · 未接受'; }); }
  }
  Future<void> connect() async {
    final p = pairing; if (p == null || busy) return;
    var ticket = p.generation;
    setState(() { busy = true; status = '请在连接页再次审查冻结目标；只有实际 pin 与 SSH 认证成功才标记已配对'; });
    await Navigator.push<void>(context,MaterialPageRoute(builder:(_) => RemotePage(tokens:widget.tokens,
      adapter:widget.adapter,pairedTarget:target,deviceKeys:keys,keyHandle:p.handle,
      devicePublicKey:p.request['public_key'] as String,onConnecting:() { ticket = p.connect(); },onAuthenticated:() { p.connectionResult(ticket,true); if (mounted) setState(() {}); },
      onStopped:() { if (['connecting','paired'].contains(p.state)) { p.generation++; p.state = 'waiting-connectivity'; } })));
    if (!mounted) return;
    if (p.state == 'connecting') p.connectionResult(ticket,false);
    setState(() { busy = false; status = '连接已停止 · ${p.state}；只能主动重新审查连接'; });
  }
  Future<void> delete() async {
    final p = pairing; if (p == null || busy) return;
    invalidate(); final ticket = revision;
    setState(() { busy = true; });
    try {
      await keys.delete(p.handle);
      if (!mounted || ticket != revision) return;
      PairingPage.resetMemorySession();
      setState(() { busy = false; pairing = null; target = null; creationUnknown = false; response.clear(); responsePreview = null; status = '本机身份已删除 · 主机授权未因此撤销；需要新配对时请明确创建'; });
    } catch (_) {
      if (mounted && ticket == revision) setState(() { busy = false; status = '密钥删除未确认 · 保留原身份引用，不会自动替换；主机授权仍需核验撤销'; });
    }
  }
  Future<void> deleteOrphan() async {
    final handle = PairingPage.retainedOrphan; if (handle == null || busy) return;
    setState(() { busy = true; });
    try {
      await keys.delete(handle); PairingPage.resetMemorySession();
      if (mounted) setState(() { busy = false; creationUnknown = false; status = '原身份已删除 · 主机授权不因此撤销'; });
    } catch (_) { if (mounted) setState(() { busy = false; status = '原身份删除未确认 · 已保留引用；不自动替换'; }); }
  }
  void previewResponse() {
    Map<String,dynamic>? preview;
    try { preview = decodePairing(Uint8List.fromList(utf8.encode(response.text)),now); } catch (_) { /* invalid is not trusted */ }
    setState(() { sourceReviewed = false; responsePreview = preview; });
  }
  Widget input(String name,String label) => Padding(padding:const EdgeInsets.only(bottom:12),
    child:TextField(key:ValueKey('pair-$name'),controller:fields[name],enabled:!busy && pairing == null,
      autocorrect:false,maxLength:name == 'expectedHostKey' ? 4096 : 1024,decoration:InputDecoration(labelText:label,counterText:''),
      onChanged:(_) { revision++; setState(() { targetReviewed = false; }); }));
  @override
  Widget build(BuildContext context) {
    final p = pairing;
    return Scaffold(appBar:AppBar(title:const Text('设备配对 · 公开请求')),
      body:SafeArea(child:SingleChildScrollView(padding:const EdgeInsets.all(16),child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
        Semantics(liveRegion:true,child:Text(status,key:const ValueKey('pair-status'))),
        const SizedBox(height:12),
        if (!platformAvailable) const Text('此平台的设备安全存储桥不可用 · 设备配对已禁用，可返回手动隔离实验'),
        if (PairingPage.retainedOrphan != null) TextButton(key:const ValueKey('pair-delete-orphan'),onPressed:busy ? null : deleteOrphan,child:const Text('明确删除原身份引用')),
        if (p == null) ...[
          input('host','SSH 主机 / IP'), input('port','SSH 端口'), input('username','主机账号'),
          input('session','命名会话（非 default）'), input('socketPath','命名会话 socket 绝对路径'),
          input('herdrPath','herdr 可执行文件绝对路径'), input('expectedHostKey','可信渠道核验的 Ed25519 主机公钥'), input('device','设备名称（英文、数字、空格）'),
          CheckboxListTile(key:const ValueKey('pair-target-review'),value:targetReviewed,
            onChanged:busy ? null : (value) => setState(() { targetReviewed = value == true; }),
            title:const Text('我已通过可信渠道核验账号、主机公钥与命名会话资料')),
          FilledButton(key:const ValueKey('pair-create'),onPressed:targetReviewed && !busy && !creationUnknown && platformAvailable ? create : null,
            child:const Text('在此设备创建独立身份并生成公开请求')),
        ] else ...[
          Text('状态 ${p.state} · 主机授权 ${p.authorization}',key:const ValueKey('pair-state')),
          Text('账号 ${p.request['account']}\n主机 ${p.request['host_key']}\n设备 ${pairingFingerprint(p.request['public_key'] as String)}\n到期 ${p.request['expires_at']}'),
          const SizedBox(height:12), SelectableText(p.wire,key:const ValueKey('pair-request')),
          TextButton(key:const ValueKey('pair-copy'),onPressed:() => Clipboard.setData(ClipboardData(text:p.wire)),child:const Text('复制公开请求')),
          const Text('响应本身没有来源认证。请独立核验主机生成的响应来源、账号与两端指纹；粘贴不等于信任。'),
          TextField(key:const ValueKey('pair-response'),controller:response,enabled:!busy,maxLength:2048,minLines:3,maxLines:6,
            decoration:const InputDecoration(labelText:'公开授权／撤销响应 JSON'),onChanged:(_) => previewResponse()),
          if (responsePreview != null) Text('待审查响应\n账号 ${responsePreview!['account']}\n主机 ${responsePreview!['host_key']}\n设备 ${responsePreview!['fingerprint']}\n状态 ${responsePreview!['status']} · 新增授权 ${responsePreview!['authorization_added']}\n期限 ${responsePreview!['issued_at']} → ${responsePreview!['expires_at']}',key:const ValueKey('pair-response-preview')),
          CheckboxListTile(key:const ValueKey('pair-source-review'),value:sourceReviewed,
            onChanged:busy ? null : (v) => setState(() { sourceReviewed = v == true; }),title:const Text('我已独立核验响应来源、账号与两端指纹')),
          FilledButton(key:const ValueKey('pair-accept'),onPressed:sourceReviewed && !busy ? accept : null,child:const Text('审查并接受绑定响应')),
          if (['authorized-unverified','waiting-connectivity','paired'].contains(p.state)) FilledButton(
            key:const ValueKey('pair-connect'),onPressed:busy ? null : connect,child:const Text('主动审查连接并读取看板')),
          TextButton(key:const ValueKey('pair-cancel'),onPressed:busy ? null : invalidate,child:const Text('取消等待（不撤销主机授权）')),
          TextButton(key:const ValueKey('pair-delete'),onPressed:busy ? null : delete,child:const Text('删除本机身份（不撤销主机授权）')),
        ],
      ]))));
  }
}
