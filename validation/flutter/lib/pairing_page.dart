import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'connection_profile.dart';
import 'design_tokens.dart';
import 'device_keys.dart';
import 'host_catalog.dart';
import 'pairing.dart';
import 'remote_adapter.dart';
import 'remote_page.dart';
import 'host_task_summary.dart';

/// Public request/response review. Native identity creation is always explicit;
/// missing/locked storage has no fallback, and responses never establish SSH trust.
class PairingPage extends StatefulWidget {
  const PairingPage({super.key,required this.tokens,this.keys,this.adapter,this.onRequest,this.clock,this.catalog,this.profileId,this.visibility,this.onViewState,this.requestedTarget,this.onOpenPane,this.summaryLeaseFactory});
  final DesignTokens tokens;
  final DeviceKeys? keys;
  final HostCatalog? catalog;
  final String? profileId;
  final ValueListenable<bool>? visibility;
  final void Function(String,String?,String?)? onViewState;
  final RemotePane? requestedTarget;
  final void Function(RemotePane)? onOpenPane;
  final HostDashboardLease Function(HostProfile)? summaryLeaseFactory;
  final RemoteReadOnlyAdapter? adapter;
  final void Function(Map<String,dynamic>)? onRequest;
  static PendingDevicePairing? retainedPairing;
  static Map<String,dynamic>? retainedTarget;
  static String? retainedOrphan;
  static bool retainedCreationUnknown = false;
  static bool retainedRequiresNetworkBinding = false;
  @visibleForTesting
  static void resetMemorySession() { retainedPairing = null; retainedTarget = null; retainedOrphan = null; retainedCreationUnknown = false; retainedRequiresNetworkBinding = false; }
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
  final profileInput = TextEditingController();
  ConnectionProfile? profilePreview;
  bool get canImportProfile => savedProfile == null && widget.profileId == null && pairing == null && target == null && !profileBlocked && !creationUnknown && !busy && pageVisible;
  PendingDevicePairing? pairing;
  HostProfile? savedProfile;
  bool profileBlocked = false,identityAvailable = true,widgetBindingChanged = false;
  Map<String,dynamic>? target;
  bool busy = false, accepting = false, targetReviewed = false, sourceReviewed = false;
  bool creationUnknown = false,scanning = false;
  String provider = 'unspecified';
  String? importedOverlayProvider;
  // Snapshot the retained session's restriction with its identity and target.
  // Another page may replace the process-wide retained session later.
  bool retainedNetworkBinding = false;
  bool get needsNetworkBinding => savedProfile?.requiresNetworkBinding ?? (importedOverlayProvider != null || retainedNetworkBinding);
  bool get pageVisible => widget.visibility?.value ?? true;
  bool get scanAvailable => !kIsWeb && [TargetPlatform.android,TargetPlatform.iOS].contains(defaultTargetPlatform);
  bool get platformAvailable => widget.keys != null || (!kIsWeb && [TargetPlatform.android,TargetPlatform.iOS,TargetPlatform.macOS].contains(defaultTargetPlatform));
  String status = '先审查目标，再由此设备生成独立身份。仅公开请求可以交给主机。';
  int revision = 0;
  bool appResumed = true;
  Completer<void>? scannerResume;
  void releaseScannerWaiter() {
    final waiter = scannerResume; scannerResume = null;
    if (waiter != null && !waiter.isCompleted) waiter.complete();
  }
  void invalidateScan() { revision++; scanning = false; releaseScannerWaiter(); }
  Future<bool> scannerForeground(int ticket,{int? expiresAt}) async {
    if (!mounted || ticket != revision || !pageVisible) return false;
    if (!appResumed) {
      // A native result can arrive while the app is paused. Keep it briefly
      // for the scanner's normal activity round trip, never indefinitely.
      final remaining = expiresAt == null ? 60 : expiresAt - now;
      if (remaining <= 0) return false;
      final limit = Duration(seconds:remaining < 60 ? remaining : 60);
      final elapsed = Stopwatch()..start();
      final waiter = Completer<void>(); scannerResume = waiter;
      final expiry = Timer(limit,() { if (!waiter.isCompleted) waiter.complete(); });
      try { await waiter.future; } finally { expiry.cancel(); }
      if (identical(scannerResume,waiter)) scannerResume = null;
      if (elapsed.elapsed >= limit || (expiresAt != null && now >= expiresAt)) return false;
    }
    return mounted && ticket == revision && pageVisible && appResumed;
  }
  Timer? timer;
  Map<String,dynamic>? responsePreview;
  // A catalog-backed page must use the same clock for request creation and
  // later restoration. Otherwise a newly persisted request can appear future
  // dated when the board rebuilds (notably with an isolated fixture clock).
  int get now => widget.clock?.call() ?? widget.catalog?.clock() ?? DateTime.now().millisecondsSinceEpoch ~/ 1000;
  @override
  void initState() {
    super.initState(); appResumed = WidgetsBinding.instance.lifecycleState == null || WidgetsBinding.instance.lifecycleState == AppLifecycleState.resumed; WidgetsBinding.instance.addObserver(this); widget.visibility?.addListener(visibilityChanged);
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
      retainedNetworkBinding = pairing != null && target != null && PairingPage.retainedRequiresNetworkBinding;
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
    if (widgetBindingChanged) return;
    invalidateScan();
    final p = pairing;
    if (p != null) {
      if (['awaiting-host','authorized-unverified'].contains(p.state)) p.cancel();
      if (['connecting','paired'].contains(p.state)) { p.generation++; p.state = 'waiting-connectivity'; }
    }
    if (!accepting && widget.catalog != null && savedProfile != null) unawaited(persistPairing().catchError((Object _) {}));
    if (mounted) setState(() { busy = accepting; targetReviewed = false; sourceReviewed = false;
      if (accepting) profileBlocked = true;
      status = accepting ? '响应保存期间已取消 · 原页禁止重试，请关闭后重新读取核验'
        : '已取消等待 · 主机授权可能已发生，请在主机核验'; });
  }
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    appResumed = state == AppLifecycleState.resumed;
    if (appResumed) releaseScannerWaiter();
    if (scanning) return; // The OS may pause this activity for its own scanner.
    if (appResumed) {
      if (mounted) setState(() {});
      if (pageVisible && pairing != null && !profileBlocked) unawaited(checkExistingIdentity());
      return;
    }
    pauseReview('应用已暂停 · 保留原请求，返回后重新核验设备与响应来源');
  }
  @override
  void dispose() {
    invalidateScan(); timer?.cancel(); widget.visibility?.removeListener(visibilityChanged); WidgetsBinding.instance.removeObserver(this);
    if (widget.catalog == null) pairing?.cancel(); for (final field in fields.values) { field.dispose(); } response.dispose(); profileInput.dispose(); super.dispose();
  }
  Future<void> create() async {
    if (busy || scanning || !appResumed || pairing != null || !targetReviewed || creationUnknown || profileBlocked || !pageVisible || !platformAvailable) return;
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
        final profile = HostProfile.create(label,values,p,now,provider:provider,networkProfileId:savedProfile?.networkProfileId,requiresNetworkBinding:savedProfile?.requiresNetworkBinding ?? (importedOverlayProvider != null));
        await widget.catalog!.completeCreation(profile); savedProfile = profile;
        if (!mounted || ticket != revision) return;
      }
      retainedNetworkBinding = savedProfile?.requiresNetworkBinding ?? (importedOverlayProvider != null);
      PairingPage.retainedPairing = p; PairingPage.retainedRequiresNetworkBinding = retainedNetworkBinding; PairingPage.retainedTarget = Map.unmodifiable(values); PairingPage.retainedOrphan = null; PairingPage.retainedCreationUnknown = false;
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
  bool requestAvailable(PendingDevicePairing p) => p.state == 'awaiting-host' && !p.consumed && now < (p.request['expires_at'] as int);
  Future<void> copyRequest() async {
    final p = pairing;
    if (p == null || busy || scanning || profileBlocked || !pageVisible || !appResumed || !requestAvailable(p)) return;
    final ticket = revision, generation = p.generation, wire = p.wire;
    try {
      await Clipboard.setData(ClipboardData(text:wire));
      if (!mounted || !identical(pairing,p) || ticket != revision || generation != p.generation || !pageVisible || !appResumed) return;
      setState(() { status = requestAvailable(p) ? '公开请求已复制 · 请独立核对请求编号、账号与两端指纹，再交给主机审查' : '复制完成时请求已失效 · 请勿交付剪贴板中的旧请求'; });
    } catch (_) {
      if (mounted && identical(pairing,p) && ticket == revision && generation == p.generation && pageVisible && appResumed) {
        setState(() { status = requestAvailable(p) ? '复制未确认 · 可手动选择下方公开请求全文；交付前核对编号与期限' : '复制未确认且请求已失效 · 请勿交付旧请求'; });
      }
    }
  }
  Future<void> accept() async {
    final p = pairing; if (p == null || busy || accepting || scanning || !pageVisible || !appResumed || profileBlocked ||
      !sourceReviewed || responsePreview == null || widget.catalog?.ready == false) return;
    final ticket = revision, generation = p.generation, originalProfile = savedProfile;
    setState(() { busy = true; accepting = true; status = '正在核验响应并保存本机状态 · 不代表 SSH 已连通'; });
    try {
      // Verify a detached candidate. The visible object remains unapproved until
      // the catalog CAS succeeds; a lost save reply must not publish permission.
      final candidate = restoreDevicePairing(p.toPublicRecord(),now);
      candidate.accept(response.text,now:now,reviewed:sourceReviewed);
      await persistPairing(candidate:candidate);
      if (!mounted) return;
      if (ticket != revision || p.generation != generation || !identical(pairing,p) || !pageVisible ||
          (originalProfile != null && (savedProfile?.id != originalProfile.id ||
            !sameHostTarget(savedProfile!.target,originalProfile.target) ||
            savedProfile!.pairingRecord['handle'] != originalProfile.pairingRecord['handle']))) {
        setState(() { busy = false; sourceReviewed = false; profileBlocked = true;
          status = '响应审查期间页面已变化 · 原页禁止重试，请关闭后从主机页重新读取核验；不会自动连接'; });
        return;
      }
      if (widget.catalog == null) {
        PairingPage.retainedPairing = candidate;
        PairingPage.retainedTarget = Map.unmodifiable(target!);
        PairingPage.retainedRequiresNetworkBinding = needsNetworkBinding;
      }
      setState(() { pairing = candidate; busy = false; sourceReviewed = false; response.clear(); responsePreview = null; status = candidate.state == 'revoked'
        ? '已审查匹配的主机撤销响应 · 此请求不能再授权' : '主机报告已授权 · 尚未验证 SSH，需主动连接'; });
    } catch (error) {
      if (!mounted) return;
      setState(() { busy = false; sourceReviewed = false;
        if (profileBlocked || widget.catalog?.ready == false) {
          profileBlocked = true;
          status = '响应核验后本机保存未确认 · 原页禁止重试，请关闭后重新读取核验；不会自动连接';
        } else { status = switch (error is RemoteFailure ? error.code : '') {
          'pairing_binding_mismatch' => '响应无效 · 与原请求账号、主机、设备或请求编号不匹配，请重新核验来源',
          'pairing_replay' => '响应无效 · 原请求已处理、到期或响应期限超出原请求，请核验原状态',
          _ => '响应无效 · 格式、设备时钟或期限不符合要求，请重新核验',
        }; }
      });
    } finally { accepting = false; }
  }
  Future<void> connect() async {
    final p = pairing; if (p == null || busy || scanning || !pageVisible || !identityAvailable || profileBlocked || widget.catalog?.ready == false || savedProfile?.enabled == false) return;
    if (needsNetworkBinding) { setState(() { status = '请返回主机列表，选择／解除网络绑定，先明确绑定相同 provider 的本机网络；不会使用系统直连'; }); return; }
    final networkBinding = savedProfile == null ? null : widget.catalog?.freezeNetwork(savedProfile!);
    var ticket = p.generation;
    setState(() { busy = true; status = '请在连接页再次审查冻结目标；只有实际 pin 与 SSH 认证成功才标记已配对'; });
    final summaryLease = savedProfile == null ? null : widget.summaryLeaseFactory?.call(savedProfile!);
    await Navigator.push<void>(context,MaterialPageRoute(builder:(_) => RemotePage(tokens:widget.tokens,
      adapter:widget.adapter,visibility:widget.visibility,networkBinding:networkBinding,pairedTarget:target,deviceKeys:keys,keyHandle:p.handle,onViewState:widget.onViewState,
      requestedTarget:widget.requestedTarget,onOpenPane:widget.onOpenPane,
      summaryLease:summaryLease,
      devicePublicKey:p.request['public_key'] as String,onConnecting:() { ticket = p.connect(); },onAuthenticated:() { p.connectionResult(ticket,true); if (mounted) setState(() {}); },
      onStopped:() { if (['connecting','paired'].contains(p.state)) { p.generation++; p.state = 'waiting-connectivity'; } })));
    if (!mounted) return;
    if (p.state == 'connecting') p.connectionResult(ticket,false);
    try { await persistPairing(); } catch (_) { if (mounted) setState(() { busy = false; status = '连接已停止 · 状态保存未确认，目录已锁定，请重新读取核验'; }); return; }
    if (!mounted) return;
    setState(() { busy = false; status = '连接已停止 · ${p.state}；只能主动重新审查连接'; });
  }
  Future<void> delete() async {
    final p = pairing; if (p == null || busy || widgetBindingChanged) return;
    invalidateScan(); p.cancel(); sourceReviewed = false; targetReviewed = false; final ticket = revision;
    setState(() { busy = true; });
    try {
      if (widget.catalog != null && savedProfile != null) await widget.catalog!.update(savedProfile!.change(enabled:false,now:now));
      await keys.delete(p.handle);
      if (widget.catalog != null && savedProfile != null) await widget.catalog!.remove(savedProfile!.id);
      if (!mounted || ticket != revision) return;
      if (widget.catalog == null && PairingPage.retainedPairing?.handle == p.handle &&
          PairingPage.retainedPairing?.request['request_id'] == p.request['request_id']) {
        PairingPage.retainedPairing = null; PairingPage.retainedTarget = null; PairingPage.retainedRequiresNetworkBinding = false;
      }
      savedProfile = null;
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
      if (!mounted || ticket != revision || profileBlocked || !pageVisible || !identical(pairing,p)) return;
      if (actual != p.request['public_key']) throw const RemoteFailure('device_key_changed');
      setState(() { identityAvailable = true; status = '本机原身份已匹配 · 请核验主机指纹后主动审查连接'; });
    } catch (_) {
      if (mounted && ticket == revision && !profileBlocked && pageVisible && identical(pairing,p)) setState(() { identityAvailable = false; status = '原设备密钥丢失、锁定或公钥不符 · 连接禁用，不生成替代身份；可保留资料核验或明确删除'; });
    }
  }
  Future<void> persistPairing({PendingDevicePairing? candidate}) async {
    final catalog = widget.catalog, p = candidate ?? pairing, old = savedProfile;
    if (catalog == null || p == null || old == null) return;
    try {
      final matches = catalog.profiles.where((current) => current.id == old.id && current.enabled && !current.retired).toList();
      if (!catalog.ready || matches.length != 1 || !sameHostTarget(matches.single.target,old.target) ||
          matches.single.networkProfileId != old.networkProfileId || matches.single.requiresNetworkBinding != old.requiresNetworkBinding || !samePairingBinding(matches.single,old)) {
        throw const RemoteFailure('catalog_binding_changed');
      }
      final next = matches.single.change(pairing:p,now:now); await catalog.update(next); savedProfile = next;
    } catch (_) { profileBlocked = true; rethrow; }
  }
  Future<void> deleteOrphan() async {
    final handle = PairingPage.retainedOrphan; if (handle == null || busy || widgetBindingChanged) return;
    setState(() { busy = true; });
    try {
      await keys.delete(handle);
      if (PairingPage.retainedOrphan == handle) { PairingPage.retainedOrphan = null; PairingPage.retainedCreationUnknown = false; }
      if (mounted) setState(() { busy = false; creationUnknown = false; status = '原身份已删除 · 主机授权不因此撤销'; });
    } catch (_) { if (mounted) setState(() { busy = false; status = '原身份删除未确认 · 已保留引用；不自动替换'; }); }
  }
  void previewResponse({bool edited = true}) {
    if (edited) invalidateScan();
    Map<String,dynamic>? preview;
    try { preview = decodePairing(Uint8List.fromList(utf8.encode(response.text)),now); } catch (_) { /* invalid is not trusted */ }
    setState(() { sourceReviewed = false; responsePreview = preview; });
  }
  @override
  void didUpdateWidget(PairingPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.profileId != widget.profileId || oldWidget.catalog != widget.catalog || oldWidget.keys != widget.keys) {
      widgetBindingChanged = true; profileBlocked = true;
      pauseReview('目标或本机身份来源已改变 · 请关闭此页并重新打开，不沿用旧扫描或信任');
    }
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
        if (!catalog.ready || current.length != 1 || !sameHostTarget(current.single.target,previous.target) || current.single.networkProfileId != previous.networkProfileId || current.single.requiresNetworkBinding != previous.requiresNetworkBinding ||
            !samePairingBinding(current.single,previous)) {
          profileBlocked = true;
          if (mounted) setState(() { status = '本机绑定或授权资料已改变 · 请关闭此标签重新读取审查，不沿用旧状态'; });
          return;
        }
        // Rename/provider edits are public metadata and may refresh without
        // resetting this tab's frozen identity or overwriting a newer record.
        savedProfile = current.single; provider = current.single.provider;
      }
      if (mounted) setState(() { status = profileBlocked
        ? '原页面状态已失效 · 请关闭后从主机页重新读取核验，不再接受响应或自动连接'
        : '标签已返回 · 目标与草稿保留；请主动重新审查连接，默认观察'; });
      if (pairing != null && !profileBlocked) unawaited(checkExistingIdentity());
      return;
    }
    pauseReview('标签已暂停 · 不发送输入、不重连；远端任务未终止');
  }
  void pauseReview(String message) {
    invalidateScan(); targetReviewed = false; sourceReviewed = false; profilePreview = null;
    final p = pairing;
    if (p != null) {
      identityAvailable = false;
      if (['connecting','paired'].contains(p.state)) { p.generation++; p.state = 'waiting-connectivity'; }
      p.tick(now);
    } else if (busy && PairingPage.retainedCreationUnknown) {
      creationUnknown = true;
    }
    if (mounted) setState(() { busy = accepting; status = message; });
  }
  Future<void> scanResponse() async {
    final p = pairing;
    if (!scanAvailable || scanning || busy || profileBlocked || !pageVisible || !appResumed || p == null ||
        p.state == 'revoked') return;
    final ticket = revision, generation = p.generation, requestId = p.request['request_id'], pairingState = p.state;
    bool current() => mounted && ticket == revision && identical(pairing,p) && p.generation == generation &&
      p.request['request_id'] == requestId && p.state == pairingState && pageVisible && appResumed && p.state != 'revoked';
    setState(() { scanning = true; sourceReviewed = false; status = '扫描公开响应 · 返回后仍需独立审查'; });
    try {
      final text = await const MethodChannel('herdr.pocket/pair_scan').invokeMethod<String>('scan');
      Map<String,dynamic>? scanned;
      if (text != null && text.isNotEmpty) {
        try {
          scanned = decodePairing(Uint8List.fromList(utf8.encode(text)),now);
          if (scanned['type'] != 'pairing-binding-response') scanned = null;
        } catch (_) { scanned = null; }
      }
      if (!await scannerForeground(ticket,expiresAt:scanned?['expires_at'] as int?) || !current()) return;
      if (text == null || text.isEmpty) { setState(() { status = '已取消扫描 · 可继续手动输入响应'; }); return; }
      if (scanned == null || now >= (scanned['expires_at'] as int)) { setState(() { status = '扫码响应无效或已过期 · 未填入，请重新核验'; }); return; }
      if (scanned['status'] != 'revoked' && !requestAvailable(p)) { setState(() { status = '原请求已取消、处理或过期 · 只可审查新鲜撤销回执'; }); return; }
      response.text = text; previewResponse(edited:false);
      setState(() { sourceReviewed = false; status = '扫码文本已填入候审框 · 尚未接受授权，请核验响应摘要与来源'; });
    } catch (_) {
      if (current()) setState(() { sourceReviewed = false; status = '相机不可用、权限被拒绝或扫描取消 · 可继续手动输入响应'; });
    } finally { if (mounted && ticket == revision) setState(() { scanning = false; }); }
  }
  void previewProfile() {
    invalidateScan();
    ConnectionProfile? preview;
    try { preview = ConnectionProfile.parse(profileInput.text); } catch (_) { /* untrusted input */ }
    setState(() { profilePreview = preview; });
  }
  Future<void> scanProfile() async {
    if (!scanAvailable || scanning || !canImportProfile || !appResumed) return;
    final ticket = revision;
    bool current() => mounted && ticket == revision && canImportProfile && appResumed;
    setState(() { scanning = true; targetReviewed = false; profilePreview = null; status = '扫描公开连接资料 · 返回后仍需预览和审查'; });
    try {
      final text = await const MethodChannel('herdr.pocket/pair_scan').invokeMethod<String>('scan');
      if (!await scannerForeground(ticket) || !current()) return;
      if (text == null || text.isEmpty) { setState(() { status = '已取消扫描 · 可手动粘贴公开资料'; }); return; }
      final preview = ConnectionProfile.parse(text);
      setState(() { profileInput.text = text; profilePreview = preview; status = '公开资料待预览 · 尚未填入或建立信任'; });
    } catch (_) {
      if (current()) setState(() { status = '扫描不可用或资料无效 · 未填入表单，可手动粘贴'; });
    } finally { if (mounted && ticket == revision) setState(() { scanning = false; }); }
  }
  void fillProfile() {
    final preview = profilePreview;
    if (!canImportProfile || scanning || !appResumed || preview == null) return;
    revision++;
    setState(() {
      for (final name in ['host','port','username','session','socketPath','herdrPath','expectedHostKey']) {
        fields[name]!.text = preview.values[name].toString();
      }
      provider = preview.values['provider'] as String;
      importedOverlayProvider = ['tailscale','easytier','zerotier'].contains(provider) ? provider : null;
      profilePreview = null; profileInput.clear(); targetReviewed = false;
      status = '资料已填入未审查表单 · 请独立核验指纹与目标后再创建设备身份';
    });
  }
  Widget input(String name,String label) => Padding(padding:const EdgeInsets.only(bottom:12),
    child:TextField(key:ValueKey('pair-$name'),controller:fields[name],enabled:!busy && pairing == null && (savedProfile == null || name == 'device'),
      autocorrect:false,maxLength:name == 'expectedHostKey' ? 4096 : 1024,decoration:InputDecoration(labelText:label,counterText:''),
      onChanged:(_) { invalidateScan(); setState(() { targetReviewed = false; profilePreview = null; }); }));
  @override
  Widget build(BuildContext context) {
    final p = pairing;
    return Scaffold(appBar:AppBar(title:const Text('设备配对 · 公开请求')),
      body:SafeArea(child:SingleChildScrollView(padding:const EdgeInsets.all(16),child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
        Semantics(liveRegion:true,child:Text(status,key:const ValueKey('pair-status'))),
        const SizedBox(height:12),
        if (!platformAvailable) const Text('此平台的设备安全存储桥不可用 · 设备配对已禁用，可返回手动隔离实验'),
        if (widget.catalog == null && PairingPage.retainedOrphan != null) TextButton(key:const ValueKey('pair-delete-orphan'),onPressed:busy || widgetBindingChanged ? null : deleteOrphan,child:const Text('明确删除原身份引用')),
        if (p == null) ...[
          if (canImportProfile) ...[
            const Text('公开连接资料不证明主机身份；请通过可信渠道独立核验指纹。'),
            if (scanAvailable) TextButton.icon(key:const ValueKey('profile-scan'),onPressed:scanning ? null : scanProfile,
              icon:const Icon(Icons.qr_code_scanner),label:const Text('扫描公开连接资料')),
            TextField(key:const ValueKey('profile-input'),controller:profileInput,maxLength:2048,minLines:2,maxLines:5,
              decoration:const InputDecoration(labelText:'粘贴公开连接资料 JSON'),onChanged:(_) => previewProfile()),
            if (profilePreview != null) ...[
              SelectableText('待预览（尚未信任）\n主机 ${profilePreview!.values['host']}:${profilePreview!.values['port']}\n账号 ${profilePreview!.values['username']}\n网络 ${profilePreview!.values['provider']}\n会话 ${profilePreview!.values['session']}\nsocket ${profilePreview!.values['socketPath']}\nherdr ${profilePreview!.values['herdrPath']}\n主机指纹 ${profilePreview!.fingerprint}',key:const ValueKey('profile-preview')),
              TextButton(key:const ValueKey('profile-fill'),onPressed:scanning ? null : fillProfile,child:const Text('明确填入未审查表单')),
            ],
          ],
          DropdownButtonFormField<String>(key:const ValueKey('pair-provider'),initialValue:provider,decoration:const InputDecoration(labelText:'网络 provider（仅配置，入网未知）'),items:[for (final p in hostProviders) DropdownMenuItem(value:p,child:Text(hostProviderLabel(p)))],onChanged:busy || importedOverlayProvider != null ? null : (value) { if (value != null) setState(() { provider = value; targetReviewed = false; profilePreview = null; invalidateScan(); }); }),
          if (importedOverlayProvider != null) Text('公开资料声明 $importedOverlayProvider · 配对后请在主机列表明确绑定同类本机网络，首次绑定前禁止连接。'),
          const SizedBox(height:12),
          input('host','SSH 主机 / IP'), input('port','SSH 端口'), input('username','主机账号'),
          input('session','命名会话（非 default）'), input('socketPath','命名会话 socket 绝对路径'),
          input('herdrPath','herdr 可执行文件绝对路径'), input('expectedHostKey','可信渠道核验的 Ed25519 主机公钥'), input('device','设备名称（英文、数字、空格）'),
          CheckboxListTile(key:const ValueKey('pair-target-review'),value:targetReviewed,
            onChanged:busy || scanning || !appResumed ? null : (value) => setState(() { targetReviewed = value == true; }),
            title:const Text('我已通过可信渠道核验账号、主机公钥与命名会话资料')),
          FilledButton(key:const ValueKey('pair-create'),onPressed:targetReviewed && !busy && !scanning && appResumed && !creationUnknown && !profileBlocked && platformAvailable ? create : null,
            child:const Text('在此设备创建独立身份并生成公开请求')),
        ] else ...[
          if (needsNetworkBinding) const Text('需先返回主机列表，选择／解除网络绑定，明确绑定相同 provider 的本机网络；不会自动使用系统直连。',key:ValueKey('pair-network-required')),
          if (savedProfile != null && !needsNetworkBinding) Text(savedProfile!.networkProfileId == null ? '系统直连（沿用系统路由） · 在线状态未知；每标签独立连接'
            : '网络：${widget.catalog?.networkFor(savedProfile!)?.label} · ${widget.catalog?.networkFor(savedProfile!)?.provider} · 入网状态未知；每标签独立连接'),
          Text('状态 ${p.state} · 主机授权 ${p.authorization}',key:const ValueKey('pair-state')),
          SelectableText('原请求编号 ${p.request['request_id']}\n账号 ${p.request['account']}\n主机指纹 ${p.request['host_key']}\n设备指纹 ${pairingFingerprint(p.request['public_key'] as String)}\n请求到期 ${p.request['expires_at']} · ${requestAvailable(p) ? '当前有效' : '不可再交付授权请求'}',key:const ValueKey('pair-handoff-summary')),
          const Text('只将有效的公开请求交给主机。主机操作者应先用 helper preview 独立核对编号、账号和两端指纹，再用 authorize 明确确认；取消等待不会撤销主机授权。'),
          const Text('需要撤销时，在主机 helper 目录运行 python -m herdr_pocket_helper revoke --host-public-key <主机公钥.pub> --request-id <原请求编号> 并明确确认；独立核验新鲜撤销回执。本机身份不会自动删除，已有 SSH 不会自动断开。'),
          if (requestAvailable(p)) ...[const SizedBox(height:12), SelectableText(p.wire,key:const ValueKey('pair-request')),
            const Text('复制不可用时，可手动选择上方公开请求全文；不要交付过期请求。')],
          TextButton(key:const ValueKey('pair-copy'),onPressed:!busy && !scanning && !profileBlocked && pageVisible && appResumed && requestAvailable(p) ? copyRequest : null,child:const Text('复制当前公开请求')),
          const Text('响应本身没有来源认证。请独立核验主机生成的响应来源、账号与两端指纹；粘贴不等于信任。'),
          if (scanAvailable) TextButton.icon(key:const ValueKey('pair-scan'),onPressed:busy || scanning || profileBlocked || !pageVisible || !appResumed || p.state == 'revoked' ? null : scanResponse,icon:const Icon(Icons.qr_code_scanner),label:const Text('扫描主机响应')),
          TextField(key:const ValueKey('pair-response'),controller:response,enabled:!busy,maxLength:2048,minLines:3,maxLines:6,
            decoration:const InputDecoration(labelText:'公开授权／撤销响应 JSON'),onChanged:(_) => previewResponse()),
          if (responsePreview != null) Text('待审查响应\n请求编号 ${responsePreview!['request_id']}\n账号 ${responsePreview!['account']}\n主机 ${responsePreview!['host_key']}\n设备 ${responsePreview!['fingerprint']}\n状态 ${responsePreview!['status']} · 新增授权 ${responsePreview!['authorization_added']}\n期限 ${responsePreview!['issued_at']} → ${responsePreview!['expires_at']}',key:const ValueKey('pair-response-preview')),
          CheckboxListTile(key:const ValueKey('pair-source-review'),value:sourceReviewed,
            onChanged:busy || scanning || !appResumed ? null : (v) => setState(() { sourceReviewed = v == true; }),title:const Text('我已独立核验响应来源、账号与两端指纹')),
          FilledButton(key:const ValueKey('pair-accept'),onPressed:sourceReviewed && responsePreview != null && !busy && !scanning &&
            pageVisible && appResumed && !profileBlocked && widget.catalog?.ready != false ? accept : null,child:const Text('审查并接受绑定响应')),
          if (['authorized-unverified','waiting-connectivity','paired'].contains(p.state)) FilledButton(
            key:const ValueKey('pair-connect'),onPressed:busy || !identityAvailable || profileBlocked || needsNetworkBinding || widget.catalog?.ready == false ? null : connect,child:const Text('主动审查连接并读取看板')),
          if (savedProfile != null && !identityAvailable) TextButton(key:const ValueKey('pair-recheck-key'),onPressed:busy ? null : checkExistingIdentity,child:const Text('仅重新核验原设备身份')),
          TextButton(key:const ValueKey('pair-cancel'),onPressed:busy || widgetBindingChanged ? null : cancelWaiting,child:const Text('取消等待（不撤销主机授权）')),
          TextButton(key:const ValueKey('pair-delete'),onPressed:busy || widgetBindingChanged ? null : delete,child:const Text('删除本机身份（不撤销主机授权）')),
        ],
      ]))));
  }
}
