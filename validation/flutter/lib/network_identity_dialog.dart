import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'host_catalog.dart';
import 'network_identity.dart';
import 'network_profiles.dart';
import 'network_runtime.dart';
import 'remote_adapter.dart';

/// Keeps a reviewed identity write in the catalog's existing serialization lane.
/// Status remains a read, including the verification after an unknown write.
class CatalogNetworkIdentityStore implements NetworkIdentityStore {
  CatalogNetworkIdentityStore({required this.catalog,required this.profile,required this.expectedRevision,
    required this.closeAffected,required this.delegate,this.runtime=const NativeNetworkRuntime()});
  final HostCatalog catalog;
  final NetworkProfile profile;
  final String expectedRevision;
  final void Function() closeAffected;
  final NetworkIdentityStore delegate;
  final NativeNetworkRuntime runtime;
  @override
  bool get supported => delegate.supported;
  void check(NetworkProfile requested) {
    if (jsonEncode(requested.toJson()) != jsonEncode(profile.toJson())) {
      throw const RemoteFailure('network_profile_stale');
    }
  }
  void checkCurrent() {
    if (!catalog.ready || catalog.revision != expectedRevision ||
        !catalog.networkProfiles.any((p) => jsonEncode(p.toJson()) == jsonEncode(profile.toJson()))) {
      throw const RemoteFailure('network_profile_stale');
    }
  }
  @override
  Future<NetworkIdentityRecord?> status(NetworkProfile requested) {
    check(requested); return delegate.status(profile);
  }
  @override
  Future<NetworkIdentityRecord> create(NetworkProfile requested,String mode,Uint8List secret) {
    check(requested);
    return catalog.guardedNetworkOperation(profile,expectedRevision:expectedRevision,
      beforeDispatch:closeAffected,operation:() async {
        await runtime.stopBeforeChange(profile);
        checkCurrent();
        return delegate.create(profile,mode,secret);
      });
  }
  @override
  Future<void> delete(NetworkProfile requested,NetworkIdentityRecord identity) {
    check(requested);
    return catalog.guardedNetworkOperation(profile,expectedRevision:expectedRevision,
      beforeDispatch:closeAffected,operation:() async {
        await runtime.stopBeforeChange(profile);
        checkCurrent();
        return delegate.delete(profile,identity);
      });
  }
}

class NetworkIdentityDialog extends StatefulWidget {
  const NetworkIdentityDialog({super.key,required this.profile,required this.catalog,
    required this.closeTabs,required this.store,this.runtime=const NativeNetworkRuntime()});
  final NetworkProfile profile;
  final HostCatalog catalog;
  final void Function(Set<String>) closeTabs;
  final NetworkIdentityStore store;
  final NativeNetworkRuntime runtime;
  @override
  State<NetworkIdentityDialog> createState() => _NetworkIdentityDialogState();
}

class _NetworkIdentityDialogState extends State<NetworkIdentityDialog> with WidgetsBindingObserver {
  final secret = TextEditingController();
  late final NetworkIdentitySession session;
  late final String capturedRevision;
  late final List<HostProfile> affected;
  String mode = 'PRIVATE';
  bool reviewed = false;
  String? inputError;
  // Our own serialized identity operation sets writing without changing the
  // revision. That must not invalidate this same review while it is pending.
  bool current() => widget.catalog.ready && widget.catalog.revision == capturedRevision &&
    widget.catalog.networkProfiles.any((p) => jsonEncode(p.toJson()) == jsonEncode(widget.profile.toJson()));
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    capturedRevision = widget.catalog.revision;
    affected = List<HostProfile>.unmodifiable(widget.catalog.networkImpact(widget.profile.id));
    final affectedIds = Set<String>.unmodifiable(affected.map((p) => p.id));
    final guarded = CatalogNetworkIdentityStore(catalog:widget.catalog,profile:widget.profile,
      expectedRevision:capturedRevision,closeAffected:() => widget.closeTabs(affectedIds),delegate:widget.store,runtime:widget.runtime);
    session = NetworkIdentitySession(profile:widget.profile,store:guarded,stillCurrent:current,
      closeAffected:() {});
    session.addListener(changed); widget.catalog.addListener(changed);
    session.refresh();
  }
  void changed() { if (mounted) setState(() {}); }
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.inactive || state == AppLifecycleState.hidden ||
        state == AppLifecycleState.paused || state == AppLifecycleState.detached) {
      secret.clear();
      if (mounted) setState(() { reviewed = false; });
    }
  }
  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    secret.clear(); secret.dispose(); session.removeListener(changed); session.dispose();
    widget.catalog.removeListener(changed); super.dispose();
  }
  Future<void> create() async {
    if (!reviewed || !session.canCreate) return;
    if (secret.text.length > 1024) {
      setState(() { inputError = '加入密码最多 1024 个 UTF-8 字节。'; });
      return;
    }
    final bytes = Uint8List.fromList(utf8.encode(secret.text));
    try { validateNetworkSecret(mode,bytes); }
    catch (_) {
      bytes.fillRange(0,bytes.length,0);
      setState(() { inputError = '加入密码须为 1–1024 个 UTF-8 字节且不含 NUL；无密码网络请明确选择对应模式。'; });
      return;
    }
    // Clear the visible field before dispatch. Dart strings/codec copies cannot
    // be proven erased; no password is retained in a model or catalog.
    secret.clear(); FocusScope.of(context).unfocus();
    setState(() { inputError = null; reviewed = false; });
    await session.create(mode,bytes);
  }
  Future<void> remove() async {
    final record = session.record;
    if (!session.canDelete || record == null) return;
    final confirmed = await showDialog<bool>(context:context,builder:(context) => AlertDialog(
      title:const Text('移除本机入网资料'),
      content:SingleChildScrollView(child:Column(mainAxisSize:MainAxisSize.min,crossAxisAlignment:CrossAxisAlignment.start,children:[
        Text('只移除“${widget.profile.label}”在本设备的入网资料。'),
        Text(affected.isEmpty ? '当前没有主机引用此网络。' : '先停止以下 ${affected.length} 个主机的本地标签：'),
        for (final host in affected) Text('• ${host.label}'),
        const Text('远端任务、SSH 配对密钥和其他网络保持不变。之后需主动重新配置，不会自动创建身份。'),
      ])),
      actions:[TextButton(onPressed:() => Navigator.pop(context,false),child:const Text('取消')),
        FilledButton(key:const ValueKey('network-identity-delete-confirm'),
          onPressed:() => Navigator.pop(context,true),child:const Text('确认移除'))]));
    if (confirmed == true && mounted && current() && session.record?.handle == record.handle) await session.delete();
  }
  @override
  Widget build(BuildContext context) {
    return AlertDialog(title:const Text('本机入网资料'),scrollable:true,
      content:SizedBox(width:420,child:Column(mainAxisSize:MainAxisSize.min,crossAxisAlignment:CrossAxisAlignment.stretch,children:[
        Text('${widget.profile.label} · ${widget.profile.provider}'),
        const Text('与公开网络配置和 SSH 配对密钥分开保存；不随配置导入导出。保存资料不代表节点已启动或可以连通。'),
        if (!session.supported) const Text('此平台或网络类型的本机存储尚未接入。当前仅 Android EasyTier 提供此入口，不会使用明文存储。'),
        if (!current()) const Text('公开配置已经变化 · 请关闭后按最新资料重新审查。'),
        if (session.busy) const Padding(padding:EdgeInsets.symmetric(vertical:12),child:LinearProgressIndicator()),
        if (session.notice != null) Text(session.notice!,key:const ValueKey('network-identity-notice')),
        if (session.supported && !session.known && !session.busy)
          const Text('本机状态未确认 · 先读取状态，创建与移除暂不可用。'),
        if (session.record != null) ...[
          const Text('已找到本机资料 · 连通尚未验证',key:ValueKey('network-identity-present')),
          Text(session.record!.mode == 'PRIVATE' ? '模式：有加入密码' : '模式：明确无加入密码'),
          TextButton(key:const ValueKey('network-identity-delete'),onPressed:session.canDelete ? remove : null,
            child:const Text('移除本机入网资料…')),
        ],
        if (session.supported && session.known && session.record == null) ...[
          const Text('本设备尚未配置',key:ValueKey('network-identity-absent')),
          DropdownButtonFormField<String>(key:const ValueKey('network-identity-mode'),initialValue:mode,isExpanded:true,
            items:const [DropdownMenuItem(value:'PRIVATE',child:Text('使用加入密码')),
              DropdownMenuItem(value:'PUBLIC_NO_SECRET',child:Text('明确使用无密码网络'))],
            onChanged:session.busy ? null : (value) { if (value != null) setState(() {
              mode = value; secret.clear(); reviewed = false; inputError = null;
            }); }),
          if (mode == 'PRIVATE') TextField(key:const ValueKey('network-identity-secret'),controller:secret,
            obscureText:true,autocorrect:false,enableSuggestions:false,enableIMEPersonalizedLearning:false,
            autofillHints:const [],maxLength:1024,enabled:!session.busy,decoration:const InputDecoration(labelText:'加入密码（仅保存在本设备）')),
          if (mode == 'PUBLIC_NO_SECRET') const Text('无密码模式不会提供共享密码保护。请确认这是该网络的真实配置；不会代填或生成密码。'),
          if (inputError != null) Text(inputError!),
          Text(affected.isEmpty ? '当前没有主机引用此网络。' : '保存前停止以下 ${affected.length} 个主机的本地标签：'),
          for (final host in affected) Text('• ${host.label}'),
          CheckboxListTile(key:const ValueKey('network-identity-review'),contentPadding:EdgeInsets.zero,
            value:reviewed,onChanged:session.canCreate ? (value) => setState(() { reviewed = value == true; }) : null,
            title:const Text('我已核对网络与模式，保存本机资料并停止受影响标签；不自动连接')),
          FilledButton(key:const ValueKey('network-identity-create'),onPressed:reviewed && session.canCreate ? create : null,
            child:const Text('保存本机资料')),
        ],
      ])),actions:[
        TextButton(key:const ValueKey('network-identity-refresh'),onPressed:session.supported && !session.busy ? session.refresh : null,
          child:const Text('重新读取本机状态')),
        TextButton(onPressed:() => Navigator.pop(context),child:const Text('关闭')),
      ]);
  }
}
