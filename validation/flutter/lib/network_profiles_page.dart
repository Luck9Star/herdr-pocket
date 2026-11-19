import 'dart:convert';
import 'package:flutter/material.dart';
import 'design_tokens.dart';
import 'host_catalog.dart';
import 'network_profiles.dart';
import 'network_identity.dart';
import 'network_identity_dialog.dart';
import 'network_runtime.dart';
import 'network_login_dialog.dart';
import 'remote_adapter.dart';
import 'zerotier_device.dart';
import 'zerotier_device_dialog.dart';

class NetworkProfilesPage extends StatefulWidget {
  const NetworkProfilesPage({super.key,required this.catalog,required this.closeTabs,this.identityStore,this.runtime,
    this.zeroTierDeviceStore,this.beforeZeroTierForget,this.closeTabsAndWait,this.desktopSshSession});
  final HostCatalog catalog;
  final void Function(Set<String>) closeTabs;
  final Future<bool> Function(Set<String>)? closeTabsAndWait;
  final NetworkIdentityStore? identityStore;
  final NativeNetworkRuntime? runtime;
  final ZeroTierDeviceStore? zeroTierDeviceStore;
  final BeforeZeroTierForget? beforeZeroTierForget;
  final ({DesignTokens tokens, Widget notice})? desktopSshSession;
  @override
  State<NetworkProfilesPage> createState() => _NetworkProfilesPageState();
}
class _NetworkProfilesPageState extends State<NetworkProfilesPage> with WidgetsBindingObserver {
  HostCatalog get catalog => widget.catalog;
  late final identities = widget.identityStore ?? NativeNetworkIdentityStore();
  late final runtime = widget.runtime ?? const NativeNetworkRuntime();
  final nodes = <String,NetworkNodeSnapshot>{};
  final epochs = <String,int>{};
  final pendingStarts = <String>{};
  final pendingStops = <String>{};
  final startingBindings = <String,NetworkNodeBinding>{};
  final cancelledStarts = <String>{};
  final uncertainStarts = <String,NetworkNodeBinding>{};
  final stoppedStarts = <String>{};
  bool foreground = true;
  bool currentProfile(NetworkProfile profile) => catalog.ready &&
    catalog.networkProfiles.any((p) => jsonEncode(p.toJson()) == jsonEncode(profile.toJson()));
  int nextEpoch(String id) => epochs[id] = (epochs[id] ?? 0) + 1;
  bool currentEpoch(String id,int value) => mounted && foreground && epochs[id] == value;
  bool canChange(NetworkProfile profile) => available && !pendingStarts.contains(profile.id) &&
    !pendingStops.contains(profile.id) && !uncertainStarts.containsKey(profile.id) && !runtime.stopUncertain(profile.id);
  void closeAffected(NetworkProfile profile) => widget.closeTabs(catalog.networkImpact(profile.id).map((p) => p.id).toSet());
  Future<void> beforeChange(NetworkProfile profile) async {
    closeAffected(profile);
    await runtime.stopBeforeChange(profile);
    nextEpoch(profile.id);
    // This path also permits proven-unavailable offline edits. Do not turn
    // that exception into a claim that a native node was observed Stopped.
    if (mounted) setState(() { nodes[profile.id] = const NetworkNodeSnapshot('unknown',null); });
  }
  Future<void> nodeStatus(NetworkProfile profile) async {
    final epoch = nextEpoch(profile.id);
    try {
      final result = await runtime.profileStatus(profile);
      if (currentEpoch(profile.id,epoch) && currentProfile(profile)) setState(() {
        nodes[profile.id] = result;
        if (!pendingStarts.contains(profile.id)) uncertainStarts.remove(profile.id);
      });
    } catch (_) {
      if (currentEpoch(profile.id,epoch) && currentProfile(profile)) setState(() {
        nodes[profile.id] = NetworkNodeSnapshot('unknown',nodes[profile.id]?.binding ?? startingBindings[profile.id]);
      });
    }
  }
  Future<void> startNode(NetworkProfile profile) async {
    if (!canChange(profile) || !profile.enabled || !{'easytier','tailscale'}.contains(profile.provider) ||
        nodes[profile.id]?.state != 'stopped') return;
    final revision = catalog.revision;
    stoppedStarts.remove(profile.id);
    pendingStarts.add(profile.id);
    final epoch = nextEpoch(profile.id);
    NetworkNodeBinding? dispatched;
    setState(() { notice = null; });
    try {
      if (!await runtime.providerAvailable(profile.provider)) throw const RemoteFailure('provider_unavailable');
      final identity = await identities.status(profile);
      if (identity == null) throw const RemoteFailure('network_identity_unavailable');
      if (profile.provider == 'easytier' && identity.mode != 'PRIVATE') throw const RemoteFailure('network_public_unsupported');
      final binding = NetworkNodeBinding.forProfile(profile,identity);
      if (!currentEpoch(profile.id,epoch)) return;
      startingBindings[profile.id] = binding;
      setState(() { nodes[profile.id] = NetworkNodeSnapshot('starting',binding); });
      final result = await catalog.guardedNetworkOperation(profile,expectedRevision:revision,
        operation:() {
          if (cancelledStarts.contains(profile.id)) throw const RemoteFailure('network_start_cancelled');
          dispatched = binding;
          return profile.provider == 'tailscale' ? runtime.startTailscale(binding,profile)
            : runtime.start(binding,(profile.settings['peers'] as List).cast<String>());
        });
      if (currentEpoch(profile.id,epoch)) setState(() { nodes[profile.id] = result; });
      else if (dispatched != null && !stoppedStarts.contains(profile.id)) {
        // A refresh issued during the pending start may predate admission.
        // Keep its display but require another status read after completion.
        uncertainStarts[profile.id] = dispatched!;
      }
    } catch (error) {
      if (dispatched != null && !stoppedStarts.contains(profile.id)) uncertainStarts[profile.id] = dispatched!;
      if (currentEpoch(profile.id,epoch)) setState(() {
        nodes[profile.id] = NetworkNodeSnapshot('unknown',dispatched);
        notice = error is RemoteFailure && error.code == 'network_public_unsupported'
          ? '当前固定 EasyTier 引擎不支持无密码模式，未启动。' : '节点启动未确认 · 请刷新状态或停止原绑定，不会自动重试。';
      });
    } finally { pendingStarts.remove(profile.id); startingBindings.remove(profile.id); cancelledStarts.remove(profile.id);
      stoppedStarts.remove(profile.id); if (mounted) setState(() {}); }
  }
  Future<void> stopNode(NetworkProfile profile) async {
    final binding = nodes[profile.id]?.binding ?? startingBindings[profile.id] ?? uncertainStarts[profile.id];
    if (binding == null || pendingStops.contains(profile.id)) return;
    if (pendingStarts.contains(profile.id)) cancelledStarts.add(profile.id);
    pendingStops.add(profile.id); final epoch = nextEpoch(profile.id);
    setState(() { nodes[profile.id] = NetworkNodeSnapshot('closing',binding); notice = null; });
    try {
      var transportClosed = true;
      try {
        final close = widget.closeTabsAndWait;
        if (close == null) { closeAffected(profile); }
        else { transportClosed = await close(catalog.networkImpact(profile.id).map((p) => p.id).toSet()); }
      } catch (_) { transportClosed = false; }
      final result = await runtime.stop(binding);
      if (result.state == 'stopped') {
        if (pendingStarts.contains(profile.id)) stoppedStarts.add(profile.id);
        uncertainStarts.remove(profile.id);
      }
      if (currentEpoch(profile.id,epoch)) setState(() {
        nodes[profile.id] = result;
        if (!transportClosed) notice = '原节点停止结果已返回；对应 SSH 清退尚未确认，不能视为连接已关闭。';
      });
    } catch (_) {
      if (currentEpoch(profile.id,epoch)) setState(() { nodes[profile.id] = NetworkNodeSnapshot('closing',binding);
        notice = '停止尚未确认 · 可刷新状态或对原绑定再次明确停止；不自动重试。'; });
    } finally { pendingStops.remove(profile.id); if (mounted) setState(() {}); }
  }
  bool busy = false;
  String? notice;
  bool get available => foreground && catalog.ready && !catalog.writing && !busy;
  @override
  void initState() { super.initState(); catalog.addListener(changed); WidgetsBinding.instance.addObserver(this); }
  void changed() { if (mounted) setState(() {}); }
  @override
  void dispose() { WidgetsBinding.instance.removeObserver(this); catalog.removeListener(changed); super.dispose(); }
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed) {
      foreground = false;
      for (final profile in catalog.networkProfiles) {
        nextEpoch(profile.id);
        final binding = nodes[profile.id]?.binding ?? startingBindings[profile.id];
        if (binding != null) nodes[profile.id] = NetworkNodeSnapshot('unknown',binding);
      }
      if (mounted) setState(() {});
    } else {
      foreground = true;
      if (mounted) setState(() {});
      for (final profile in catalog.networkProfiles) {
        if ({'easytier','tailscale'}.contains(profile.provider) && runtime.supported) nodeStatus(profile);
      }
    }
  }
  Future<void> action(Future<void> Function() work) async {
    if (!available) return;
    setState(() { busy = true; notice = null; });
    try { await work(); }
    catch (error) {
      if (mounted) setState(() { notice = switch (error is RemoteFailure ? error.code : '') {
        'network_in_use' => '此网络仍被主机引用 · 请先从主机列表明确更换或解除网络绑定后再删除',
        'invalid_network_profile' => '公开网络资料格式无效 · 尚未保存，请检查字段；不接受密钥、令牌或加入密码',
        'network_revision_limit' => '此配置版本已达上限 · 请明确创建新配置并重新绑定',
        'network_identity_present' => '此配置仍有本机入网资料 · 请先打开“本机入网资料”明确移除，再删除公开配置。',
        'network_identity_unavailable' => '无法核对本机入网资料 · 请解锁并重新读取，暂不删除公开配置。',
        _ => '操作未确认或预览已过期 · 已停止，请重新读取核验；不会重放',
      }; });
    }
    if (mounted) setState(() { busy = false; });
  }
  Future<bool> confirm(NetworkProfile profile,String verb,List<HostProfile> affected) async =>
    await showDialog<bool>(context:context,builder:(context) => AlertDialog(title:Text('$verb网络配置'),
      content:SingleChildScrollView(child:Column(mainAxisSize:MainAxisSize.min,crossAxisAlignment:CrossAxisAlignment.start,children:[
        Text('“${profile.label}” · ${profile.provider}'),
        Text(affected.isEmpty ? '当前没有主机引用此配置。' : '实际受影响的 ${affected.length} 个主机：'),
        for (final host in affected) Text('• ${host.label}'),
        Text(verb == '删除' && affected.isNotEmpty
          ? '仍被引用时拒绝删除。请先从主机列表明确更换或解除绑定；解除后将使用系统直连。'
          : '仅停止以上主机的本地标签与输入；不会重放、自动连接、终止远端任务或迁移网络身份。'),
      ])),actions:[TextButton(onPressed:() => Navigator.pop(context,false),child:const Text('取消')),
        FilledButton(key:const ValueKey('network-confirm'),onPressed:() => Navigator.pop(context,true),child:Text('确认$verb'))])) == true;
  Future<void> edit([NetworkProfile? profile]) async {
    if (!available || (profile != null && !canChange(profile))) return;
    final captured = catalog.revision;
    final result = await showDialog<NetworkProfile>(context:context,builder:(_) => _NetworkEditor(profile:profile));
    if (result == null || !mounted) return;
    if (profile == null) { await action(() => catalog.addNetwork(result)); return; }
    final affected = catalog.networkImpact(profile.id);
    if (!await confirm(profile,'编辑',affected) || !mounted) return;
    await action(() => catalog.updateNetwork(result,expectedRevision:captured,beforeChange:() => beforeChange(profile)));
  }
  Future<void> toggle(NetworkProfile profile) async {
    final captured = catalog.revision,affected = catalog.networkImpact(profile.id);
    if (!await confirm(profile,profile.enabled ? '停用' : '启用',affected) || !mounted) return;
    await action(() => catalog.updateNetwork(profile.change(enabled:!profile.enabled),expectedRevision:captured,
      beforeChange:() => beforeChange(profile)));
  }
  Future<void> remove(NetworkProfile profile) async {
    final captured = catalog.revision,affected = catalog.networkImpact(profile.id);
    if (!await confirm(profile,'删除',affected) || !mounted) return;
    await action(() => catalog.removeNetwork(profile,expectedRevision:captured,
      beforeRemove:() async {
        if ({'easytier','tailscale'}.contains(profile.provider) && identities.supported && await identities.status(profile) != null) {
          throw const RemoteFailure('network_identity_present');
        }
        await beforeChange(profile);
      }));
  }
  Future<void> localIdentity(NetworkProfile profile) async {
    if (!canChange(profile)) return;
    if (profile.provider == 'zerotier') { await sharedZeroTierDevice(); return; }
    await showDialog<void>(context:context,builder:(_) => NetworkIdentityDialog(profile:profile,catalog:catalog,
      closeTabs:widget.closeTabs,store:identities,runtime:runtime));
    if (mounted && currentProfile(profile) && runtime.supported) await nodeStatus(profile);
  }
  Future<void> sharedZeroTierDevice() async {
    if (!available) return;
    await showDialog<void>(context:context,builder:(_) => ZeroTierDeviceDialog(catalog:catalog,
      store:widget.zeroTierDeviceStore ?? NativeZeroTierDeviceStore(),beforeForget:widget.beforeZeroTierForget));
  }
  bool loginReady(NetworkProfile profile) {
    final binding = nodes[profile.id]?.binding;
    return canChange(profile) && profile.enabled && profile.provider == 'tailscale' &&
      binding != null && binding.provider == 'tailscale' && binding.profileRevision == profile.revision &&
      binding.networkName == tailscaleNetworkName(profile) &&
      {'starting','needs-login','needs-machine-auth','running'}.contains(nodes[profile.id]?.state);
  }
  Future<void> login(NetworkProfile profile) async {
    if (!loginReady(profile)) return;
    await showDialog<void>(context:context,builder:(_) => TailscaleLoginDialog(profile:profile,
      binding:nodes[profile.id]!.binding!,catalog:catalog,runtime:runtime));
    if (mounted && currentProfile(profile) && foreground) await nodeStatus(profile);
  }
  String providerName(String provider) => switch (provider) {
    'tailscale' => 'Tailscale', 'easytier' => 'EasyTier', 'zerotier' => 'ZeroTier', _ => provider,
  };
  String hostSummary(NetworkProfile profile) {
    final hosts = catalog.networkImpact(profile.id);
    if (hosts.isEmpty) return '未绑定主机';
    return hosts.length == 1 ? '主机：${hosts.first.label}' : '主机：${hosts.first.label} 等 ${hosts.length} 台';
  }
  VoidCallback? get addNetwork => available && catalog.networkProfiles.length < maxNetworkProfiles ? () => edit() : null;

  Widget desktopEmptyCard(DesignTokens tokens) {
    final large = MediaQuery.textScalerOf(context).scale(1) > 1;
    return Container(key: const ValueKey('network-empty-card'),
    height: large ? null : 204, padding: const EdgeInsets.all(16),
    decoration: BoxDecoration(color: tokens.color('card'), borderRadius: BorderRadius.circular(16)),
    foregroundDecoration: BoxDecoration(borderRadius: BorderRadius.circular(16), border: Border.all(color: tokens.color('border'))),
    child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Align(alignment: Alignment.centerLeft, child: Container(width: 44, height: 44,
        decoration: BoxDecoration(color: tokens.color('cardSubtle'), borderRadius: BorderRadius.circular(10)),
        child: Icon(Icons.language, color: tokens.color('textSecondary')))),
      const SizedBox(height: 12),
      const Text('还没有网络配置', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600)),
      const SizedBox(height: 4),
      Text('配置 ZeroTier、Tailscale 或 EasyTier 后，在这里管理网络。',
        style: TextStyle(fontSize: 13, color: tokens.color('textSecondary'))),
      if (large) const SizedBox(height: 16) else const Spacer(),
      SizedBox(height: large ? null : 48, child: OutlinedButton(key: const ValueKey('networks-add'),
        style: OutlinedButton.styleFrom(foregroundColor: tokens.color('textPrimary'),
          side: BorderSide(color: tokens.color('borderStrong')), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10))),
        onPressed: addNetwork, child: const Text('添加网络配置'))),
    ]));
  }

  @override
  Widget build(BuildContext context) {
    final desktop = widget.desktopSshSession;
    final desktopEmpty = desktop != null && catalog.ready && catalog.networkProfiles.isEmpty;
    final content = <Widget>[
      if (desktop != null) ...[
        const SizedBox(height: 30, child: Text('网络', style: TextStyle(fontSize: 22, fontWeight: FontWeight.w600, height: 1))),
        const SizedBox(height: 16),
        desktop.notice,
        const SizedBox(height: 16),
      ],
      if (desktopEmpty) ...[desktopEmptyCard(desktop.tokens), const SizedBox(height: 12)],
      if (!catalog.ready) ...[
        Semantics(liveRegion: true, child: Text(catalog.reading ? '正在重新读取本机网络配置' : catalog.status,
          key: const ValueKey('networks-catalog-status'))),
        const SizedBox(height: 12),
      ],
      Text('网络配置可供多台主机复用。保存不代表已入网或 SSH 可用。',
        style:Theme.of(context).textTheme.bodySmall),
      const SizedBox(height:12),
      Wrap(spacing:8,runSpacing:8,children:[
        if (!desktopEmpty) FilledButton.icon(key:const ValueKey('networks-add'),
          onPressed:addNetwork,
          icon:const Icon(Icons.add),label:const Text('新增网络')),
        OutlinedButton.icon(key:const ValueKey('networks-zerotier-device'),
          onPressed:available ? sharedZeroTierDevice : null,
          icon:const Icon(Icons.devices),label:const Text('ZeroTier 共享身份')),
      ]),
      if (notice != null) Padding(padding:const EdgeInsets.symmetric(vertical:12),child:Text(notice!,key:const ValueKey('networks-notice'))),
      if (desktop == null && catalog.ready && catalog.networkProfiles.isEmpty) const Padding(padding:EdgeInsets.symmetric(vertical:24),
        child:Text('暂无网络配置 · 本地配对仍可继续')),
      const SizedBox(height:8),
      for (final profile in catalog.networkProfiles) Card(key:ValueKey('network-card-${profile.id}'),color:Theme.of(context).colorScheme.surface,elevation:0,clipBehavior:Clip.antiAlias,
        shape:RoundedRectangleBorder(borderRadius:BorderRadius.circular(14),
          side:BorderSide(color:Theme.of(context).colorScheme.outlineVariant)),
        child:ExpansionTile(key:PageStorageKey('network-details-${profile.id}'),
          title:Text('${profile.label} · ${providerName(profile.provider)}',
            style:Theme.of(context).textTheme.titleSmall?.copyWith(fontWeight:FontWeight.w700)),
          subtitle:DefaultTextStyle.merge(
            style:Theme.of(context).textTheme.bodySmall!.copyWith(color:Theme.of(context).colorScheme.onSurfaceVariant),
            child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[
            Text(profile.enabled ? '本机启用 · 不代表已入网' : '本机停用'),
            if ({'easytier','tailscale'}.contains(profile.provider))
              Text('节点：${networkNodeStateLabel(nodes[profile.id]?.state)}',key:ValueKey('network-node-status-${profile.id}'))
            else const Text('设备与入网状态未读取'),
            Text(hostSummary(profile)),
            if (uncertainStarts.containsKey(profile.id)) const Text('启动结果或期间状态未确认 · 启动和配置写入已锁定；请刷新状态或停止原绑定。'),
            if (runtime.stopUncertain(profile.id)) const Text('停止尚未确认 · 配置写入已锁定；请刷新状态或明确停止原绑定。'),
          ])),
          childrenPadding:const EdgeInsets.fromLTRB(16,0,16,12),
          children:[Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
            if ({'easytier','tailscale'}.contains(profile.provider)) ...[
              if (profile.provider == 'tailscale') const Text('先配置本机入网资料 → 刷新并启动节点 → 授权 / 等待批准 → 主机配对与看板。节点就绪后仍需主动连接。'),
              Wrap(spacing:8,children:[
                TextButton(key:ValueKey('network-node-refresh-${profile.id}'),onPressed:runtime.supported ? () => nodeStatus(profile) : null,child:const Text('刷新节点状态')),
                TextButton(key:ValueKey('network-node-start-${profile.id}'),onPressed:canChange(profile) && profile.enabled && nodes[profile.id]?.state == 'stopped' ? () => startNode(profile) : null,child:const Text('启动节点')),
                TextButton(key:ValueKey('network-node-stop-${profile.id}'),onPressed:(nodes[profile.id]?.binding != null || startingBindings.containsKey(profile.id) || uncertainStarts.containsKey(profile.id)) && !pendingStops.contains(profile.id) ? () => stopNode(profile) : null,child:const Text('停止原节点')),
                if (profile.provider == 'tailscale') TextButton(key:ValueKey('network-node-login-${profile.id}'),
                  onPressed:loginReady(profile) ? () => login(profile) : null,child:const Text('设备授权与入网状态')),
              ]),
            ],
            SelectableText(key:PageStorageKey('network-settings-${profile.id}'),profile.settings.entries.map((e) => '${e.key}: ${e.value}').join('\n')),
            Wrap(spacing:8,children:[
              TextButton(key:ValueKey('network-identity-${profile.id}'),onPressed:canChange(profile) ? () => localIdentity(profile) : null,child:const Text('本机入网资料')),
              TextButton(key:ValueKey('network-edit-${profile.id}'),onPressed:canChange(profile) ? () => edit(profile) : null,child:const Text('编辑公开参数')),
              TextButton(key:ValueKey('network-toggle-${profile.id}'),onPressed:canChange(profile) ? () => toggle(profile) : null,child:Text(profile.enabled ? '停用与影响预览' : '启用与影响预览')),
              TextButton(key:ValueKey('network-delete-${profile.id}'),onPressed:canChange(profile) ? () => remove(profile) : null,child:const Text('删除与影响预览')),
            ]),
          ])])),
      const SizedBox(height:12),
      Text('入网身份保存在本机。网络组件暂不可用时，已绑定的主机会保持断开；组件恢复后可重新审查并连接。',
        style:Theme.of(context).textTheme.bodySmall),
    ];
    return Scaffold(appBar: desktop == null ? AppBar(title: const Text('网络配置')) : null,
      body: SafeArea(child: ListView(padding: EdgeInsets.fromLTRB(desktop == null ? 16 : 40, 16, desktop == null ? 16 : 40, 16),
        children: desktop == null ? content : [
          Align(alignment: Alignment.topLeft, child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 560),
            child: SizedBox(width: double.infinity, child: Column(crossAxisAlignment: CrossAxisAlignment.stretch,
              children: content)))),
        ])));
  }

}

class _NetworkEditor extends StatefulWidget {
  const _NetworkEditor({this.profile});
  final NetworkProfile? profile;
  @override
  State<_NetworkEditor> createState() => _NetworkEditorState();
}
class _NetworkEditorState extends State<_NetworkEditor> {
  late String provider = widget.profile?.provider ?? 'tailscale';
  late final label = TextEditingController(text:widget.profile?.label ?? '');
  late final fields = <String,TextEditingController>{for (final key in ['controlUrl','hostname','networkName','peers','networkId'])
    key:TextEditingController(text:widget.profile?.settings[key] is List ? (widget.profile!.settings[key] as List).join('\n') : widget.profile?.settings[key]?.toString() ?? '')};
  String? error;
  @override
  void dispose() { label.dispose(); for (final field in fields.values) { field.dispose(); } super.dispose(); }
  Widget input(String key,String title,{bool multiline=false}) => Padding(padding:const EdgeInsets.only(top:12),
    child:TextField(key:ValueKey('network-$key'),controller:fields[key],autocorrect:false,enableSuggestions:false,
      keyboardType:multiline ? TextInputType.multiline : TextInputType.text,minLines:multiline ? 3 : 1,maxLines:multiline ? 6 : 1,
      decoration:InputDecoration(labelText:title)));
  void save() {
    try {
      final settings = switch (provider) {
        'tailscale' => <String,dynamic>{'controlUrl':fields['controlUrl']!.text,'hostname':fields['hostname']!.text},
        'easytier' => <String,dynamic>{'networkName':fields['networkName']!.text,'peers':fields['peers']!.text.split('\n')},
        _ => <String,dynamic>{'networkId':fields['networkId']!.text},
      };
      final profile = widget.profile?.change(label:label.text,settings:settings) ?? NetworkProfile.create(label.text,provider,settings);
      Navigator.pop(context,profile);
    } catch (_) { setState(() { error = '字段格式无效或版本已达上限 · 未保存。仅接受公开配置，身份与秘密在原设备保管。'; }); }
  }
  @override
  Widget build(BuildContext context) => AlertDialog(title:Text(widget.profile == null ? '新增网络配置' : '编辑网络配置'),
    scrollable:true,content:SizedBox(width:420,child:Column(mainAxisSize:MainAxisSize.min,crossAxisAlignment:CrossAxisAlignment.stretch,children:[
      if (error != null) Text(error!,key:const ValueKey('network-editor-error')),
      TextField(key:const ValueKey('network-label'),controller:label,decoration:const InputDecoration(labelText:'公开配置名称')),
      DropdownButtonFormField<String>(key:const ValueKey('network-provider'),initialValue:provider,isExpanded:true,
        items:[for (final p in overlayProviders) DropdownMenuItem(value:p,child:Text(p))],
        onChanged:widget.profile != null ? null : (value) { if (value != null) setState(() { provider = value; error = null; }); }),
      if (provider == 'tailscale') ...[input('controlUrl','控制服务器 HTTPS URL（空为默认）'),input('hostname','本机名（空为 herdr-pocket，ASCII 标签）')],
      if (provider == 'easytier') ...[input('networkName','公开网络名称（不含加入密码）'),input('peers','公开 peer URI（每行一个，1–16 个）',multiline:true),const Text('支持 tcp / udp / ws / wss；tcp、udp 必须填写端口。')],
      if (provider == 'zerotier') input('networkId','公开 network ID（16 位小写十六进制）'),
      const Padding(padding:EdgeInsets.only(top:12),child:Text('保存不会启动网络、加入网络或授权主机。')),
    ])),actions:[TextButton(onPressed:() => Navigator.pop(context),child:const Text('取消')),
      FilledButton(key:const ValueKey('network-save'),onPressed:save,child:const Text('保存公开配置'))]);
}
