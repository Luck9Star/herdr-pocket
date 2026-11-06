import 'dart:convert';
import 'package:flutter/material.dart';
import 'host_catalog.dart';
import 'network_login.dart';
import 'network_profiles.dart';
import 'network_runtime.dart';

String networkNodeStateLabel(String? state) => switch (state) {
  'starting' => '正在启动 · 入网尚未确认',
  'needs-login' => '等待本设备授权',
  'needs-machine-auth' => '等待网络管理员批准此设备',
  'running' => 'Tailscale 已就绪 · SSH 与 herdr 仍需核验',
  'engine-started' => '引擎已启动 · 入网与 SSH 未验证',
  'closing' => '正在停止 · 清理尚未确认',
  'stopped' => '已停止',
  'unavailable' => '运行时不可用',
  _ => '状态未知 · 请刷新',
};

class TailscaleLoginDialog extends StatefulWidget {
  const TailscaleLoginDialog({super.key,required this.profile,required this.binding,
    required this.catalog,required this.runtime});
  final NetworkProfile profile;
  final NetworkNodeBinding binding;
  final HostCatalog catalog;
  final NativeNetworkRuntime runtime;
  @override
  State<TailscaleLoginDialog> createState() => _TailscaleLoginDialogState();
}

class _TailscaleLoginDialogState extends State<TailscaleLoginDialog> with WidgetsBindingObserver {
  late final String revision;
  late final NetworkLoginSession session;
  bool reviewed = false;
  bool current() => widget.catalog.ready && widget.catalog.revision == revision &&
    widget.catalog.networkProfiles.any((p) => jsonEncode(p.toJson()) == jsonEncode(widget.profile.toJson())) &&
    widget.binding.profileId == widget.profile.id && widget.binding.profileRevision == widget.profile.revision &&
    widget.binding.provider == 'tailscale' && widget.binding.networkName == tailscaleNetworkName(widget.profile);
  @override
  void initState() {
    super.initState(); revision = widget.catalog.revision; WidgetsBinding.instance.addObserver(this);
    session = NetworkLoginSession(binding:widget.binding,runtime:widget.runtime,stillCurrent:current,
      dispatchLogin:() => widget.catalog.guardedNetworkOperation(widget.profile,expectedRevision:revision,
        operation:() => widget.runtime.login(widget.binding)),
      dispatchOpen:(url,token) => widget.catalog.guardedNetworkOperation(widget.profile,expectedRevision:revision,
        operation:() => widget.runtime.openLogin(widget.binding,url,token)));
    session.addListener(changed); widget.catalog.addListener(catalogChanged);
    session.refresh();
  }
  void changed() { if (mounted) setState(() {}); }
  void catalogChanged() { session.checkCurrent(); if (mounted) setState(() { if (!current()) reviewed = false; }); }
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) { session.resume(); }
    else { reviewed = false; session.suspend(); }
  }
  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this); widget.catalog.removeListener(catalogChanged);
    session.removeListener(changed); session.dispose(); super.dispose();
  }
  Future<void> authorize() async {
    if (!reviewed || !session.canAuthorize) return;
    setState(() { reviewed = false; }); await session.authorize();
  }
  @override
  Widget build(BuildContext context) => AlertDialog(title:const Text('Tailscale · 本设备授权'),scrollable:true,
    content:SizedBox(width:420,child:Column(mainAxisSize:MainAxisSize.min,crossAxisAlignment:CrossAxisAlignment.stretch,children:[
      Text(widget.profile.label,style:Theme.of(context).textTheme.titleMedium),
      Text('控制服务器：${tailscaleEffectiveSettings(widget.profile)['controlUrl']}'),
      Text('本机名：${tailscaleEffectiveSettings(widget.profile)['hostname']}'),
      SelectableText('本机身份：${widget.binding.identityRef}'),
      Text('状态：${networkNodeStateLabel(session.state)}',key:const ValueKey('tailscale-login-state')),
      if (session.busy) const LinearProgressIndicator(),
      if (!current()) const Text('原配置已变化 · 请关闭后按最新资料审查。'),
      if (session.notice != null) Text(session.notice!,key:const ValueKey('tailscale-login-notice')),
      const Text('授权仅针对以上本机身份。登录链接不保存或导出；返回 App 后重新读取原节点，不会自动连接 SSH、发送输入或改变终端尺寸。'),
      if (session.state == 'needs-machine-auth') const Text('请在对应网络的管理端批准此设备，再刷新。无需再次登录。'),
      if (session.state == 'running') const Text('可关闭此页，回到主机列表，完成配对审查并主动连接看板。'),
      if (session.canAuthorize) ...[
        CheckboxListTile(key:const ValueKey('tailscale-login-review'),contentPadding:EdgeInsets.zero,
          value:reviewed,onChanged:(value) => setState(() { reviewed = value == true; }),
          title:const Text('已核对控制服务器与本机身份，明确请求授权链接')),
        FilledButton(key:const ValueKey('tailscale-login-authorize'),onPressed:reviewed ? authorize : null,
          child:const Text('请求本设备授权')),
      ],
      if (session.authUrl != null) ...[
        SelectableText(session.authUrl!,key:const ValueKey('tailscale-login-url')),
        FilledButton.icon(key:const ValueKey('tailscale-login-open'),onPressed:session.canOpen ? session.open : null,
          icon:const Icon(Icons.open_in_new),label:const Text('在系统浏览器打开授权')),
      ],
      const Text('关闭此页会停止状态轮询并清除链接，节点仍保留。取消入网请返回网络管理明确停止原节点。'),
    ])),actions:[
      TextButton(key:const ValueKey('tailscale-login-refresh'),onPressed:session.current && !session.busy ? session.refresh : null,
        child:const Text('重新读取原节点状态')),
      TextButton(key:const ValueKey('tailscale-login-close'),onPressed:() => Navigator.pop(context),child:const Text('关闭授权页')),
    ]);
}
