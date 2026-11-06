import 'package:flutter/material.dart';
import 'host_catalog.dart';
import 'network_profiles.dart';
import 'network_identity.dart';
import 'network_identity_dialog.dart';
import 'remote_adapter.dart';

class NetworkProfilesPage extends StatefulWidget {
  const NetworkProfilesPage({super.key,required this.catalog,required this.closeTabs,this.identityStore});
  final HostCatalog catalog;
  final void Function(Set<String>) closeTabs;
  final NetworkIdentityStore? identityStore;
  @override
  State<NetworkProfilesPage> createState() => _NetworkProfilesPageState();
}
class _NetworkProfilesPageState extends State<NetworkProfilesPage> {
  HostCatalog get catalog => widget.catalog;
  late final identities = widget.identityStore ?? NativeNetworkIdentityStore();
  bool busy = false;
  String? notice;
  bool get available => catalog.ready && !catalog.writing && !busy;
  @override
  void initState() { super.initState(); catalog.addListener(changed); }
  void changed() { if (mounted) setState(() {}); }
  @override
  void dispose() { catalog.removeListener(changed); super.dispose(); }
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
    if (!available) return;
    final captured = catalog.revision;
    final result = await showDialog<NetworkProfile>(context:context,builder:(_) => _NetworkEditor(profile:profile));
    if (result == null || !mounted) return;
    if (profile == null) { await action(() => catalog.addNetwork(result)); return; }
    final affected = catalog.networkImpact(profile.id);
    if (!await confirm(profile,'编辑',affected) || !mounted) return;
    await action(() => catalog.updateNetwork(result,expectedRevision:captured,
      beforeCommit:() => widget.closeTabs(affected.map((p) => p.id).toSet())));
  }
  Future<void> toggle(NetworkProfile profile) async {
    final captured = catalog.revision,affected = catalog.networkImpact(profile.id);
    if (!await confirm(profile,profile.enabled ? '停用' : '启用',affected) || !mounted) return;
    await action(() => catalog.updateNetwork(profile.change(enabled:!profile.enabled),expectedRevision:captured,
      beforeCommit:() => widget.closeTabs(affected.map((p) => p.id).toSet())));
  }
  Future<void> remove(NetworkProfile profile) async {
    final captured = catalog.revision,affected = catalog.networkImpact(profile.id);
    if (!await confirm(profile,'删除',affected) || !mounted) return;
    await action(() => catalog.removeNetwork(profile,expectedRevision:captured,
      beforeRemove:() async {
        if (profile.provider == 'easytier' && identities.supported && await identities.status(profile) != null) {
          throw const RemoteFailure('network_identity_present');
        }
      },beforeCommit:() => widget.closeTabs(affected.map((p) => p.id).toSet())));
  }
  Future<void> localIdentity(NetworkProfile profile) async {
    if (!available) return;
    await showDialog<void>(context:context,builder:(_) => NetworkIdentityDialog(profile:profile,catalog:catalog,
      closeTabs:widget.closeTabs,store:identities));
  }
  @override
  Widget build(BuildContext context) => Scaffold(appBar:AppBar(title:const Text('网络管理 · 公开配置')),
    body:SafeArea(child:ListView(padding:const EdgeInsets.all(16),children:[
      const Text('Tailscale、EasyTier、ZeroTier 公开配置可由多台主机复用。本机入网资料单独保管，不随配置导出，也不复制 SSH 私钥或三网身份。'),
      const Text('手机网络连接桥尚未接入：绑定配置后的连接明确返回 provider_unavailable，不会改走系统 TCP / DNS。旧主机的 provider 标签仍只是资料。'),
      if (notice != null) Padding(padding:const EdgeInsets.symmetric(vertical:12),child:Text(notice!,key:const ValueKey('networks-notice'))),
      FilledButton.icon(key:const ValueKey('networks-add'),onPressed:available && catalog.networkProfiles.length < maxNetworkProfiles ? () => edit() : null,
        icon:const Icon(Icons.add),label:const Text('新增网络配置')),
      for (final profile in catalog.networkProfiles) Card(child:Padding(padding:const EdgeInsets.all(16),child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
        Text(profile.label,style:Theme.of(context).textTheme.titleMedium),
        Text('${profile.provider} · ${profile.enabled ? '本机启用' : '本机停用'} · 入网未知'),
        Text('引用主机 ${catalog.networkImpact(profile.id).length} 个'),
        SelectableText(profile.settings.entries.map((e) => '${e.key}: ${e.value}').join('\n')),
        Wrap(spacing:8,children:[
          TextButton(key:ValueKey('network-identity-${profile.id}'),onPressed:available ? () => localIdentity(profile) : null,child:const Text('本机入网资料')),
          TextButton(key:ValueKey('network-edit-${profile.id}'),onPressed:available ? () => edit(profile) : null,child:const Text('编辑公开参数')),
          TextButton(key:ValueKey('network-toggle-${profile.id}'),onPressed:available ? () => toggle(profile) : null,child:Text(profile.enabled ? '停用与影响预览' : '启用与影响预览')),
          TextButton(key:ValueKey('network-delete-${profile.id}'),onPressed:available ? () => remove(profile) : null,child:const Text('删除与影响预览')),
        ]),
      ]))),
    ])));
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
      if (provider == 'tailscale') ...[input('controlUrl','控制服务器 HTTPS URL（空为默认）'),input('hostname','本机名（空为自动，ASCII 标签）')],
      if (provider == 'easytier') ...[input('networkName','公开网络名称（不含加入密码）'),input('peers','公开 peer URI（每行一个，1–16 个）',multiline:true),const Text('支持 tcp / udp / ws / wss；tcp、udp 必须填写端口。')],
      if (provider == 'zerotier') input('networkId','公开 network ID（16 位小写十六进制）'),
      const Padding(padding:EdgeInsets.only(top:12),child:Text('保存不会启动网络、加入网络或授权主机。')),
    ])),actions:[TextButton(onPressed:() => Navigator.pop(context),child:const Text('取消')),
      FilledButton(key:const ValueKey('network-save'),onPressed:save,child:const Text('保存公开配置'))]);
}
