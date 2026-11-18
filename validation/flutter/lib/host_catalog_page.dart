import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'design_tokens.dart';
import 'direct_ssh_page.dart';
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
  const HostCatalogPage({super.key,required this.tokens,required this.offlineBuilder,this.catalog,this.keys,this.tabs,this.adapterFactory,this.overlayAdapterFactory});
  final DesignTokens tokens;
  final WidgetBuilder offlineBuilder;
  final HostCatalog? catalog;
  final DeviceKeys? keys;
  final HostTabs? tabs;
  final RemoteReadOnlyAdapter Function(HostProfile)? adapterFactory;
  @visibleForTesting final RemoteReadOnlyAdapter Function(HostProfile,SocketConnector)? overlayAdapterFactory;
  @override
  State<HostCatalogPage> createState() => _HostCatalogPageState();
}
class _HostCatalogPageState extends State<HostCatalogPage> with WidgetsBindingObserver {
  late final catalog = widget.catalog ?? HostCatalog();
  late final tabs = widget.tabs ?? HostTabs();
  late final summaries = HostTaskSummaries(catalog);
  String? notice;
  bool busy = false;
  bool sshClosedNotice = false;
  int destination = 0;
  bool collapsePending = false;
  bool workspaceWide = false;
  final hostSearch = TextEditingController();
  final expandedHostManagement = <String>{};
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
  void tabChanged() { if (mounted) setState(() { if (destination == 1 && tabs.active == null && tabs.tabs.isEmpty) destination = 0; }); }
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
    if (sshClosedNotice) setState(() => sshClosedNotice = false);
    if (profile != null && profile.hasIdentity) {
      if (profile.requiresNetworkBinding) { setState(() { notice = '请先通过主机的“选择／解除网络绑定”选择相同 provider 的本机网络，再新建视图；不会使用系统直连。'; }); return; }
      tabs.open(profile,networks:catalog.networkProfiles,adapter:widget.adapterFactory?.call(profile));
      if (tabs.active != null) setState(() => destination = 1); return; }
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
    if (tabs.active != null) setState(() => destination = 1);
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
      closeTabsAndWait:tabs.closeHostsAndWait,closeTabs:(ids) { for (final id in ids) { tabs.closeHost(id); } })));
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
  Widget statusBadge(HostProfile profile) {
    final report = summaries.forHost(profile.id);
    final pending = report?.current == true && report!.blockedCount > 0;
    final label = pending ? '待处理 ${report.blockedCount}' : report == null ? '状态未知'
      : !report.current ? '待核查' : report.unknownCount > 0 ? '状态未知' : '已同步';
    return Container(padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(color: widget.tokens.color(pending ? 'warningSoft' : 'cardSubtle'),
        borderRadius: BorderRadius.circular(20)),
      child: Text(label, style: Theme.of(context).textTheme.labelSmall?.copyWith(
        color: widget.tokens.color(pending ? 'warningText' : 'textSecondary'))));
  }
  Widget hostSummary(HostProfile profile,{bool compact=false}) {
    final value = summaries.forHost(profile.id);
    final distinct = <String,RemotePane>{};
    for (final pane in value?.blockedPanes ?? const <RemotePane>[]) {
      distinct.putIfAbsent(jsonEncode([pane.paneId,pane.terminalId]),() => pane);
    }
    if (!compact) {
      final time = value?.syncedAt.toLocal();
      String two(int n) => n.toString().padLeft(2,'0');
      final sync = time == null ? null : '${two(time.month)}-${two(time.day)} ${two(time.hour)}:${two(time.minute)}';
      final count = value == null ? null : value.paneCount == 0 ? '快照确认为空' : '受阻${value.unknownCount > 0 ? '至少' : ''} ${value.blockedCount} 个${value.unknownCount > 0 ? ' · ${value.unknownCount} 个状态未知' : ''} · 共 ${value.paneCount} 个窗格';
      return Column(key:ValueKey('host-task-summary-${profile.id}'),crossAxisAlignment:CrossAxisAlignment.stretch,children:[
        Text('会话 ${profile.target['session']}',style:Theme.of(context).textTheme.titleSmall),
        const SizedBox(height:4),
        Text(value == null ? '任务状态未知 · 尚无有效会话快照' : '${value.current ? '主机报告' : value.freshness == DashboardFreshness.unavailable ? '单次主机报告' : '上次主机报告'} · $count',
          style:Theme.of(context).textTheme.bodySmall?.copyWith(color:widget.tokens.color('textSecondary'))),
        if (sync != null) Tooltip(message:value!.detail,child:Text('同步 $sync${value.current ? '' : ' · 待核查'}',
          style:Theme.of(context).textTheme.bodySmall?.copyWith(color:widget.tokens.color('textSecondary')))),
        if (value != null && distinct.isNotEmpty) ...[
          for (final pane in distinct.values) Padding(padding:const EdgeInsets.only(top:4),child:Row(children:[
            Expanded(child:Text('${pane.label == null ? pane.paneId : '${pane.label} · ${pane.paneId}'}${pane.agent == null ? '' : ' / ${pane.agent}'}',
              style:Theme.of(context).textTheme.labelLarge)),
            Text(value.current ? '待处理' : '待核查',style:Theme.of(context).textTheme.labelSmall?.copyWith(
              color:widget.tokens.color(value.current ? 'warningText' : 'textSecondary'))),
          ])),
          ExpansionTile(key:ValueKey(blockedSummaryGroupKey(profile.id)),tilePadding:EdgeInsets.zero,dense:true,
            title:const Text('受阻窗格 · 核查原目标'),
            children:[Text(value.current ? '原因未提供 · 打开前审查连接' : value.freshness == DashboardFreshness.unavailable
              ? '持续更新不可用 · 打开前重新核查此目标' : '上次报告 · 点击后重新核查此目标'),
              Text(value.detail,style:Theme.of(context).textTheme.bodySmall),
              for (final pane in distinct.values)
              ListTile(key:ValueKey(blockedSummaryTargetKey(profile.id,pane)),
                title:Text(pane.label ?? '受阻窗格'),
                subtitle:Text('主机 ${profile.label} · 原会话 ${value.source.session}\npane ${pane.paneId} · terminal ${pane.terminalId}'),
                trailing:const Icon(Icons.chevron_right),
                onTap:busy || !catalog.ready || catalog.writing ? null : () => openBlocked(profile,value,pane))]),
        ],
      ]);
    }
    return Column(key:ValueKey('${compact ? 'workspace' : 'host'}-task-summary-${profile.id}'),crossAxisAlignment:CrossAxisAlignment.stretch,children:[
      Text(value?.label ?? '任务状态未知 · 尚无此主机的有效会话快照'),
      if (value != null) Text(compact ? value.detail : '最后同步 ${value.syncedAt.toLocal().toIso8601String()}',
        style: Theme.of(context).textTheme.bodySmall),
      if (value != null && distinct.isNotEmpty)
        ExpansionTile(key:ValueKey(blockedSummaryGroupKey(profile.id,compact:compact)),tilePadding:EdgeInsets.zero,
          title:Text(distinct.length == 1
            ? '受阻窗格 · ${distinct.values.first.label ?? distinct.values.first.paneId}${distinct.values.first.agent == null ? '' : ' / ${distinct.values.first.agent}'}'
            : '受阻窗格 · ${value.blockedCount} 个'),
          subtitle:Text(value.current ? '当前受阻 · 原因未提供\n打开前仍需审查连接及原目标' : value.freshness == DashboardFreshness.unavailable
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
  bool get ordinaryCatalogStatus => catalog.ready &&
    (catalog.status.startsWith('已恢复 ') || catalog.status == '本机资料已保存 · 不代表主机授权或当前在线');
  bool get largeMobileText => MediaQuery.textScalerOf(context).scale(1) > 1;
  bool get mobileEmptyBoard => MediaQuery.sizeOf(context).width < 960 && catalog.ready &&
    catalog.profiles.isEmpty && catalog.pendingCreation == null && tabs.tabs.isEmpty && notice == null &&
    (catalog.status == '没有本机主机资料 · 请明确新增配对' || ordinaryCatalogStatus);

  void openDirectSsh() {
    tabs.select(null);
    if (sshClosedNotice) setState(() => sshClosedNotice = false);
    Navigator.push<void>(context, MaterialPageRoute(builder: (_) => DirectSshPage(tokens: widget.tokens,
      onReturnAfterDisconnect: () { if (mounted) setState(() => sshClosedNotice = true); })));
  }

  Future<void> chooseConnection() async {
    if (sshClosedNotice) setState(() => sshClosedNotice = false);
    final choice = await Navigator.push<String>(context, MaterialPageRoute(builder: (context) {
      final margin = MediaQuery.sizeOf(context).width < 360 ? 16.0 : 24.0;
      final large = MediaQuery.textScalerOf(context).scale(1) > 1;
      Widget option(String key, String title, String detail, IconData icon, bool primary, String value) =>
        ConstrainedBox(constraints: const BoxConstraints(minHeight: 100), child: SizedBox(height: large ? null : 100, child: Material(
          color: widget.tokens.color('card'),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(cardRadius),
            side: BorderSide(color: widget.tokens.color(primary ? 'brandBorder' : 'border'))),
          child: InkWell(key: ValueKey(key), borderRadius: BorderRadius.circular(cardRadius),
            onTap: () => Navigator.pop(context, value), child: Padding(
              padding: const EdgeInsets.all(14), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [Container(width: 40, height: 40,
                  decoration: BoxDecoration(color: widget.tokens.color(primary ? 'brandSoft' : 'cardSubtle'), borderRadius: BorderRadius.circular(10)),
                  child: Icon(icon, color: widget.tokens.color(primary ? 'brand' : 'textSecondary'), size: 24)),
                  const SizedBox(width: 12), Expanded(child: Text(title, maxLines: large ? null : 1, overflow: large ? TextOverflow.visible : TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold))),
                  Icon(Icons.chevron_right, color: widget.tokens.color('textSecondary'))]),
                const SizedBox(height: 8), if (large) Text(detail, style: TextStyle(fontSize: 13, letterSpacing: 0, color: widget.tokens.color('textSecondary')))
                else FittedBox(fit: BoxFit.scaleDown, alignment: Alignment.centerLeft, child: Text(detail,
                  style: TextStyle(fontSize: 13, letterSpacing: 0, color: widget.tokens.color('textSecondary')))),
              ]))))));
      return Scaffold(body: SafeArea(child: Column(children: [
        Container(key: const ValueKey('choose-header'), height: large ? 72 : 56,
          decoration: BoxDecoration(border: Border(bottom: BorderSide(color: widget.tokens.color('border')))),
          child: Row(children: [SizedBox(width: margin - 8), SizedBox(width: 44, height: 44,
            child: IconButton(key: const ValueKey('choose-back'), padding: EdgeInsets.zero, tooltip: '返回',
              onPressed: () => Navigator.pop(context), icon: const Icon(Icons.arrow_back))),
            const SizedBox(width: 8), const Text('添加主机', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold))])),
        Expanded(child: ListView(padding: EdgeInsets.fromLTRB(margin, 24, margin, 24), children: [
          SizedBox(height: large ? null : 28, child: Transform.translate(offset: Offset(0, large ? 0 : -4),
            child: const Text('选择连接方式', style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold, letterSpacing: 0)))),
          const SizedBox(height: 16),
          option('choose-ssh', '普通 SSH 终端', '使用服务器密码或已有私钥打开远程 Shell。', Icons.terminal, true, 'ssh'),
          const SizedBox(height: 12),
          option('choose-herdr', 'herdr 配对 / 手动连接', '接入 herdr 工作台，查看会话和任务。', Icons.web_asset_outlined, false, 'herdr'),
        ])),
      ])));
    }));
    if (!mounted) return;
    if (choice == 'ssh') openDirectSsh();
    if (choice == 'herdr') await open();
  }

  double get cardRadius => ((widget.tokens.data['radii'] as Map)['card'] as num).toDouble();

  Widget emptyMobileNavigation() {
    final entries = [(Icons.dashboard_outlined, '看板'), (Icons.terminal, '终端'),
      (Icons.language, '网络'), (Icons.settings_outlined, '设置')];
    return Material(color: widget.tokens.color('card'), child: SafeArea(top: false, child: Container(
      key: const ValueKey('home-tabs'), height: 56,
      decoration: BoxDecoration(border: Border(top: BorderSide(color: widget.tokens.color('border')))),
      child: Row(children: [for (var i = 0; i < entries.length; i++) Expanded(child: InkWell(
        key: i == 2 ? const ValueKey('hosts-networks') : ValueKey('home-tab-$i'),
        onTap: () { setState(() { destination = i; sshClosedNotice = false; }); if (i != 1) tabs.select(null); },
        child: Semantics(label: entries[i].$2, button: true, selected: i == 0, child: Stack(alignment: Alignment.topCenter, children: [
          Positioned(top: 4, child: Container(width: 40, height: 28,
            decoration: BoxDecoration(color: i == 0 ? widget.tokens.color('brandSoft') : Colors.transparent,
              borderRadius: BorderRadius.circular(10)),
            child: Icon(entries[i].$1, size: 24, color: widget.tokens.color(i == 0 ? 'brand' : 'textSecondary')))),
          Positioned(top: 36, child: Text(entries[i].$2, textScaler: TextScaler.noScaling,
            style: TextStyle(fontSize: 12, height: 1, color: widget.tokens.color(i == 0 ? 'brand' : 'textSecondary')))),
        ]))))]))));
  }

  Widget sshDisconnectedNotice() => Container(key: const ValueKey('home-ssh-closed'),
    constraints: const BoxConstraints(minHeight: 44), alignment: Alignment.centerLeft,
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
    decoration: BoxDecoration(color: widget.tokens.color('brandSoft'), borderRadius: BorderRadius.circular(10),
      border: Border.all(color: widget.tokens.color('brandBorder'))),
    child: Semantics(liveRegion: true, child: Text('普通 SSH 已断开',
      style: TextStyle(color: widget.tokens.color('brand'), fontWeight: FontWeight.bold))));
  Widget emptyMobileBoard() {
    final margin = MediaQuery.sizeOf(context).width < 360 ? 16.0 : 24.0;
    final large = largeMobileText;
    final canAdd = !busy && !catalog.writing && catalog.profiles.length < maxHostProfiles;
    return ListView(key: const ValueKey('host-catalog-list'), padding: EdgeInsets.fromLTRB(margin, 16, margin, 16), children: [
      SizedBox(key: const ValueKey('home-brand'), height: large ? null : 44, child: Row(children: [
        Container(width: 34, height: 34, alignment: Alignment.center,
          decoration: BoxDecoration(color: widget.tokens.color('brand'), borderRadius: BorderRadius.circular(10)),
          child: Text('HP', style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: widget.tokens.color('textInverse')))),
        const SizedBox(width: 10), Expanded(child: Text('Herdr Pocket', maxLines: large ? null : 1,
          overflow: large ? TextOverflow.visible : TextOverflow.ellipsis,
          style: const TextStyle(fontSize: 22, fontWeight: FontWeight.bold))),
      ])),
      if (sshClosedNotice) ...[
        const SizedBox(height: 12), sshDisconnectedNotice(), const SizedBox(height: 16),
      ] else const SizedBox(height: 28),
      Container(key: const ValueKey('home-empty-card'), height: large ? null : 268,
        constraints: const BoxConstraints(minHeight: 268), padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(color: widget.tokens.color('card'), borderRadius: BorderRadius.circular(cardRadius),
          border: Border.all(color: widget.tokens.color('border'))),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Align(alignment: Alignment.centerLeft, child: Container(width: 44, height: 44,
            decoration: BoxDecoration(color: widget.tokens.color('brandSoft'), borderRadius: BorderRadius.circular(10)),
            child: Icon(Icons.terminal, color: widget.tokens.color('brand')))),
          const SizedBox(height: 8), const Text('还没有主机', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, height: 1.4)),
          const SizedBox(height: 8), Text('添加主机后，在这里查看会话和任务状态。', maxLines: large ? null : 1,
            overflow: large ? TextOverflow.visible : TextOverflow.ellipsis,
            style: TextStyle(fontSize: 13, letterSpacing: 0, color: widget.tokens.color('textSecondary'), height: 1.5)),
          if (large) const SizedBox(height: 24) else const Spacer(), SizedBox(height: large ? null : 48, child: FilledButton(key: const ValueKey('hosts-add'),
            onPressed: canAdd ? chooseConnection : null, child: const Text('添加主机'))),
          const SizedBox(height: 12), SizedBox(height: large ? null : 48, child: OutlinedButton(key: const ValueKey('hosts-direct-ssh'),
            onPressed: openDirectSsh, style: OutlinedButton.styleFrom(foregroundColor: widget.tokens.color('textPrimary'),
              side: BorderSide(color: widget.tokens.color('borderStrong')),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10))), child: const Text('普通 SSH 终端'))),
        ])),
    ]);
  }
  Widget board() {
    if (mobileEmptyBoard) return emptyMobileBoard();
    final ordered = orderedHosts;
    // Derived only from existing reports; filtering never opens or retires a lease.
    final categories = {
      for (final host in ordered) host.id: searchTargetCategory(host),
    };
    final pendingIds = {
      for (final entry in categories.entries)
        if (entry.value == HostTaskFilter.current) entry.key,
    };
    final historicalIds = {
      for (final entry in categories.entries)
        if (entry.value == HostTaskFilter.history) entry.key,
    };
    final shown = searchHostCatalog(
      ordered,
      query: hostSearch.text,
      filter: taskFilter,
      fields: searchFields,
      current: (host) => pendingIds.contains(host.id),
      history: (host) => historicalIds.contains(host.id),
    );
    final ordinaryStatus = ordinaryCatalogStatus;
    return ListView(
      key: const ValueKey('host-catalog-list'),
      padding: const EdgeInsets.all(16),
      children: [
        Row(
          children: [
            Container(
              width: 38,
              height: 38,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: widget.tokens.color('brand'),
                borderRadius: BorderRadius.circular(11),
              ),
              child: Text(
                'HP',
                style: TextStyle(
                  color: widget.tokens.color('textInverse'),
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Herdr Pocket',
                    style: Theme.of(context).textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  Text(
                    '${ordered.length} 台已保存主机 · ${tabs.tabs.length} 个本地视图',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ],
              ),
            ),
            FilledButton.icon(
              key: const ValueKey('hosts-add'),
              onPressed:
                  catalog.ready &&
                      !busy &&
                      !catalog.writing &&
                      catalog.profiles.length < maxHostProfiles &&
                      catalog.pendingCreation == null
                  ? () => open()
                  : null,
              icon: const Icon(Icons.add, size: 18),
              label: const Text('配对添加'),
            ),
          ],
        ),
        Align(alignment: Alignment.centerRight, child: TextButton.icon(
          key: const ValueKey('hosts-direct-ssh'), onPressed: openDirectSsh,
          icon: const Icon(Icons.terminal), label: const Text('普通 SSH'))),
        const SizedBox(height: 4),
        if (sshClosedNotice) ...[sshDisconnectedNotice(), const SizedBox(height: 12)],
        if (!ordinaryStatus) Text(
          catalog.status,
          key: const ValueKey('hosts-status'),
          style: Theme.of(context).textTheme.bodySmall,
        ),
        if (notice != null)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 12),
            child: Text(notice!),
          ),
        if (catalog.ready && ordered.isEmpty)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 24),
            child: Text('暂无已保存主机 · 使用“配对添加”开始'),
          ),
        if (catalog.ready && catalog.profiles.length >= maxHostProfiles)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 12),
            child: Text(
              '本机主机资料已达 $maxHostProfiles 个上限 · 上方新增按钮已禁用；需先删除或整理既有资料',
              key: const ValueKey('hosts-add-limit-notice'),
            ),
          ),
        if (catalog.pendingCreation != null) ...[
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 12),
            child: Text(
              '上次设备身份创建未完成或结果未知 · 已禁止再次创建，不会自动重放。已返回句柄可明确删除；无句柄时需人工核验本机身份，不能按空记录处理。',
            ),
          ),
          if ((catalog.pendingCreation!['handle'] as String).isNotEmpty)
            TextButton(
              key: const ValueKey('hosts-delete-pending'),
              onPressed: busy || !catalog.ready
                  ? null
                  : () => action(() async {
                      final handle =
                          catalog.pendingCreation!['handle'] as String;
                      await (widget.keys ?? NativeDeviceKeys()).delete(handle);
                      await catalog.clearDeletedCreation(handle);
                    }),
              child: const Text('明确删除未完成的本机身份（不撤销主机）'),
            ),
        ],
        if (catalog.ready && ordered.isNotEmpty) ...[
          const SizedBox(height: 12),
          TextField(
            key: const ValueKey('hosts-search'),
            controller: hostSearch,
            // Read the raw text only. Do not rewrite case, selection or IME composing.
            onChanged: (_) => setState(() {}),
            decoration: InputDecoration(
              labelText: '查找主机或会话',
              prefixIcon: const Icon(Icons.search),
              suffixIcon: hostSearch.text.isEmpty
                  ? null
                  : IconButton(
                      key: const ValueKey('hosts-search-clear'),
                      tooltip: '清除搜索',
                      onPressed: () => setState(hostSearch.clear),
                      icon: const Icon(Icons.clear),
                    ),
            ),
          ),
          const SizedBox(height: 8),
          Wrap(
            key: const ValueKey('hosts-task-filter'),
            spacing:8,
            children: [
              for (final item in <(HostTaskFilter, String)>[
                (HostTaskFilter.all, '全部 ${ordered.length}'),
                (HostTaskFilter.current, '待处理 ${pendingIds.length}'),
                (HostTaskFilter.history, '历史待核查 ${historicalIds.length}'),
              ]) ConstrainedBox(constraints:const BoxConstraints(minHeight:48),
                child: ChoiceChip(key: ValueKey('hosts-filter-${item.$1.name}'),
                  label: Text(item.$2), labelPadding:const EdgeInsets.symmetric(horizontal:2), selected: taskFilter == item.$1,
                  onSelected: (_) => setState(() => taskFilter = item.$1))),
            ],
          ),
          if (taskFilter != HostTaskFilter.all || hostSearch.text.isNotEmpty) Text(
            '显示 ${shown.length} / ${ordered.length} 台主机',
            key: const ValueKey('hosts-filter-count'),
          ),
          if (taskFilter == HostTaskFilter.current)
            const Text('仅列出当前报告中可定位的受阻目标；历史报告与状态未知不计入。'),
          if (taskFilter == HostTaskFilter.history)
            const Text('上次明确受阻的目标，当前状态待核查；打开后仍需重新审查连接与原目标。'),
          if (shown.isEmpty) ...[
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 12),
              child: Text('没有匹配的主机', key: ValueKey('hosts-search-empty')),
            ),
            TextButton(
              key: const ValueKey('hosts-filters-reset'),
              onPressed: () => setState(() {
                hostSearch.clear();
                taskFilter = HostTaskFilter.all;
              }),
              child: const Text('清除全部筛选'),
            ),
          ],
        ],
        for (final profile in shown)
          Card(
            key: ValueKey('host-card-${profile.id}'),
            color: widget.tokens.color('card'),
            elevation: 0,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14), side: BorderSide(color: widget.tokens.color('border'))),
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(children: [
                    Expanded(child: Text(profile.label, style: Theme.of(context).textTheme.titleMedium)),
                    statusBadge(profile),
                  ]),
                  Text(networkDescription(profile), style: Theme.of(context).textTheme.bodySmall),
                  const SizedBox(height: 6),
                  Material(color: widget.tokens.color('cardSubtle'), borderRadius: BorderRadius.circular(10),
                    child: Padding(padding: const EdgeInsets.all(8), child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                        hostSummary(profile),
                      ]))),
                  if (!profile.hasIdentity) const Text('导入未配对 · 无本机身份'),
                  Row(children: [
                    Expanded(child:FilledButton(
                      key: ValueKey('host-open-${profile.id}'),
                      style:FilledButton.styleFrom(minimumSize:const Size(0,44)),
                      onPressed: !busy && catalog.ready && profile.enabled ? () => open(profile) : null,
                      child: Text(profile.hasIdentity ? '观察会话 · 审查' : '审查目标并配对'),
                    )),
                    const SizedBox(width:8),
                    Semantics(expanded:expandedHostManagement.contains(profile.id),child:TextButton.icon(key:ValueKey('host-management-${profile.id}'),
                      style:TextButton.styleFrom(minimumSize:const Size(0,44)),
                      onPressed:() => setState(() {
                        if (!expandedHostManagement.add(profile.id)) expandedHostManagement.remove(profile.id);
                      }),
                      icon:Icon(expandedHostManagement.contains(profile.id) ? Icons.expand_less : Icons.expand_more),
                      label:const Text('管理'))),
                  ]),
                  if (expandedHostManagement.contains(profile.id)) Column(
                    crossAxisAlignment:CrossAxisAlignment.stretch,
                    children: [
                      Text(
                        '资料 provider：${hostProviderLabel(profile.provider)} · 入网状态未知\n${profile.target['username']}@${profile.target['host']}:${profile.target['port']}\n会话 ${profile.target['session']} · ${profile.retired
                            ? '已替换停用，保留原身份待撤销'
                            : profile.enabled
                            ? '本机启用'
                            : '本机停用'}\n${profile.hasIdentity ? profile.restore(catalog.clock()).state : '导入未配对 · 无本机身份'} · 在线与主机授权需重新核验',
                      ),
                      if (profile.retired && profile.hasIdentity)
                        ExpansionTile(
                          title: const Text('原配对公开请求（供主机核验撤销）'),
                          children: [
                            SelectableText(
                              profile.restore(catalog.clock()).wire,
                            ),
                          ],
                        ),
                      const SizedBox(height: 8),
                      Wrap(
                        spacing: 8,
                        children: [
                          TextButton(
                            key: ValueKey('host-rename-${profile.id}'),
                            onPressed: busy || !catalog.ready
                                ? null
                                : () => rename(profile),
                            child: const Text('重命名'),
                          ),
                          TextButton(
                            key: ValueKey('host-network-${profile.id}'),
                            onPressed: busy || !catalog.ready || profile.retired
                                ? null
                                : () => configureNetwork(profile),
                            child: const Text('选择／解除网络绑定'),
                          ),
                          TextButton(
                            key: ValueKey('host-provider-${profile.id}'),
                            onPressed:
                                busy ||
                                    !catalog.ready ||
                                    profile.requiresNetworkBinding
                                ? null
                                : () => configureProvider(profile),
                            child: const Text('旧 provider 标签（仅资料）'),
                          ),
                          TextButton(
                            key: ValueKey('host-disable-${profile.id}'),
                            onPressed: busy || !catalog.ready || profile.retired
                                ? null
                                : () => action(
                                    () => catalog.update(
                                      profile.change(
                                        enabled: !profile.enabled,
                                        now: catalog.clock(),
                                      ),
                                      beforeCommit: () =>
                                          tabs.closeHost(profile.id),
                                    ),
                                  ),
                            child: Text(
                              profile.enabled ? '本机停用（不撤销主机）' : '本机启用（仍需审查）',
                            ),
                          ),
                          TextButton(
                            key: ValueKey('host-delete-${profile.id}'),
                            onPressed: busy || !catalog.ready
                                ? null
                                : () => remove(profile),
                            child: const Text('删除本机资料与身份'),
                          ),
                        ],
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        const SizedBox(height: 12),
        if (ordered.isNotEmpty) Text(
          '资料不会自动连接、替换主机公钥或重放未知操作。',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        if (ordinaryStatus) Text(catalog.status,key:const ValueKey('hosts-status'),
          style:Theme.of(context).textTheme.bodySmall),
      ],
    );
  }

  Widget settings() => ListView(
    padding: const EdgeInsets.all(16),
    children: [
      Text('设置', style: Theme.of(context).textTheme.headlineSmall),
      const SizedBox(height: 12),
      ListTile(
        key: const ValueKey('hosts-terminal-preferences'),
        leading: const Icon(Icons.text_fields),
        title: const Text('终端字号'),
        subtitle: Text('${catalog.terminalFontSize} px · 仅本机显示'),
        onTap: catalog.ready && !busy && !catalog.writing
            ? terminalPreferences
            : null,
      ),
      ListTile(
        key: const ValueKey('hosts-transfer'),
        leading: const Icon(Icons.import_export),
        title: const Text('加密导出／导入公开主机资料'),
        onTap:
            catalog.ready &&
                !busy &&
                !catalog.writing &&
                catalog.pendingCreation == null
            ? transfer
            : null,
      ),
      ListTile(
        key: const ValueKey('hosts-reload'),
        leading: const Icon(Icons.refresh),
        title: const Text('重新读取本机资料'),
        onTap: busy || catalog.writing ? null : catalog.load,
      ),
      ListTile(
        key: const ValueKey('hosts-offline'),
        leading: const Icon(Icons.science_outlined),
        title: const Text('离线终端实验室'),
        onTap: () {
          tabs.select(null);
          Navigator.push<void>(
            context,
            MaterialPageRoute(builder: widget.offlineBuilder),
          );
        },
      ),
    ],
  );
  Widget terminalList() => ListView(
    padding: const EdgeInsets.all(16),
    children: [
      Text('终端', style: Theme.of(context).textTheme.headlineSmall),
      if (tabs.tabs.isEmpty)
        const Padding(
          padding: EdgeInsets.symmetric(vertical: 24),
          child: Text('暂无打开的本地视图 · 请先在看板选择主机'),
        ),
      for (final tab in tabs.tabs)
        ValueListenableBuilder<HostTabView>(
          valueListenable: tab.view,
          builder: (context, view, _) => ListTile(
            key: ValueKey('terminal-list-${tab.id}'),
            leading: const Icon(Icons.terminal),
            title: Text(tab.label),
            subtitle: Text('${view.target} · ${view.label}${tab.visible.value ? '' : '\n${view.frameLabel}'}'),
            trailing: IconButton(
              tooltip: '关闭本地标签，不终止远端任务',
              onPressed: () => tabs.close(tab.id),
              icon: const Icon(Icons.close),
            ),
            onTap: () => tabs.select(tab.id),
          ),
        ),
    ],
  );
  Widget tabNavigator(HostTab tab) => ValueListenableBuilder<bool>(valueListenable:tab.visible,
    builder:(context,visible,child) => IgnorePointer(ignoring:!visible,child:ExcludeSemantics(excluding:!visible,
      child:FocusScope(canRequestFocus:visible,child:child!))),
    child:Navigator(key:tab.navigator,onGenerateRoute:(settings) => MaterialPageRoute<void>(settings:settings,
      builder:(_) => PairingPage(tokens:widget.tokens,keys:widget.keys,catalog:catalog,profileId:tab.hostId,
        registerTransport:tab.registerTransport,
        overlayAdapterFactory:widget.overlayAdapterFactory == null ? null : (connector) => widget.overlayAdapterFactory!(catalog.profiles.singleWhere((p) => p.id == tab.hostId),connector),
        adapter:tab.adapter,visibility:tab.visible,inputEligible:tab.inputEligible,onViewState:tab.report,requestedTarget:tab.requestedTarget,
        summaryLeaseFactory:(profile) {
          tab.summaryLease?.close();
          final lease = summaries.open(profile,visible:() => tabs.find(tab.id) == tab && tab.visible.value);
          tab.summaryLease = lease; return lease;
        },
        onOpenPane:(pane) => openPane(tab,pane)))));
  Widget tabBar() => SingleChildScrollView(
    scrollDirection: Axis.horizontal,
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
    child: Row(
      children: [
        Padding(
          padding: const EdgeInsets.only(right: 8),
          child: ChoiceChip(
            key: const ValueKey('hosts-board-tab'),
            label: const Text('主机列表'),
            selected: tabs.activeId == null,
            onSelected: (_) { tabs.select(null); setState(() => destination = 0); },
          ),
        ),
        for (final tab in tabs.tabs)
          Padding(
            padding: const EdgeInsets.only(right: 8),
            child: Container(
              decoration: BoxDecoration(
                border: Border.all(
                  color: tabs.activeId == tab.id
                      ? Theme.of(context).colorScheme.primary
                      : Theme.of(context).dividerColor,
                ),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  ValueListenableBuilder<HostTabView>(
                    valueListenable: tab.view,
                    builder: (context, view, _) => MergeSemantics(
                      child: Semantics(
                        selected: tabs.activeId == tab.id,
                        child: TextButton(
                          key: ValueKey('host-tab-${tab.id}'),
                          onPressed: () { tabs.select(tab.id); setState(() => destination = 1); },
                          child: ConstrainedBox(
                            constraints: const BoxConstraints(maxWidth: 260),
                            child: Text(
                              '${tab.label} · ${tab.networkLabel}\n${view.target} · ${view.label}${tab.visible.value ? '' : '\n${view.frameLabel}'}',
                              maxLines: 3,
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
                  if (MediaQuery.sizeOf(context).width >= 960 && tabs.active != null && tabs.activeId != tab.id)
                    IconButton(key: ValueKey('host-split-${tab.id}'), tooltip: '并排观察此标签',
                      onPressed: () => tabs.splitWith(tab.id), icon: const Icon(Icons.vertical_split)),
                  IconButton(
                    key: ValueKey('host-tab-close-${tab.id}'),
                    tooltip: '关闭本地标签，不终止远端任务',
                    onPressed: () => tabs.close(tab.id),
                    icon: const Icon(Icons.close, size: 18),
                  ),
                ],
              ),
            ),
          ),
      ],
    ),
  );
  Widget desktopSidebar() => Material(color: widget.tokens.color('card'), child: Container(
    width: 224,
    decoration: BoxDecoration(border: Border(right: BorderSide(color: widget.tokens.color('border')))),
    child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      const Padding(padding: EdgeInsets.all(16), child: Text('Herdr Pocket', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold))),
      TextButton.icon(key: const ValueKey('hosts-board-tab'),
        onPressed: () { tabs.select(null); setState(() => destination = 0); },
        icon: const Icon(Icons.dashboard_outlined), label: const Text('主机看板')),
      const Padding(padding: EdgeInsets.fromLTRB(16, 12, 16, 4), child: Text('主机与已开标签')),
      Expanded(child: ListView(children: [
        for (final profile in orderedHosts)
          ExpansionTile(key: ValueKey('sidebar-host-${profile.id}'), initiallyExpanded: true,
            title: Text(profile.label, overflow: TextOverflow.ellipsis),
            subtitle: Text(networkDescription(profile), maxLines: 1, overflow: TextOverflow.ellipsis),
            children: [
              ListTile(dense: true, leading: const Icon(Icons.add), title: const Text('新建观察视图'),
                onTap: profile.enabled && !busy ? () => open(profile) : null),
              for (final tab in tabs.forHost(profile.id))
                ValueListenableBuilder<HostTabView>(valueListenable: tab.view, builder: (context, view, _) =>
                  ListTile(key: ValueKey('host-tab-${tab.id}'), dense: true,
                    selected: tabs.activeId == tab.id, selectedTileColor: widget.tokens.color('brandSoft'),
                    title: Text(view.target, maxLines: 1, overflow: TextOverflow.ellipsis),
                    subtitle: Text('${view.label}${tab.visible.value ? '' : '\n${view.frameLabel}'}'),
                    onTap: () { tabs.select(tab.id); setState(() => destination = 1); },
                    trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                      if (tabs.active != null && tabs.activeId != tab.id)
                        IconButton(key: ValueKey('host-split-${tab.id}'), tooltip: '并排观察此标签',
                          onPressed: () => tabs.splitWith(tab.id), icon: const Icon(Icons.vertical_split)),
                      IconButton(key: ValueKey('host-tab-close-${tab.id}'), tooltip: '关闭本地标签，不终止远端任务',
                        onPressed: () => tabs.close(tab.id), icon: const Icon(Icons.close)),
                    ]))),
            ]),
      ])),
      ListTile(key: const ValueKey('hosts-networks'), leading: const Icon(Icons.language), title: const Text('网络'),
        selected: destination == 2, onTap: () { tabs.select(null); setState(() => destination = 2); }),
      ListTile(leading: const Icon(Icons.settings_outlined), title: const Text('设置'),
        selected: destination == 3, onTap: () { tabs.select(null); setState(() => destination = 3); }),
    ])));
  @override
  Widget build(BuildContext context) => PopScope(
    canPop: tabs.activeId == null,
    onPopInvokedWithResult: (didPop, result) {
      if (didPop) return;
      final navigator = tabs.active?.navigator.currentState;
      if (navigator?.canPop() == true) {
        unawaited(navigator!.maybePop());
      } else {
        tabs.select(null);
      }
    },
    child: Scaffold(
      bottomNavigationBar: MediaQuery.sizeOf(context).width < 960 ?
        (mobileEmptyBoard && destination == 0 && !largeMobileText ? emptyMobileNavigation() : NavigationBar(
        backgroundColor: widget.tokens.color('card'),
        indicatorColor: widget.tokens.color('brandSoft'),
        selectedIndex: destination,
        onDestinationSelected: (index) {
          setState(() {
            destination = index;
            sshClosedNotice = false;
          });
          if (index != 1) tabs.select(null);
        },
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.dashboard_outlined),
            label: '看板',
          ),
          NavigationDestination(icon: Icon(Icons.terminal), label: '终端'),
          NavigationDestination(key: ValueKey('hosts-networks'), icon: Icon(Icons.language), label: '网络'),
          NavigationDestination(
            icon: Icon(Icons.settings_outlined),
            label: '设置',
          ),
        ],
      )) : null,
      body: SafeArea(
        child: Row(children: [
          if (MediaQuery.sizeOf(context).width >= 960) desktopSidebar(),
          Expanded(child: LayoutBuilder(
          builder: (context, constraints) => Column(
            children: [
              if (MediaQuery.sizeOf(context).width < 960 && tabs.tabs.isNotEmpty && (destination == 0 || destination == 1))
                ConstrainedBox(
                  constraints: BoxConstraints(
                    maxHeight: constraints.maxHeight * .18,
                  ),
                  child: SingleChildScrollView(child: tabBar()),
                ),
              if (tabs.active != null && MediaQuery.sizeOf(context).width < 960)
                ConstrainedBox(
                  constraints: BoxConstraints(
                    maxHeight: constraints.maxHeight * .28,
                  ),
                  child: SingleChildScrollView(child: workspaceSummary()),
                ),
              if (tabs.notice != null)
                ConstrainedBox(
                  constraints: BoxConstraints(
                    maxHeight: constraints.maxHeight * .12,
                  ),
                  child: SingleChildScrollView(
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 16),
                      child: Text(tabs.notice!),
                    ),
                  ),
                ),
              if (tabs.active != null)
                ConstrainedBox(
                  constraints: BoxConstraints(
                    maxHeight: constraints.maxHeight * .12,
                  ),
                  child: SingleChildScrollView(
                    child: Padding(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 16,
                        vertical: 4,
                      ),
                      child: Text(
                        '隐藏标签暂停观察与输入；连接可保留，返回后需主动恢复并等待原目标新画面。',
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                    ),
                  ),
                ),
              // The nested tab Navigator installs a modal barrier whose BlockSemantics
              // climbs to the nearest semantic boundary and would otherwise drop the tab
              // strip, workspace summary and notices from the semantics tree. Contain it.
              Expanded(child: LayoutBuilder(builder: (context, workspace) {
                final wide = workspace.maxWidth >= 960;
                workspaceWide = wide;
                if (!wide && tabs.splitId != null && !collapsePending) {
                  collapsePending = true;
                  WidgetsBinding.instance.addPostFrameCallback((_) {
                    collapsePending = false;
                    if (mounted && !workspaceWide) tabs.closeSplit();
                  });
                }
                final split = wide && tabs.active != null && tabs.splitId != null;
                final showingTab = destination == 1 && tabs.active != null;
                return Semantics(container: true, child: Stack(children: [
                  Positioned.fill(child: Offstage(offstage: showingTab, child: IndexedStack(
                    index: destination, children: [board(), terminalList(),
                      NetworkProfilesPage(catalog: catalog, closeTabsAndWait:tabs.closeHostsAndWait,closeTabs: (ids) {
                        for (final id in ids) { tabs.closeHost(id); }
                      }), settings()]))),
                  for (final tab in tabs.tabs)
                    Positioned(key: ValueKey('host-tab-view-${tab.id}'), top: 0, bottom: 0,
                      left: split && tab.id != tabs.splitLeftId ? workspace.maxWidth / 2 : 0,
                      width: split ? workspace.maxWidth / 2 : workspace.maxWidth,
                      child: Offstage(offstage: !showingTab || (tab.id != tabs.activeId && (!split || tab.id != tabs.splitId)),
                        child: DecoratedBox(key: ValueKey('workspace-frame-${tab.id}'), decoration: BoxDecoration(border: Border.all(
                          color: split && tab.id == tabs.activeId ? widget.tokens.color('brand') : Colors.transparent,
                          width: split ? 2 : 0)), child: Column(children: [
                          SizedBox(height: split ? 44 : 0, child: split ? Row(children: [
                            Expanded(child: TextButton(key: ValueKey('workspace-focus-${tab.id}'),
                              onPressed: () => tabs.select(tab.id),
                              child: Text('${tab.label} · ${tab.id == tabs.activeId ? '输入焦点' : '观察'}', overflow: TextOverflow.ellipsis))),
                            if (tab.id == tabs.splitId) IconButton(key: const ValueKey('workspace-close-split'),
                              tooltip: '收起并排观察', onPressed: tabs.closeSplit, icon: const Icon(Icons.close)),
                          ]) : null),
                          Expanded(child: Semantics(container: true, child: tabNavigator(tab))),
                        ])))),
                ]));
              })),
            ],
          ),
        )),
        ]),
      ),
    ),
  );
}
