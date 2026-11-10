import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'design_tokens.dart';
import 'device_keys.dart';
import 'host_catalog.dart';
import 'pairing_page.dart';
import 'host_tabs.dart';
import 'remote_adapter.dart';
import 'config_transfer_page.dart';
import 'network_profiles_page.dart';
import 'host_task_summary.dart';
import 'host_catalog_search.dart';

String blockedSummaryGroupKey(String hostId,{bool compact=false}) => '${compact ? 'workspace' : 'host'}-blocked-$hostId';
String blockedSummaryTargetKey(String hostId,RemotePane pane,{bool compact=false}) =>
  '${compact ? 'workspace' : 'host'}-blocked-target-${jsonEncode([hostId,pane.paneId,pane.terminalId])}';

class HostCatalogPage extends StatefulWidget {
  const HostCatalogPage({super.key,required this.tokens,required this.offlineBuilder,this.catalog,this.keys,this.tabs,this.adapterFactory});
  final DesignTokens tokens;
  final WidgetBuilder offlineBuilder;
  final HostCatalog? catalog;
  final DeviceKeys? keys;
  final HostTabs? tabs;
  final RemoteReadOnlyAdapter Function(HostProfile)? adapterFactory;
  @override
  State<HostCatalogPage> createState() => _HostCatalogPageState();
}
class _HostCatalogPageState extends State<HostCatalogPage> with WidgetsBindingObserver {
  late final catalog = widget.catalog ?? HostCatalog();
  late final tabs = widget.tabs ?? HostTabs();
  late final summaries = HostTaskSummaries(catalog);
  String? notice;
  bool busy = false;
  final hostSearch = TextEditingController();
  HostTaskFilter taskFilter = HostTaskFilter.all;
  @override
  void initState() {
    super.initState(); catalog.addListener(changed); tabs.addListener(tabChanged); summaries.addListener(tabChanged);
    WidgetsBinding.instance.addObserver(this);
    summaries.setForeground(WidgetsBinding.instance.lifecycleState == null || WidgetsBinding.instance.lifecycleState == AppLifecycleState.resumed);
    unawaited(catalog.load());
  }
  @override void didChangeAppLifecycleState(AppLifecycleState state) => summaries.setForeground(state == AppLifecycleState.resumed);
  void changed() { tabs.reconcile(catalog.ready ? catalog.profiles : const [],catalog.networkProfiles); if (mounted) setState(() {}); }
  void tabChanged() { if (mounted) setState(() {}); }
  @override
  void dispose() { hostSearch.dispose(); WidgetsBinding.instance.removeObserver(this); summaries.removeListener(tabChanged); summaries.dispose(); catalog.removeListener(changed); tabs.removeListener(tabChanged); if (widget.tabs == null) tabs.dispose(); if (widget.catalog == null) catalog.dispose(); super.dispose(); }
  Future<void> action(Future<void> Function() work) async {
    if (busy) return;
    setState(() { busy = true; notice = null; });
    try { await work(); } catch (_) { if (mounted) setState(() { notice = '本机操作未确认 · 已停止，请重新读取核验；不会重放'; }); }
    if (mounted) setState(() { busy = false; });
  }
  Future<void> open([HostProfile? profile]) async {
    if (busy || !catalog.ready || catalog.writing || profile?.enabled == false) return;
    if (profile != null && profile.hasIdentity) {
      if (profile.requiresNetworkBinding) { setState(() { notice = '请先通过主机的“选择／解除网络绑定”选择相同 provider 的本机网络，再新建视图；不会使用系统直连。'; }); return; }
      tabs.open(profile,networks:catalog.networkProfiles,adapter:widget.adapterFactory?.call(profile)); return; }
    tabs.select(null);
    await Navigator.push<void>(context,MaterialPageRoute(builder:(_) => PairingPage(tokens:widget.tokens,keys:widget.keys,
      catalog:catalog,profileId:profile?.id,summaryLeaseFactory:(profile) => summaries.open(profile))));
    if (mounted) setState(() {});
  }
  void openPane(HostTab source,RemotePane pane) {
    if (busy || !catalog.ready || catalog.writing || tabs.activeId != source.id || !source.visible.value || tabs.find(source.id) != source) return;
    final matches = catalog.profiles.where((p) => p.id == source.hostId && p.enabled && !p.retired).toList();
    if (matches.length != 1 || HostTab.bindingFor(matches.single,catalog.networkProfiles) != source.binding) return;
    final profile = matches.single;
    tabs.open(profile,networks:catalog.networkProfiles,requestedTarget:pane,adapter:widget.adapterFactory?.call(profile));
  }
  void openBlocked(HostProfile profile,HostTaskSummary report,RemotePane pane) {
    if (busy || !catalog.ready || catalog.writing) return;
    final target = summaries.blockedTarget(profile.id,report,pane);
    final matches = catalog.profiles.where((p) => p.id == profile.id && p.enabled && !p.retired && p.hasIdentity).toList();
    if (target == null || matches.length != 1 ||
        HostTab.bindingFor(matches.single,catalog.networkProfiles) != HostTab.bindingFor(profile,catalog.networkProfiles)) {
      setState(() { notice = '原受阻报告或主机身份已改变 · 请重新核查，不会选择替代目标'; });
      return;
    }
    if (tabs.tabs.length >= maxOpenHostTabs) {
      tabs.open(matches.single,networks:catalog.networkProfiles,requestedTarget:target);
      return;
    }
    tabs.open(matches.single,networks:catalog.networkProfiles,requestedTarget:target,
      adapter:widget.adapterFactory?.call(matches.single));
  }
  Future<void> transfer() async {
    if (busy || !catalog.ready || catalog.writing || catalog.pendingCreation != null) return;
    tabs.select(null);
    await Navigator.push<void>(context,MaterialPageRoute(builder:(_) => ConfigTransferPage(catalog:catalog,
      closeTabs:(ids) { for (final id in ids) { tabs.closeHost(id); } })));
    if (mounted) setState(() {});
  }
  Future<void> terminalPreferences() async {
    if (busy || !catalog.ready || catalog.writing) return;
    final captured = catalog.revision;
    var size = catalog.terminalFontSize;
    final result = await showDialog<int>(context:context,builder:(context) => StatefulBuilder(builder:(context,update) => AlertDialog(
      title:const Text('终端字号'),content:Column(mainAxisSize:MainAxisSize.min,children:[
        Text('$size px',key:const ValueKey('terminal-font-preview')),
        Slider(key:const ValueKey('terminal-font-slider'),value:size.toDouble(),min:10,max:28,divisions:18,label:'$size px',
          onChanged:(value) => update(() { size = value.round(); })),
        const Text('仅改变本机文字显示。不会调整远端共享终端尺寸或发送输入。'),
      ]),actions:[TextButton(onPressed:() => Navigator.pop(context),child:const Text('取消')),
        FilledButton(key:const ValueKey('terminal-font-save'),onPressed:() => Navigator.pop(context,size),child:const Text('保存本机字号'))])));
    if (result != null) await action(() => catalog.updateTerminalFontSize(result,expectedRevision:captured));
  }

  Future<void> networks() async {
    if (busy || !catalog.ready || catalog.writing) return;
    tabs.select(null);
    await Navigator.push<void>(context,MaterialPageRoute(builder:(_) => NetworkProfilesPage(catalog:catalog,
      closeTabs:(ids) { for (final id in ids) { tabs.closeHost(id); } })));
    if (mounted) setState(() {});
  }
  Future<void> configureNetwork(HostProfile profile) async {
    final captured = catalog.revision;
    var selected = profile.networkProfileId ?? '';
    final result = await showDialog<String>(context:context,builder:(context) => StatefulBuilder(builder:(context,update) => AlertDialog(
      title:const Text('主机网络绑定'),scrollable:true,content:Column(mainAxisSize:MainAxisSize.min,crossAxisAlignment:CrossAxisAlignment.stretch,children:[
        Text(profile.requiresNetworkBinding ? '此公开资料首次须绑定 ${profile.provider} 本机网络；请先在网络管理中创建并启用对应配置。' : '选择可复用的公开网络配置。旧 provider 标签不会改变路由。系统直连沿用当前操作系统路由；overlay 无连接桥时会明确停止。'),
        DropdownButtonFormField<String>(key:const ValueKey('host-network-choice'),initialValue:selected,isExpanded:true,
          items:[DropdownMenuItem(value:'',enabled:!profile.requiresNetworkBinding,child:Text(profile.requiresNetworkBinding ? '请选择对应网络' : '系统直连（沿用系统路由）')),
            for (final network in catalog.networkProfiles) DropdownMenuItem(value:network.id,enabled:network.enabled && (!profile.requiresNetworkBinding || network.provider == profile.provider),
              child:Text('${network.label} · ${network.provider}${network.enabled ? '' : ' · 停用'}',overflow:TextOverflow.ellipsis))],
          onChanged:(value) { if (value != null) update(() { selected = value; }); }),
      ]),actions:[TextButton(onPressed:() => Navigator.pop(context),child:const Text('取消')),
        FilledButton(key:const ValueKey('host-network-preview'),onPressed:() => Navigator.pop(context,selected),child:const Text('预览绑定影响'))])));
    if (result == null || !mounted || result == (profile.networkProfileId ?? '')) return;
    final confirmed = await showDialog<bool>(context:context,builder:(context) => AlertDialog(title:const Text('确认主机网络更换'),
      content:Text('实际受影响主机：${profile.label}\n将先停止此主机的本地标签与输入。${result.isEmpty ? '解除绑定后将改为系统直连，沿用系统路由。' : '将使用指定网络配置；手机桥未接入时返回 provider_unavailable。'}其他主机标签不变；不会自动连接或重放。'),
      actions:[TextButton(onPressed:() => Navigator.pop(context,false),child:const Text('取消')),
        FilledButton(key:const ValueKey('host-network-confirm'),onPressed:() => Navigator.pop(context,true),child:const Text('确认更换并停止此主机'))]));
    if (confirmed != true || !mounted) return;
    await action(() => catalog.update(profile.change(networkProfileId:result.isEmpty ? null : result,replaceNetwork:true,now:catalog.clock()),
      expectedRevision:captured,beforeCommit:() => tabs.closeHost(profile.id)));
  }

  Future<void> rename(HostProfile profile) async {
    final controller = TextEditingController(text:profile.label);
    final label = await showDialog<String>(context:context,builder:(context) => AlertDialog(title:const Text('重命名本机资料'),
      content:TextField(key:const ValueKey('host-rename-input'),controller:controller,maxLength:64,decoration:const InputDecoration(labelText:'名称')),
      actions:[TextButton(onPressed:() => Navigator.pop(context),child:const Text('取消')),
        FilledButton(onPressed:() => Navigator.pop(context,controller.text),child:const Text('保存名称'))]));
    controller.dispose();
    if (label != null) await action(() => catalog.update(profile.change(label:label,now:catalog.clock())));
  }
  Future<void> configureProvider(HostProfile profile) async {
    var provider = profile.provider;
    final selected = await showDialog<String>(context:context,builder:(context) => StatefulBuilder(builder:(context,update) => AlertDialog(
      title:const Text('网络 provider 资料'),
      content:Column(mainAxisSize:MainAxisSize.min,children:[
        const Text('这里只记录此主机的连接配置。不会启动组网、切换网络身份或据此声称已入网。'),
        DropdownButtonFormField<String>(initialValue:provider,items:[for (final value in hostProviders) DropdownMenuItem(value:value,child:Text(hostProviderLabel(value)))],
          onChanged:(value) { if (value != null) update(() { provider = value; }); }),
      ]),actions:[TextButton(onPressed:() => Navigator.pop(context),child:const Text('取消')),
        FilledButton(onPressed:() => Navigator.pop(context,provider),child:const Text('保存配置（入网仍未知）'))])));
    if (selected != null) await action(() => catalog.update(profile.change(provider:selected,now:catalog.clock())));
  }
  Future<void> remove(HostProfile profile) async {
    final confirmed = await showDialog<bool>(context:context,builder:(context) => AlertDialog(
      title:const Text('删除本机资料与设备身份'),
      content:Text('将删除“${profile.label}”的本机资料与此设备密钥。此操作不会撤销主机上的公钥授权；请先在主机核验撤销。若删除未确认，资料会保持停用以便处理。'),
      actions:[TextButton(onPressed:() => Navigator.pop(context,false),child:const Text('取消')),
        FilledButton(onPressed:() => Navigator.pop(context,true),child:const Text('仅删除本机'))]));
    if (confirmed != true) return;
    await action(() async {
      // Persist disabled before deleting the key. A crash between the two never
      // leaves an enabled profile pointing to an identity deliberately removed.
      await catalog.update(profile.change(enabled:false,now:catalog.clock()),beforeCommit:() => tabs.closeHost(profile.id));
      if (profile.hasIdentity) await (widget.keys ?? NativeDeviceKeys()).delete(profile.restore(catalog.clock()).handle);
      await catalog.remove(profile.id);
      if (mounted) notice = '本机已删除 · 主机授权未因此撤销';
    });
  }
  List<HostProfile> get orderedHosts => summaries.orderedHosts;
  HostSearchFields searchFields(HostProfile profile) {
    final bound=catalog.networkProfiles.where((network) => network.id==profile.networkProfileId).toList();
    return HostSearchFields(label:profile.label,session:profile.target['session'] as String,
      host:profile.target['host'] as String,provider:hostSearchProvider(profile.provider,
        hasBinding:profile.networkProfileId != null,boundProvider:bound.length==1 ? bound.single.provider : null));
  }
  HostTaskFilter? searchTargetCategory(HostProfile profile) {
    final report=summaries.forHost(profile.id);
    if (report==null) return null;
    final current=report.freshness==DashboardFreshness.fresh && report.current;
    final select=current ? currentSearchTargets : historicalSearchTargets;
    final targets=select(report.blockedPanes.map((pane) => HostSearchTarget(
      pane.paneId,pane.terminalId,pane.agentStatus)),fresh:report.freshness==DashboardFreshness.fresh,current:report.current);
    if (targets.isEmpty) return null;
    // Authority and binding are report-wide. The search projection has already
    // rejected duplicate pane/terminal IDs, so one candidate is sufficient.
    final target=targets.first;
    final pane=report.blockedPanes.firstWhere((pane) => pane.paneId==target.paneId && pane.terminalId==target.terminalId);
    if (summaries.blockedTarget(profile.id,report,pane)==null) return null;
    return current ? HostTaskFilter.current : HostTaskFilter.history;
  }
  String networkDescription(HostProfile profile) {
    final matches=catalog.networkProfiles.where((network) => network.id==profile.networkProfileId).toList();
    final bound=matches.length==1 ? matches.single : null;
    return hostNetworkDescription(declared:profile.provider,requiresBinding:profile.requiresNetworkBinding,
      hasBinding:profile.networkProfileId != null,boundLabel:bound?.label,boundEnabled:bound?.enabled);
  }
  Widget hostSummary(HostProfile profile,{bool compact=false}) {
    final value = summaries.forHost(profile.id);
    final distinct = <String,RemotePane>{};
    for (final pane in value?.blockedPanes ?? const <RemotePane>[]) {
      distinct.putIfAbsent(jsonEncode([pane.paneId,pane.terminalId]),() => pane);
    }
    return Column(key:ValueKey('${compact ? 'workspace' : 'host'}-task-summary-${profile.id}'),crossAxisAlignment:CrossAxisAlignment.stretch,children:[
      Text(value?.label ?? '任务状态未知 · 尚无此主机的有效会话快照'),
      if (value != null) Text(value.detail),
      if (value != null && distinct.isNotEmpty)
        ExpansionTile(key:ValueKey(blockedSummaryGroupKey(profile.id,compact:compact)),tilePadding:EdgeInsets.zero,
          title:Text('受阻窗格 · ${value.blockedCount} 个'),
          subtitle:Text(value.current ? '打开前仍需审查连接及原目标' : value.freshness == DashboardFreshness.unavailable
            ? '持续更新不可用 · 单次确认报告，打开前重新核查此目标' : '上次报告 · 点击后重新核查此目标'),
          children:[for (final pane in distinct.values)
            ListTile(key:ValueKey(blockedSummaryTargetKey(profile.id,pane,compact:compact)),
              title:Text(pane.label ?? '受阻窗格'),
              subtitle:Text('主机 ${profile.label} · 原会话 ${value.source.session}\npane ${pane.paneId} · terminal ${pane.terminalId}'),
              trailing:const Icon(Icons.chevron_right),
              onTap:busy || !catalog.ready || catalog.writing ? null : () => openBlocked(profile,value,pane))]),
    ]);
  }
  Widget workspaceSummary() {
    final active = tabs.active;
    final profiles = orderedHosts;
    final found = profiles.where((p) => p.id == active?.hostId).toList();
    final profile = found.length == 1 ? found.single : null;
    final value = profile == null ? null : summaries.forHost(profile.id);
    return ExpansionTile(key:const ValueKey('workspace-task-summaries'),tilePadding:const EdgeInsets.symmetric(horizontal:16),
      title:Text('${profile?.label ?? '当前主机'} · ${value?.label ?? '任务状态未知'}'),
      subtitle:Text(value?.detail ?? '尚无有效会话快照 · 展开查看主机摘要'),
      children:[ConstrainedBox(constraints:const BoxConstraints(maxHeight:180),child:ListView(shrinkWrap:true,children:[
        for (final host in profiles) Padding(padding:const EdgeInsets.symmetric(horizontal:16,vertical:6),child:Column(
          crossAxisAlignment:CrossAxisAlignment.stretch,children:[Text(host.label,style:Theme.of(context).textTheme.titleSmall),hostSummary(host,compact:true)])),
      ]))]);
  }
  Widget board() {
    final ordered=orderedHosts;
    // Derived only from existing reports; filtering never opens or retires a lease.
    final categories={for (final host in ordered) host.id:searchTargetCategory(host)};
    final pendingIds={for (final entry in categories.entries) if (entry.value==HostTaskFilter.current) entry.key};
    final historicalIds={for (final entry in categories.entries) if (entry.value==HostTaskFilter.history) entry.key};
    final shown=searchHostCatalog(ordered,query:hostSearch.text,filter:taskFilter,
      fields:searchFields,
      current:(host) => pendingIds.contains(host.id),history:(host) => historicalIds.contains(host.id));
    return ListView(key:const ValueKey('host-catalog-list'),padding:const EdgeInsets.all(16),children:[
    Text(catalog.status,key:const ValueKey('hosts-status')),
    if (notice != null) Padding(padding:const EdgeInsets.symmetric(vertical:12),child:Text(notice!)),
    const SizedBox(height:12),
    FilledButton.icon(key:const ValueKey('hosts-add'),onPressed:catalog.ready && !busy && !catalog.writing && catalog.profiles.length < maxHostProfiles && catalog.pendingCreation == null ? () => open() : null,
      icon:const Icon(Icons.add),label:const Text('新增主机与设备配对')),
    OutlinedButton.icon(key:const ValueKey('hosts-terminal-preferences'),onPressed:catalog.ready && !busy && !catalog.writing ? terminalPreferences : null,
      icon:const Icon(Icons.text_fields),label:Text('终端字号 · ${catalog.terminalFontSize} px')),
    OutlinedButton.icon(key:const ValueKey('hosts-networks'),onPressed:catalog.ready && !busy && !catalog.writing ? networks : null,
      icon:const Icon(Icons.hub_outlined),label:const Text('网络管理 · Tailscale / EasyTier / ZeroTier')),
    OutlinedButton.icon(key:const ValueKey('hosts-transfer'),onPressed:catalog.ready && !busy && !catalog.writing && catalog.pendingCreation == null ? transfer : null,
      icon:const Icon(Icons.import_export),label:const Text('加密导出／导入公开主机资料')),
    if (catalog.ready && catalog.profiles.length >= maxHostProfiles) Padding(padding:const EdgeInsets.symmetric(vertical:12),
      child:Text('本机主机资料已达 $maxHostProfiles 个上限 · 上方新增按钮已禁用；需先删除或整理既有资料',key:const ValueKey('hosts-add-limit-notice'))),
    if (catalog.pendingCreation != null) ...[
      const Padding(padding:EdgeInsets.symmetric(vertical:12),child:Text('上次设备身份创建未完成或结果未知 · 已禁止再次创建，不会自动重放。已返回句柄可明确删除；无句柄时需人工核验本机身份，不能按空记录处理。')),
      if ((catalog.pendingCreation!['handle'] as String).isNotEmpty) TextButton(key:const ValueKey('hosts-delete-pending'),
        onPressed:busy || !catalog.ready ? null : () => action(() async {
          final handle = catalog.pendingCreation!['handle'] as String;
          await (widget.keys ?? NativeDeviceKeys()).delete(handle); await catalog.clearDeletedCreation(handle);
        }),child:const Text('明确删除未完成的本机身份（不撤销主机）')),
    ],
    if (catalog.ready && ordered.isNotEmpty) ...[
      const SizedBox(height:12),
      TextField(key:const ValueKey('hosts-search'),controller:hostSearch,
        // Read the raw text only. Do not rewrite case, selection or IME composing.
        onChanged:(_) => setState(() {}),
        decoration:InputDecoration(labelText:'查找主机或会话',prefixIcon:const Icon(Icons.search),
          suffixIcon:hostSearch.text.isEmpty ? null : IconButton(key:const ValueKey('hosts-search-clear'),
            tooltip:'清除搜索',onPressed:() => setState(hostSearch.clear),icon:const Icon(Icons.clear)))),
      const SizedBox(height:8),
      InputDecorator(decoration:const InputDecoration(labelText:'任务状态'),child:DropdownButtonHideUnderline(
        child:DropdownButton<HostTaskFilter>(key:const ValueKey('hosts-task-filter'),value:taskFilter,isExpanded:true,
          items:[const DropdownMenuItem(value:HostTaskFilter.all,child:Text('全部任务状态')),
            DropdownMenuItem(value:HostTaskFilter.current,child:Text('当前待处理（${pendingIds.length}）')),
            DropdownMenuItem(value:HostTaskFilter.history,child:Text('上次受阻，待核查（${historicalIds.length}）'))],
          onChanged:(value) { if (value != null) setState(() => taskFilter=value); }))),
      Text('显示 ${shown.length} / ${ordered.length} 台主机',key:const ValueKey('hosts-filter-count')),
      if (taskFilter==HostTaskFilter.current) const Text('仅列出当前报告中可定位的受阻目标；历史报告与状态未知不计入。'),
      if (taskFilter==HostTaskFilter.history) const Text('上次明确受阻的目标，当前状态待核查；打开后仍需重新审查连接与原目标。'),
      if (shown.isEmpty) ...[
        const Padding(padding:EdgeInsets.symmetric(vertical:12),child:Text('没有匹配的主机',key:ValueKey('hosts-search-empty'))),
        TextButton(key:const ValueKey('hosts-filters-reset'),onPressed:() => setState(() {
          hostSearch.clear(); taskFilter=HostTaskFilter.all;
        }),child:const Text('清除全部筛选')),
      ],
    ],
    for (final profile in shown) Card(key:ValueKey('host-card-${profile.id}'),child:Padding(padding:const EdgeInsets.all(16),child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
      Text(profile.label,style:Theme.of(context).textTheme.titleMedium),
      hostSummary(profile),
      Text(networkDescription(profile)),
      Text('资料 provider：${hostProviderLabel(profile.provider)} · 入网状态未知\n${profile.target['username']}@${profile.target['host']}:${profile.target['port']}\n会话 ${profile.target['session']} · ${profile.retired ? '已替换停用，保留原身份待撤销' : profile.enabled ? '本机启用' : '本机停用'}\n${profile.hasIdentity ? profile.restore(catalog.clock()).state : '导入未配对 · 无本机身份'} · 在线与主机授权需重新核验'),
      if (profile.retired && profile.hasIdentity) ExpansionTile(title:const Text('原配对公开请求（供主机核验撤销）'),
        children:[SelectableText(profile.restore(catalog.clock()).wire)]),
      const SizedBox(height:8),
      FilledButton(key:ValueKey('host-open-${profile.id}'),onPressed:!busy && catalog.ready && profile.enabled ? () => open(profile) : null,
        child:Text(profile.hasIdentity ? '新建视图并审查连接' : '审查导入目标并在此设备配对')),
      Wrap(spacing:8,children:[
        TextButton(key:ValueKey('host-rename-${profile.id}'),onPressed:busy || !catalog.ready ? null : () => rename(profile),child:const Text('重命名')),
        TextButton(key:ValueKey('host-network-${profile.id}'),onPressed:busy || !catalog.ready || profile.retired ? null : () => configureNetwork(profile),child:const Text('选择／解除网络绑定')),
        TextButton(key:ValueKey('host-provider-${profile.id}'),onPressed:busy || !catalog.ready || profile.requiresNetworkBinding ? null : () => configureProvider(profile),child:const Text('旧 provider 标签（仅资料）')),
        TextButton(key:ValueKey('host-disable-${profile.id}'),onPressed:busy || !catalog.ready || profile.retired ? null : () => action(() => catalog.update(profile.change(enabled:!profile.enabled,now:catalog.clock()),beforeCommit:() => tabs.closeHost(profile.id))),
          child:Text(profile.enabled ? '本机停用（不撤销主机）' : '本机启用（仍需审查）')),
        TextButton(key:ValueKey('host-delete-${profile.id}'),onPressed:busy || !catalog.ready ? null : () => remove(profile),child:const Text('删除本机资料与身份')),
      ]),
    ]))),
    const SizedBox(height:12),TextButton(key:const ValueKey('hosts-offline'),onPressed:() { tabs.select(null); Navigator.push<void>(context,MaterialPageRoute(builder:widget.offlineBuilder)); },child:const Text('进入离线终端实验室')),
    const Text('资料只含公开目标、设备公钥与本机句柄。不会自动连接、替换主机公钥、重建密钥或重放未知操作。'),
  ]);
  }
  Widget tabNavigator(HostTab tab) => ValueListenableBuilder<bool>(valueListenable:tab.visible,
    builder:(context,visible,child) => IgnorePointer(ignoring:!visible,child:ExcludeSemantics(excluding:!visible,
      child:FocusScope(canRequestFocus:visible,child:child!))),
    child:Navigator(key:tab.navigator,onGenerateRoute:(settings) => MaterialPageRoute<void>(settings:settings,
      builder:(_) => PairingPage(tokens:widget.tokens,keys:widget.keys,catalog:catalog,profileId:tab.hostId,
        adapter:tab.adapter,visibility:tab.visible,onViewState:tab.report,requestedTarget:tab.requestedTarget,
        summaryLeaseFactory:(profile) {
          tab.summaryLease?.close();
          final lease = summaries.open(profile,visible:() => tabs.find(tab.id) == tab && tab.visible.value);
          tab.summaryLease = lease; return lease;
        },
        onOpenPane:(pane) => openPane(tab,pane)))));
  Widget tabBar() => SingleChildScrollView(scrollDirection:Axis.horizontal,padding:const EdgeInsets.symmetric(horizontal:12,vertical:6),
    child:Row(children:[
      Padding(padding:const EdgeInsets.only(right:8),child:ChoiceChip(key:const ValueKey('hosts-board-tab'),label:const Text('主机列表'),selected:tabs.activeId == null,onSelected:(_) => tabs.select(null))),
      for (final tab in tabs.tabs) Padding(padding:const EdgeInsets.only(right:8),child:Container(
        decoration:BoxDecoration(border:Border.all(color:tabs.activeId == tab.id ? Theme.of(context).colorScheme.primary : Theme.of(context).dividerColor),borderRadius:BorderRadius.circular(12)),
        child:Row(mainAxisSize:MainAxisSize.min,children:[
          ValueListenableBuilder<HostTabView>(valueListenable:tab.view,builder:(context,view,_) =>
            MergeSemantics(child:Semantics(selected:tabs.activeId == tab.id,child:TextButton(key:ValueKey('host-tab-${tab.id}'),onPressed:() => tabs.select(tab.id),child:ConstrainedBox(
              constraints:const BoxConstraints(maxWidth:260),child:Text('${tab.label} · ${tab.networkLabel}\n${view.target} · ${view.label}',maxLines:2,overflow:TextOverflow.ellipsis)))))),
          IconButton(key:ValueKey('host-tab-close-${tab.id}'),tooltip:'关闭本地标签，不终止远端任务',onPressed:() => tabs.close(tab.id),icon:const Icon(Icons.close,size:18)),
        ]))),
    ]));
  @override
  Widget build(BuildContext context) => PopScope(canPop:tabs.activeId == null,onPopInvokedWithResult:(didPop,result) {
    if (didPop) return;
    final navigator = tabs.active?.navigator.currentState;
    if (navigator?.canPop() == true) { unawaited(navigator!.maybePop()); } else { tabs.select(null); }
  },child:Scaffold(appBar:AppBar(title:const Text('herdr pocket · 主机与标签'),actions:[
    IconButton(key:const ValueKey('hosts-reload'),tooltip:'重新读取本机资料',onPressed:busy || catalog.writing ? null : catalog.load,icon:const Icon(Icons.refresh)),
  ]),body:SafeArea(child:LayoutBuilder(builder:(context,constraints) => Column(children:[
    ConstrainedBox(constraints:BoxConstraints(maxHeight:constraints.maxHeight*.18),child:SingleChildScrollView(child:tabBar())),
    if (tabs.active != null) ConstrainedBox(constraints:BoxConstraints(maxHeight:constraints.maxHeight*.28),child:SingleChildScrollView(child:workspaceSummary())),
    if (tabs.notice != null) ConstrainedBox(constraints:BoxConstraints(maxHeight:constraints.maxHeight*.12),child:SingleChildScrollView(child:Padding(padding:const EdgeInsets.symmetric(horizontal:16),child:Text(tabs.notice!)))),
    if (tabs.active != null) ConstrainedBox(constraints:BoxConstraints(maxHeight:constraints.maxHeight*.12),child:SingleChildScrollView(child:Padding(padding:const EdgeInsets.symmetric(horizontal:16,vertical:4),child:Text('隐藏标签暂停观察与输入；连接可保留，返回后需主动恢复并等待原目标新画面。',style:Theme.of(context).textTheme.bodySmall)))),
    // The nested tab Navigator installs a modal barrier whose BlockSemantics
    // climbs to the nearest semantic boundary and would otherwise drop the tab
    // strip, workspace summary and notices from the semantics tree. Contain it.
    Expanded(child:Semantics(container:true,child:IndexedStack(index:tabs.activeIndex+1,children:[board(),for (final tab in tabs.tabs) KeyedSubtree(key:ValueKey('host-tab-view-${tab.id}'),child:tabNavigator(tab))]))),
  ])))));
}
