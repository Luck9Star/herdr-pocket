import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'design_tokens.dart';
import 'device_keys.dart';
import 'host_catalog.dart';
import 'pairing.dart';
import 'remote_adapter.dart';
import 'remote_page.dart';

/// Public request/response review. Native identity creation is always explicit;
/// missing/locked storage has no fallback, and responses never establish SSH trust.
class PairingPage extends StatefulWidget {
  const PairingPage({super.key,required this.tokens,this.keys,this.adapter,this.onRequest,this.clock,this.catalog,this.profileId,this.visibility});
  final DesignTokens tokens;
  final DeviceKeys? keys;
  final HostCatalog? catalog;
  final String? profileId;
  final ValueListenable<bool>? visibility;
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
  HostProfile? savedProfile;
  bool profileBlocked = false,identityAvailable = true;
  Map<String,dynamic>? target;
  bool busy = false, targetReviewed = false, sourceReviewed = false;
  bool creationUnknown = false,scanning = false;
  String provider = 'unspecified';
  bool get pageVisible => widget.visibility?.value ?? true;
  bool get scanAvailable => !kIsWeb && [TargetPlatform.android,TargetPlatform.iOS].contains(defaultTargetPlatform);
  bool get platformAvailable => widget.keys != null || (!kIsWeb && [TargetPlatform.android,TargetPlatform.iOS,TargetPlatform.macOS].contains(defaultTargetPlatform));
  String status = '先审查目标，再由此设备生成独立身份。仅公开请求可以交给主机。';
  int revision = 0;
  Timer? timer;
  Map<String,dynamic>? responsePreview;
  int get now => widget.clock?.call() ?? DateTime.now().millisecondsSinceEpoch ~/ 1000;
  @override
  void initState() {
    super.initState(); WidgetsBinding.instance.addObserver(this); widget.visibility?.addListener(visibilityChanged);
    if (widget.catalog != null) {
      final catalog = widget.catalog!;
      if (!catalog.ready || (widget.profileId == null && catalog.pendingCreation != null)) {
        profileBlocked = true; status = '目录不可用或上次创建结果未知 · 禁止创建替代身份，请从主机页核验';
      } else if (widget.profileId != null) {
        final matches = catalog.profiles.where((p) => p.id == widget.profileId && p.enabled).toList();
        if (matches.length != 1) { profileBlocked = true; status = '指定主机资料不存在或已停用 · 不回退其他主机'; }
        else {
          savedProfile = matches.single; provider = savedProfile!.provider; target = savedProfile!.target;
          if (savedProfile!.hasIdentity) {
            pairing = savedProfile!.restore(now); identityAvailable = false;
            status = '已恢复原主机与设备身份 · 正在核验本机句柄；不会自动连接';
            unawaited(checkExistingIdentity());
          } else {
            for (final entry in fields.entries) {
              if (target![entry.key] != null) entry.value.text = target![entry.key].toString();
            }
            profileBlocked = catalog.pendingCreation != null;
            status = profileBlocked ? '上次创建结果待核实 · 禁止创建替代身份'
              : '已导入公开连接资料 · 未带入信任或设备身份；核验目标后在此设备明确创建新配对';
          }
        }
      }
    } else {
      pairing = PairingPage.retainedPairing; target = PairingPage.retainedTarget;
      creationUnknown = PairingPage.retainedCreationUnknown;
      if (pairing != null) status = '已恢复本进程保留的原身份 · 不会重新创建；请核验状态或明确删除';
      if (creationUnknown) status = '上次身份创建或清理结果未知 · 不会重放创建；可删除已返回的原身份引用';
    }
    timer = Timer.periodic(const Duration(seconds:1),(_) {
      final p = pairing; if (p == null) return;
      final previous = p.state; p.tick(now);
      if (mounted && p.state != previous) setState(() { status = '请求已到期 · 授权结果仍未知，不会重放请求'; });
    });
  }
  void cancelWaiting() {
    revision++; scanning = false;
    final p = pairing;
    if (p != null) {
      if (['awaiting-host','authorized-unverified'].contains(p.state)) p.cancel();
      if (['connecting','paired'].contains(p.state)) { p.generation++; p.state = 'waiting-connectivity'; }
    }
    if (widget.catalog != null && savedProfile != null) unawaited(persistPairing().catchError((Object _) {}));
    if (mounted) setState(() { busy = false; targetReviewed = false; sourceReviewed = false; status = '已取消等待 · 主机授权可能已发生，请在主机核验'; });
  }
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (scanning) return; // The OS may pause this activity for its own scanner.
    if (state == AppLifecycleState.resumed) {
      if (pageVisible && pairing != null && !profileBlocked) unawaited(checkExistingIdentity());
      return;
    }
    pauseReview('应用已暂停 · 保留原请求，返回后重新核验设备与响应来源');
  }
  @override
  void dispose() {
    revision++; timer?.cancel(); widget.visibility?.removeListener(visibilityChanged); WidgetsBinding.instance.removeObserver(this);
    if (widget.catalog == null) pairing?.cancel(); for (final field in fields.values) { field.dispose(); } response.dispose(); super.dispose();
  }
  Future<void> create() async {
    if (busy || pairing != null || !targetReviewed || creationUnknown || profileBlocked || !pageVisible || !platformAvailable) return;
    final ticket = ++revision;
    String? handle;
    var createStarted = false;
    var phase = '核验连接资料';
    setState(() { busy = true; sourceReviewed = false; });
    try {
      final values = <String,dynamic>{'schemaVersion':1,'reviewConfirmed':true,'paneId':'',
        for (final e in fields.entries) if (e.key != 'port' && e.key != 'device') e.key:e.value.text,
        'port':int.tryParse(fields['port']!.text)};
      final checked = RemoteConfig.fromJson({...values,'privateKeyPem':'validation-only'});
      checked.configRoot; // reject target/socket mismatch before creating an identity
      final device = fields['device']!.text;
      if (!RegExp(r'^[A-Za-z0-9 -]{1,48}$').hasMatch(device)) throw const RemoteFailure('invalid_pairing');
      final fullLabel = '${checked.host} / ${checked.session}';
      final label = savedProfile?.label ?? (fullLabel.length > 64 ? fullLabel.substring(0,64) : fullLabel);
      if (widget.catalog != null) {
        phase = '保存创建意图';
        await widget.catalog!.beginCreation(values,label,sourceProfileId:savedProfile?.hasIdentity == false ? savedProfile!.id : null);
        if (!mounted || ticket != revision) { await widget.catalog!.clearUnstartedCreation(widget.catalog!.pendingCreation!['id'] as String); return; }
      }
      createStarted = true; PairingPage.retainedCreationUnknown = true;
      phase = '创建设备身份';
      handle = await keys.create();
      PairingPage.retainedOrphan = handle;
      if (widget.catalog != null) {
        phase = '保存本机密钥引用';
        await widget.catalog!.recordCreatedHandle(handle);
      }
      phase = '读取设备公钥';
      final publicKey = await keys.public(handle);
      if (!mounted || ticket != revision) {
        try { await keys.delete(handle); if (widget.catalog?.pendingCreation?['handle'] == handle) await widget.catalog!.clearDeletedCreation(handle); if (PairingPage.retainedOrphan == handle) { PairingPage.retainedOrphan = null; PairingPage.retainedCreationUnknown = false; } } catch (_) { PairingPage.retainedCreationUnknown = true; }
        return;
      }
      final p = PendingDevicePairing(handle:handle,publicKey:publicKey,account:checked.username,
        hostKey:checked.expectedFingerprint,device:device,now:now);
      if (widget.catalog != null) {
        phase = '保存主机资料';
        final profile = HostProfile.create(label,values,p,now,provider:provider);
        await widget.catalog!.completeCreation(profile); savedProfile = profile;
        if (!mounted || ticket != revision) return;
      }
      PairingPage.retainedPairing = p; PairingPage.retainedTarget = Map.unmodifiable(values); PairingPage.retainedOrphan = null; PairingPage.retainedCreationUnknown = false;
      setState(() { pairing = p; identityAvailable = true; target = Map.unmodifiable(values); busy = false; targetReviewed = false;
        status = '等待主机审查 · 授权结果未知；公开请求有效 600 秒'; });
      widget.onRequest?.call(Map.unmodifiable(p.request));
    } catch (_) {
      if (handle != null && (savedProfile == null || !savedProfile!.hasIdentity)) { try { await keys.delete(handle); if (widget.catalog?.pendingCreation?['handle'] == handle) await widget.catalog!.clearDeletedCreation(handle); PairingPage.retainedOrphan = null; } catch (_) { PairingPage.retainedOrphan = handle; } }
      PairingPage.retainedCreationUnknown = createStarted;
      if (mounted && ticket == revision) setState(() { busy = false; targetReviewed = false;
        creationUnknown = createStarted;
        status = createStarted ? '${phase}未完成 · 设备安全存储不可用或创建结果未知 · 请核验原身份，不会重放创建' : '${phase}未完成 · 未创建设备身份'; });
    }
  }
  Future<void> accept() async {
    final p = pairing; if (p == null || busy || scanning || !pageVisible || profileBlocked || widget.catalog?.ready == false) return;
    final ticket = revision;
    setState(() { busy = true; });
    try {
      p.accept(response.text,now:now,reviewed:sourceReviewed);
      await persistPairing();
      if (!mounted || ticket != revision) return;
      setState(() { busy = false; sourceReviewed = false; response.clear(); responsePreview = null; status = p.state == 'revoked'
        ? '已审查匹配的主机撤销响应 · 此请求不能再授权' : '主机报告已授权 · 尚未验证 SSH，需主动连接'; });
    } catch (_) { if (mounted && ticket == revision) setState(() { busy = false; sourceReviewed = false; status = '响应无效或保存未确认 · 已停止；请核验目录与绑定，不重放'; }); }
  }
  Future<void> connect() async {
    final p = pairing; if (p == null || busy || scanning || !pageVisible || !identityAvailable || profileBlocked || widget.catalog?.ready == false || savedProfile?.enabled == false) return;
    var ticket = p.generation;
    setState(() { busy = true; status = '请在连接页再次审查冻结目标；只有实际 pin 与 SSH 认证成功才标记已配对'; });
    await Navigator.push<void>(context,MaterialPageRoute(builder:(_) => RemotePage(tokens:widget.tokens,
      adapter:widget.adapter,visibility:widget.visibility,pairedTarget:target,deviceKeys:keys,keyHandle:p.handle,
      devicePublicKey:p.request['public_key'] as String,onConnecting:() { ticket = p.connect(); },onAuthenticated:() { p.connectionResult(ticket,true); if (mounted) setState(() {}); },
      onStopped:() { if (['connecting','paired'].contains(p.state)) { p.generation++; p.state = 'waiting-connectivity'; } })));
    if (!mounted) return;
    if (p.state == 'connecting') p.connectionResult(ticket,false);
    try { await persistPairing(); } catch (_) { if (mounted) setState(() { busy = false; status = '连接已停止 · 状态保存未确认，目录已锁定，请重新读取核验'; }); return; }
    if (!mounted) return;
    setState(() { busy = false; status = '连接已停止 · ${p.state}；只能主动重新审查连接'; });
  }
  Future<void> delete() async {
    final p = pairing; if (p == null || busy) return;
    revision++; p.cancel(); sourceReviewed = false; targetReviewed = false; final ticket = revision;
    setState(() { busy = true; });
    try {
      if (widget.catalog != null && savedProfile != null) await widget.catalog!.update(savedProfile!.change(enabled:false,now:now));
      await keys.delete(p.handle);
      if (widget.catalog != null && savedProfile != null) await widget.catalog!.remove(savedProfile!.id);
      if (!mounted || ticket != revision) return;
      PairingPage.resetMemorySession(); savedProfile = null;
      setState(() { busy = false; pairing = null; target = null; creationUnknown = false; response.clear(); responsePreview = null; status = '本机身份已删除 · 主机授权未因此撤销；需要新配对时请明确创建'; });
    } catch (_) {
      if (mounted && ticket == revision) setState(() { busy = false; status = '密钥删除未确认 · 保留原身份引用，不会自动替换；主机授权仍需核验撤销'; });
    }
  }
  Future<void> checkExistingIdentity() async {
    final p = pairing; if (p == null) return;
    final ticket = revision;
    try {
      final actual = await keys.public(p.handle);
      if (!mounted || ticket != revision) return;
      if (actual != p.request['public_key']) throw const RemoteFailure('device_key_changed');
      setState(() { identityAvailable = true; status = '本机原身份已匹配 · 请核验主机指纹后主动审查连接'; });
    } catch (_) {
      if (mounted && ticket == revision) setState(() { identityAvailable = false; status = '原设备密钥丢失、锁定或公钥不符 · 连接禁用，不生成替代身份；可保留资料核验或明确删除'; });
    }
  }
  Future<void> persistPairing() async {
    final catalog = widget.catalog, p = pairing, old = savedProfile;
    if (catalog == null || p == null || old == null) return;
    try {
      final next = old.change(pairing:p,now:now); await catalog.update(next); savedProfile = next;
    } catch (_) { profileBlocked = true; rethrow; }
  }
  Future<void> deleteOrphan() async {
    final handle = PairingPage.retainedOrphan; if (handle == null || busy) return;
    setState(() { busy = true; });
    try {
      await keys.delete(handle);
      if (PairingPage.retainedOrphan == handle) PairingPage.resetMemorySession();
      if (mounted) setState(() { busy = false; creationUnknown = false; status = '原身份已删除 · 主机授权不因此撤销'; });
    } catch (_) { if (mounted) setState(() { busy = false; status = '原身份删除未确认 · 已保留引用；不自动替换'; }); }
  }
  void previewResponse({bool edited = true}) {
    if (edited) { revision++; scanning = false; }
    Map<String,dynamic>? preview;
    try { preview = decodePairing(Uint8List.fromList(utf8.encode(response.text)),now); } catch (_) { /* invalid is not trusted */ }
    setState(() { sourceReviewed = false; responsePreview = preview; });
  }
  @override
  void didUpdateWidget(PairingPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.visibility != widget.visibility) {
      oldWidget.visibility?.removeListener(visibilityChanged); widget.visibility?.addListener(visibilityChanged);
      visibilityChanged();
    }
  }
  void visibilityChanged() {
    if (pageVisible) {
      final catalog = widget.catalog, previous = savedProfile;
      if (catalog != null && previous != null) {
        final current = catalog.profiles.where((p) => p.id == previous.id && p.enabled).toList();
        if (!catalog.ready || current.length != 1 || !sameHostTarget(current.single.target,previous.target) ||
            jsonEncode(current.single.pairingRecord) != jsonEncode(previous.pairingRecord)) {
          profileBlocked = true;
          if (mounted) setState(() { status = '本机绑定或授权资料已改变 · 请关闭此标签重新读取审查，不沿用旧状态'; });
          return;
        }
        // Rename/provider edits are public metadata and may refresh without
        // resetting this tab's frozen identity or overwriting a newer record.
        savedProfile = current.single; provider = current.single.provider;
      }
      if (mounted) setState(() { status = '标签已返回 · 目标与草稿保留；请主动重新审查连接，默认观察'; });
      if (pairing != null && !profileBlocked) unawaited(checkExistingIdentity());
      return;
    }
    pauseReview('标签已暂停 · 不发送输入、不重连；远端任务未终止');
  }
  void pauseReview(String message) {
    revision++; scanning = false; targetReviewed = false; sourceReviewed = false;
    final p = pairing;
    if (p != null) {
      identityAvailable = false;
      if (['connecting','paired'].contains(p.state)) { p.generation++; p.state = 'waiting-connectivity'; }
      p.tick(now);
    } else if (busy && PairingPage.retainedCreationUnknown) {
      creationUnknown = true;
    }
    if (mounted) setState(() { busy = false; status = message; });
  }
  Future<void> scanResponse() async {
    final p = pairing;
    if (!scanAvailable || scanning || busy || !pageVisible || p == null ||
        ['cancelled','expired','revoked'].contains(p.state) || now >= (p.request['expires_at'] as int)) return;
    final ticket = revision, generation = p.generation, requestId = p.request['request_id'], pairingState = p.state;
    bool current() => mounted && ticket == revision && identical(pairing,p) && p.generation == generation &&
      p.request['request_id'] == requestId && p.state == pairingState && pageVisible && now < (p.request['expires_at'] as int) &&
      !['cancelled','expired','revoked'].contains(p.state);
    setState(() { scanning = true; sourceReviewed = false; status = '扫描公开响应 · 返回后仍需独立审查'; });
    try {
      final text = await const MethodChannel('herdr.pocket/pair_scan').invokeMethod<String>('scan');
      if (!current()) return;
      if (text == null || text.isEmpty) { setState(() { status = '已取消扫描 · 可继续手动输入响应'; }); return; }
      if (utf8.encode(text).length > 2048) { setState(() { status = '扫码内容超过公开响应上限 · 未填入，可手动核验'; }); return; }
      response.text = text; previewResponse(edited:false);
      setState(() { sourceReviewed = false; status = '扫码文本已填入候审框 · 尚未接受授权，请核验响应摘要与来源'; });
    } catch (_) {
      if (current()) setState(() { sourceReviewed = false; status = '相机不可用、权限被拒绝或扫描取消 · 可继续手动输入响应'; });
    } finally { if (mounted && ticket == revision) setState(() { scanning = false; }); }
  }
  Widget input(String name,String label) => Padding(padding:const EdgeInsets.only(bottom:12),
    child:TextField(key:ValueKey('pair-$name'),controller:fields[name],enabled:!busy && pairing == null && (savedProfile == null || name == 'device'),
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
        if (widget.catalog == null && PairingPage.retainedOrphan != null) TextButton(key:const ValueKey('pair-delete-orphan'),onPressed:busy ? null : deleteOrphan,child:const Text('明确删除原身份引用')),
        if (p == null) ...[
          DropdownButtonFormField<String>(key:const ValueKey('pair-provider'),initialValue:provider,decoration:const InputDecoration(labelText:'网络 provider（仅配置，入网未知）'),items:[for (final p in hostProviders) DropdownMenuItem(value:p,child:Text(hostProviderLabel(p)))],onChanged:busy ? null : (value) { if (value != null) setState(() { provider = value; targetReviewed = false; revision++; }); }),
          const SizedBox(height:12),
          input('host','SSH 主机 / IP'), input('port','SSH 端口'), input('username','主机账号'),
          input('session','命名会话（非 default）'), input('socketPath','命名会话 socket 绝对路径'),
          input('herdrPath','herdr 可执行文件绝对路径'), input('expectedHostKey','可信渠道核验的 Ed25519 主机公钥'), input('device','设备名称（英文、数字、空格）'),
          CheckboxListTile(key:const ValueKey('pair-target-review'),value:targetReviewed,
            onChanged:busy ? null : (value) => setState(() { targetReviewed = value == true; }),
            title:const Text('我已通过可信渠道核验账号、主机公钥与命名会话资料')),
          FilledButton(key:const ValueKey('pair-create'),onPressed:targetReviewed && !busy && !creationUnknown && !profileBlocked && platformAvailable ? create : null,
            child:const Text('在此设备创建独立身份并生成公开请求')),
        ] else ...[
          if (savedProfile != null) Text('${hostProviderLabel(savedProfile!.provider)} · 入网状态未知；每标签独立连接'),
          Text('状态 ${p.state} · 主机授权 ${p.authorization}',key:const ValueKey('pair-state')),
          Text('账号 ${p.request['account']}\n主机 ${p.request['host_key']}\n设备 ${pairingFingerprint(p.request['public_key'] as String)}\n到期 ${p.request['expires_at']}'),
          const SizedBox(height:12), SelectableText(p.wire,key:const ValueKey('pair-request')),
          TextButton(key:const ValueKey('pair-copy'),onPressed:p.state == 'awaiting-host' ? () => Clipboard.setData(ClipboardData(text:p.wire)) : null,child:const Text('复制公开请求')),
          const Text('响应本身没有来源认证。请独立核验主机生成的响应来源、账号与两端指纹；粘贴不等于信任。'),
          if (scanAvailable) TextButton.icon(key:const ValueKey('pair-scan'),onPressed:busy || scanning || !pageVisible || ['cancelled','expired','revoked'].contains(p.state) || now >= (p.request['expires_at'] as int) ? null : scanResponse,icon:const Icon(Icons.qr_code_scanner),label:const Text('扫描主机响应')),
          TextField(key:const ValueKey('pair-response'),controller:response,enabled:!busy,maxLength:2048,minLines:3,maxLines:6,
            decoration:const InputDecoration(labelText:'公开授权／撤销响应 JSON'),onChanged:(_) => previewResponse()),
          if (responsePreview != null) Text('待审查响应\n账号 ${responsePreview!['account']}\n主机 ${responsePreview!['host_key']}\n设备 ${responsePreview!['fingerprint']}\n状态 ${responsePreview!['status']} · 新增授权 ${responsePreview!['authorization_added']}\n期限 ${responsePreview!['issued_at']} → ${responsePreview!['expires_at']}',key:const ValueKey('pair-response-preview')),
          CheckboxListTile(key:const ValueKey('pair-source-review'),value:sourceReviewed,
            onChanged:busy ? null : (v) => setState(() { sourceReviewed = v == true; }),title:const Text('我已独立核验响应来源、账号与两端指纹')),
          FilledButton(key:const ValueKey('pair-accept'),onPressed:sourceReviewed && !busy && !scanning ? accept : null,child:const Text('审查并接受绑定响应')),
          if (['authorized-unverified','waiting-connectivity','paired'].contains(p.state)) FilledButton(
            key:const ValueKey('pair-connect'),onPressed:busy || !identityAvailable || profileBlocked || widget.catalog?.ready == false ? null : connect,child:const Text('主动审查连接并读取看板')),
          if (savedProfile != null && !identityAvailable) TextButton(key:const ValueKey('pair-recheck-key'),onPressed:busy ? null : checkExistingIdentity,child:const Text('仅重新核验原设备身份')),
          TextButton(key:const ValueKey('pair-cancel'),onPressed:busy ? null : cancelWaiting,child:const Text('取消等待（不撤销主机授权）')),
          TextButton(key:const ValueKey('pair-delete'),onPressed:busy ? null : delete,child:const Text('删除本机身份（不撤销主机授权）')),
        ],
      ]))));
  }
}
