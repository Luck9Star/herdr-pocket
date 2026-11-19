import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'config_transfer.dart';
import 'host_catalog.dart';
import 'host_tabs.dart';
import 'remote_adapter.dart' show RemoteFailure;

class ConfigTransferPage extends StatefulWidget {
  const ConfigTransferPage({super.key,required this.catalog,required this.closeTabs,this.tabs,this.documents});
  final HostCatalog catalog;
  final void Function(Set<String>) closeTabs;
  final HostTabs? tabs;
  final ConfigDocuments? documents;
  @override State<ConfigTransferPage> createState() => _ConfigTransferPageState();
}
class _ConfigTransferPageState extends State<ConfigTransferPage> {
  final password = TextEditingController(), repeatPassword = TextEditingController();
  final selected = <String>{},selectedNetworks = <String>{},importNetworks = <String>{};
  bool includePreferences = false,applyPreferences = false;
  late final documents = widget.documents ?? NativeConfigDocuments();
  bool reviewed = false,busy = false;
  Uint8List? archive;
  ConfigImportPlan? plan;
  List<ConfigImportAction?> choices = [];
  List<(String,bool)> reviewedImpact = const [];
  String message = '只迁移公开主机、网络参数和明确选择的终端显示偏好。身份、公钥授权、草稿、未知发送、当前连接均不迁移。';
  bool get supported => widget.documents != null || (!kIsWeb &&
    [TargetPlatform.android,TargetPlatform.iOS,TargetPlatform.macOS].contains(defaultTargetPlatform));
  bool get available => supported && widget.catalog.ready && !widget.catalog.writing && widget.catalog.pendingCreation == null;
  @override void initState() { super.initState(); widget.catalog.addListener(changed); widget.tabs?.addListener(changed); }
  @override void dispose() {
    widget.tabs?.removeListener(changed);
    widget.catalog.removeListener(changed); password.clear(); repeatPassword.clear(); password.dispose(); repeatPassword.dispose();
    archive?.fillRange(0,archive!.length,0); super.dispose();
  }
  void changed() {
    if (!mounted) return;
    setState(() {
      selected.removeWhere((id) => !widget.catalog.profiles.any((p) => p.id == id && !p.retired));
      selectedNetworks.removeWhere((id) => !widget.catalog.networkProfiles.any((p) => p.id == id));
      if (plan != null && (plan!.revision != widget.catalog.revision || !widget.catalog.ready || widget.catalog.pendingCreation != null)) {
        plan = null; choices = []; importNetworks.clear(); applyPreferences = false; reviewed = false; message = '目录或待创建状态已变化 · 请重新解密并逐条审查，未自动套用旧选择。';
      }
      if (reviewed && !listEquals(reviewedImpact,impactScope(replacedHosts))) {
        reviewed = false;
        message = '受影响的标签已变化 · 请重新核对确认。';
      }
    });
  }
  Set<String> get replacedHosts {
    final preview = plan;
    return preview == null ? {} : {
      for (final (index,choice) in choices.indexed)
        if (choice == ConfigImportAction.replace) ...preview.conflicts[index].map((profile) => profile.id),
    };
  }
  Iterable<(int,HostTab)> affectedTabs(Set<String> hosts) =>
    (widget.tabs?.tabs ?? const <HostTab>[]).indexed.where((entry) => hosts.contains(entry.$2.hostId));
  List<(String,bool)> impactScope(Set<String> hosts) =>
    [for (final (_,tab) in affectedTabs(hosts)) (tab.id,tab.inputEligible.value)];

  Widget importImpact(Set<String> hosts) {
    final affected = affectedTabs(hosts).toList();
    return Card(key:const ValueKey('transfer-impact'),child:Padding(padding:const EdgeInsets.all(12),child:Column(
      crossAxisAlignment:CrossAxisAlignment.start,children:[
        if (affected.isEmpty) const Text('当前没有受影响的本地标签。') else ...[
          Text('确认后将停止连接',style:Theme.of(context).textTheme.titleSmall),
          for (final (index,tab) in affected) Padding(
            key:ValueKey('transfer-affected-tab-${tab.id}'),padding:const EdgeInsets.only(top:6),
            child:ValueListenableBuilder<HostTabView>(valueListenable:tab.view,builder:(_,view,_) => Text(
              '标签 ${index+1} · ${tab.label} · ${view.target}'
              '${tab.inputEligible.value ? ' · 输入焦点将撤回' : ''}',
            )),
          ),
          if (!affected.any((entry) => entry.$2.inputEligible.value))
            const Padding(padding:EdgeInsets.only(top:6),child:Text('以上标签当前均不能从本机输入。')),
        ],
      ],
    )));
  }
  Future<void> operation(Future<void> Function() work) async {
    if (busy || !available) return;
    setState(() { busy = true; });
    try { await work(); }
    catch (error) {
      if (mounted) setState(() { message = error is TransferFailure
        ? switch (error.code) {
          'transfer_invalid_password' => '口令无效 · 新口令至少 12 个 Unicode 字符，读入口令 1–1024 UTF-8 bytes；不裁剪或规范化。',
          'transfer_auth_failed' => '口令不匹配或文件被改动 · 未导入任何资料。',
          'transfer_unsupported_version' => '文件版本不支持 · 未运行口令派生或导入。',
          _ => '文件格式、大小或公开字段不符合约定 · 未导入任何资料。',
        } : error is RemoteFailure && error.code == 'transfer_network_unavailable'
          ? '此阶段不导出已绑定网络的主机 · 请等待保留网络绑定的迁移格式，不能静默降级为系统直连。'
          : error is RemoteFailure && error.code == 'catalog_transfer_impact_changed'
          ? '受影响的标签已变化 · 请重新核对确认。'
          : error is RemoteFailure && widget.catalog.ready
          ? '导入选择冲突、容量不足或审查计划已过期 · 尚未保存，请修正并重新审查。'
          : '操作未确认或目录版本冲突 · 文件或本机保存可能已生效，请返回重新读取核验；不会重放。'; });
    } finally {
      password.clear(); repeatPassword.clear();
      if (mounted) setState(() { busy = false; });
    }
  }
  Future<void> export() => operation(() async {
    if (!reviewed || password.text != repeatPassword.text) {
      setState(() { message = '请审查导出范围并输入两次相同的新口令。'; }); return;
    }
    final config = widget.catalog.exportConfig(selected,selectedNetworks,includePreferences:includePreferences), revision = widget.catalog.revision;
    final bytes = await encryptPortableConfig(password.text,config);
    try {
      if (!mounted) return;
      if (!widget.catalog.ready || widget.catalog.revision != revision || widget.catalog.pendingCreation != null) {
        setState(() { message = '加密期间目录已变化 · 未保存文件，请重新审查。'; }); return;
      }
      final saved = await documents.save(bytes);
      if (mounted) setState(() { message = saved ? '加密文件已交给系统保存 · 接收设备仍需审查并独立配对。' : '已取消保存 · 未写入主机目录。'; });
    } finally { bytes.fillRange(0,bytes.length,0); }
  });
  Future<void> open() => operation(() async {
    final bytes = await documents.open();
    if (!mounted) return;
    plan = null; choices = []; importNetworks.clear(); applyPreferences = false; reviewed = false;
    archive?.fillRange(0,archive!.length,0); archive = null;
    if (bytes == null) { setState(() { message = '已取消打开文件。'; }); return; }
    validateTransferEnvelope(bytes);
    setState(() { archive = Uint8List.fromList(bytes); message = '已打开加密文件 · 请输入原口令，解密后逐条审查。'; });
  });
  Future<void> decrypt() => operation(() async {
    final bytes = archive; if (bytes == null) return;
    final config = await decryptPortableConfig(password.text,bytes);
    if (!mounted) return;
    final preview = widget.catalog.previewConfigImport(config);
    setState(() { plan = preview; choices = List.filled(config.hosts.length,null); importNetworks.clear(); applyPreferences = false; reviewed = false;
      message = '已解密公开资料 · 尚未写入。逐条选择添加、保留或替换；任何目标仍须重新核验并在此设备配对。'; });
  });
  Future<void> apply() => operation(() async {
    final reviewedPlan = plan;
    if (reviewedPlan == null || !reviewed || choices.any((value) => value == null)) return;
    final decisions = [for (final choice in choices) ConfigImportChoice(choice!)];
    final approvedImpact = reviewedImpact;
    await widget.catalog.applyConfigImport(reviewedPlan,decisions,selectedNetworks:Set.of(importNetworks),applyPreferences:applyPreferences,beforeCommit:(affected) {
      // Whole-plan validation and the queue-time revision check have passed.
      // Revocation is synchronous and immediately precedes the one catalog CAS.
      if (!listEquals(approvedImpact,impactScope(affected))) {
        if (mounted) setState(() { reviewed = false; });
        throw const RemoteFailure('catalog_transfer_impact_changed');
      }
      widget.closeTabs(affected);
      if (mounted) setState(() { plan = null; choices = []; reviewed = false; });
    });
    if (mounted) setState(() { message = '本机公开资料已原子更新 · 新条目没有设备身份，需正式配对。被替换身份已停用保留，请在原主机核验撤销或明确删除。'; });
  });
  Widget secret(TextEditingController controller,String key,String label) => TextField(key:ValueKey(key),controller:controller,
    enabled:available && !busy,obscureText:true,autocorrect:false,enableSuggestions:false,enableIMEPersonalizedLearning:false,
    maxLength:1024,decoration:InputDecoration(labelText:label,helperText:'不裁剪空格，不规范化 Unicode；口令不会写入资料文件。'));
  @override Widget build(BuildContext context) {
    final affectedHosts = replacedHosts;
    return PopScope(canPop:!busy,child:Scaffold(
    appBar:AppBar(title:const Text('加密迁移公开配置')),
    body:SafeArea(child:SingleChildScrollView(padding:const EdgeInsets.all(16),child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
      Text(message,key:const ValueKey('transfer-status')),
      if (!supported) const Text('系统文件打开／保存目前接入 Android、iOS 和 macOS；此平台未启用迁移，不回退公共目录或剪贴板。'),
      if (supported) const Text('Android／Apple 系统文件选择交互仍需设备验收；编译与隔离测试不代表系统选择器已实测。'),
      if (widget.catalog.pendingCreation != null) const Text('存在尚未核实的身份创建操作 · 迁移已禁用，请先处理原记录。'),
      const Text('每份档案最多 16 台主机与 16 个网络。所选主机自动携带依赖网络；可单独迁移网络或终端字号。导入网络一律新建为本机停用，不复用三网身份。主机公钥仍需独立核验。'),
      for (final profile in widget.catalog.profiles.where((p) => !p.retired)) CheckboxListTile(
        key:ValueKey('transfer-select-${profile.id}'),value:selected.contains(profile.id),
        onChanged:available && !busy ? (value) => setState(() { if (value == true) { selected.add(profile.id); } else { selected.remove(profile.id); } reviewed = false; }) : null,
        title:Text(profile.label),subtitle:Text('${profile.target['username']}@${profile.target['host']}:${profile.target['port']} / ${profile.target['session']}')),
      for (final network in widget.catalog.networkProfiles) CheckboxListTile(
        key:ValueKey('transfer-network-select-${network.id}'),value:selectedNetworks.contains(network.id),
        onChanged:available && !busy ? (value) => setState(() { if (value == true) { selectedNetworks.add(network.id); } else { selectedNetworks.remove(network.id); } reviewed = false; }) : null,
        title:Text('独立网络：${network.label}'),subtitle:Text('${network.provider} · 所选主机的依赖会自动携带；不迁移身份与启用状态')),
      CheckboxListTile(key:const ValueKey('transfer-export-preferences'),value:includePreferences,
        onChanged:available && !busy ? (value) => setState(() { includePreferences = value == true; reviewed = false; }) : null,
        title:Text('导出本机终端字号（${widget.catalog.terminalFontSize} px）')),
      secret(password,'transfer-password','迁移口令（新导出至少 12 个 Unicode 字符）'),
      secret(repeatPassword,'transfer-password-repeat','重复新导出口令（只在导出时填写）'),
      FilledButton(key:const ValueKey('transfer-open'),onPressed:available && !busy ? open : null,child:const Text('打开加密文件')),
      if (archive != null) FilledButton(key:const ValueKey('transfer-decrypt'),onPressed:available && !busy ? decrypt : null,child:const Text('使用原口令解密并预览')),
      if (plan != null) ...[
        for (var index = 0; index < plan!.hosts.length; index++) Card(child:Padding(padding:const EdgeInsets.all(12),child:Column(
          crossAxisAlignment:CrossAxisAlignment.stretch,children:[
            Text(plan!.hosts[index].label),
            SelectableText('${hostProviderLabel(plan!.hosts[index].provider)}\n${plan!.hosts[index].target.entries.map((e) => '${e.key}: ${e.value}').join('\n')}'),
            Text(plan!.conflicts[index].isEmpty ? '没有同名或相同目标冲突'
              : '冲突：\n${plan!.conflicts[index].map((p) => '${p.label} · ${p.hasIdentity ? '替换时停用资料并保留本机身份' : '未配对，替换时移除资料'}').join('\n')}'),
            DropdownButtonFormField<ConfigImportAction>(key:ValueKey('transfer-choice-$index'),initialValue:choices[index],
              isExpanded:true,
              hint:const Text('请明确选择处理方式'),items:[
                const DropdownMenuItem(value:ConfigImportAction.add,child:Text('添加新条目（不复用身份）')),
                const DropdownMenuItem(value:ConfigImportAction.keep,child:Text('保留本机／跳过此条')),
                if (plan!.conflicts[index].isNotEmpty) const DropdownMenuItem(value:ConfigImportAction.replace,child:Text('替换全部冲突')),
              ],onChanged:available && !busy ? (value) => setState(() { choices[index] = value; reviewed = false; }) : null),
          ]))),
        for (var index = 0; index < (plan!.config?.networks.length ?? 0); index++) Card(child:Padding(padding:const EdgeInsets.all(12),child:Column(
          crossAxisAlignment:CrossAxisAlignment.stretch,children:[
            Text('导入网络：${plan!.config!.networks[index].label} · ${plan!.config!.networks[index].provider}'),
            SelectableText(plan!.config!.networks[index].settings.entries.map((e) => '${e.key}: ${e.value}').join('\n')),
            const Text('将以新本机配置创建并保持停用，不复用现有网络身份。实际添加的主机所引用网络会自动创建；跳过主机不会自动创建其网络。'),
            if (plan!.networkConflicts[index].isNotEmpty) ...[
              const Text('存在同名本机网络（保留原配置，导入时仍新建；可取消）：'),
              for (final existing in plan!.networkConflicts[index]) SelectableText('${existing.label} · ${existing.provider}\n${existing.settings.entries.map((e) => '${e.key}: ${e.value}').join('\n')}'),
            ],
            CheckboxListTile(key:ValueKey('transfer-import-network-${plan!.config!.networks[index].key}'),
              value:importNetworks.contains(plan!.config!.networks[index].key),title:const Text('即使没有添加引用主机，也单独导入此网络'),
              onChanged:available && !busy ? (value) => setState(() { final key = plan!.config!.networks[index].key;
                if (value == true) { importNetworks.add(key); } else { importNetworks.remove(key); } reviewed = false; }) : null),
          ]))),
        if (plan!.config?.terminalFontSize != null) CheckboxListTile(key:const ValueKey('transfer-import-preferences'),value:applyPreferences,
          title:Text('明确应用档案终端字号（${plan!.config!.terminalFontSize} px，当前 ${widget.catalog.terminalFontSize} px）'),
          subtitle:const Text('默认不覆盖。本机显示改变不会调整共享 PTY。'),
          onChanged:available && !busy ? (value) => setState(() { applyPreferences = value == true; reviewed = false; }) : null),
      ],
      if (widget.tabs != null && affectedHosts.isNotEmpty) importImpact(affectedHosts),
      CheckboxListTile(key:const ValueKey('transfer-review'),value:reviewed,onChanged:available && !busy ? (value) => setState(() {
        reviewed = value == true;
        reviewedImpact = reviewed ? impactScope(affectedHosts) : const [];
      }) : null,title:const Text('我已核对范围与冲突。迁移不带入信任、身份或授权，替换会停止相关连接。')),
      FilledButton(key:const ValueKey('transfer-export'),onPressed:available && !busy && reviewed && (selected.isNotEmpty || selectedNetworks.isNotEmpty || includePreferences) && selected.length <= 16 ? export : null,child:const Text('加密并另存所选公开资料')),
      if (plan != null) FilledButton(key:const ValueKey('transfer-apply'),onPressed:available && !busy && reviewed && choices.every((value) => value != null) ? apply : null,child:const Text('按所选范围原子导入一次')),
      if (busy) const LinearProgressIndicator(),
    ])))));
  }
}
