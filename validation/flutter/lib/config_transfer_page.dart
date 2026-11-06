import 'dart:typed_data';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'config_transfer.dart';
import 'host_catalog.dart';
import 'remote_adapter.dart' show RemoteFailure;

class ConfigTransferPage extends StatefulWidget {
  const ConfigTransferPage({super.key,required this.catalog,required this.closeTabs,this.documents});
  final HostCatalog catalog;
  final void Function(Set<String>) closeTabs;
  final ConfigDocuments? documents;
  @override State<ConfigTransferPage> createState() => _ConfigTransferPageState();
}
class _ConfigTransferPageState extends State<ConfigTransferPage> {
  final password = TextEditingController(), repeatPassword = TextEditingController();
  final selected = <String>{};
  late final documents = widget.documents ?? NativeConfigDocuments();
  bool reviewed = false,busy = false;
  Uint8List? archive;
  ConfigImportPlan? plan;
  List<ConfigImportAction?> choices = [];
  String message = '只迁移名称、网络 provider 和公开连接路径。身份、公钥授权、草稿、未知发送、当前连接均不迁移。';
  bool get supported => widget.documents != null || (!kIsWeb &&
    [TargetPlatform.android,TargetPlatform.iOS,TargetPlatform.macOS].contains(defaultTargetPlatform));
  bool get available => supported && widget.catalog.ready && !widget.catalog.writing && widget.catalog.pendingCreation == null;
  @override void initState() { super.initState(); widget.catalog.addListener(changed); }
  @override void dispose() {
    widget.catalog.removeListener(changed); password.clear(); repeatPassword.clear(); password.dispose(); repeatPassword.dispose();
    archive?.fillRange(0,archive!.length,0); super.dispose();
  }
  void changed() {
    if (!mounted) return;
    setState(() {
      selected.removeWhere((id) => !widget.catalog.profiles.any((p) => p.id == id && !p.retired));
      if (plan != null && (plan!.revision != widget.catalog.revision || !widget.catalog.ready || widget.catalog.pendingCreation != null)) {
        plan = null; choices = []; reviewed = false; message = '目录或待创建状态已变化 · 请重新解密并逐条审查，未自动套用旧选择。';
      }
    });
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
        } : error is RemoteFailure && widget.catalog.ready
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
    final hosts = widget.catalog.exportProfiles(selected), revision = widget.catalog.revision;
    final bytes = await encryptConfigTransfer(password.text,hosts);
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
    plan = null; choices = []; reviewed = false;
    archive?.fillRange(0,archive!.length,0); archive = null;
    if (bytes == null) { setState(() { message = '已取消打开文件。'; }); return; }
    validateTransferEnvelope(bytes);
    setState(() { archive = Uint8List.fromList(bytes); message = '已打开加密文件 · 请输入原口令，解密后逐条审查。'; });
  });
  Future<void> decrypt() => operation(() async {
    final bytes = archive; if (bytes == null) return;
    final hosts = await decryptConfigTransfer(password.text,bytes);
    if (!mounted) return;
    final preview = widget.catalog.previewImport(hosts);
    setState(() { plan = preview; choices = List.filled(hosts.length,null); reviewed = false;
      message = '已解密公开资料 · 尚未写入。逐条选择添加、保留或替换；任何目标仍须重新核验并在此设备配对。'; });
  });
  Future<void> apply() => operation(() async {
    final reviewedPlan = plan;
    if (reviewedPlan == null || !reviewed || choices.any((value) => value == null)) return;
    final decisions = [for (final choice in choices) ConfigImportChoice(choice!)];
    await widget.catalog.applyImport(reviewedPlan,decisions,beforeCommit:(affected) {
      // Whole-plan validation and the queue-time revision check have passed.
      // Revocation is synchronous and immediately precedes the one catalog CAS.
      widget.closeTabs(affected);
      if (mounted) setState(() { plan = null; choices = []; reviewed = false; });
    });
    if (mounted) setState(() { message = '本机公开资料已原子更新 · 新条目没有设备身份，需正式配对。被替换身份已停用保留，请在原主机核验撤销或明确删除。'; });
  });
  Widget secret(TextEditingController controller,String key,String label) => TextField(key:ValueKey(key),controller:controller,
    enabled:available && !busy,obscureText:true,autocorrect:false,enableSuggestions:false,enableIMEPersonalizedLearning:false,
    maxLength:1024,decoration:InputDecoration(labelText:label,helperText:'不裁剪空格，不规范化 Unicode；口令不会写入资料文件。'));
  @override Widget build(BuildContext context) => PopScope(canPop:!busy,child:Scaffold(
    appBar:AppBar(title:const Text('加密迁移公开主机资料')),
    body:SafeArea(child:SingleChildScrollView(padding:const EdgeInsets.all(16),child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
      Text(message,key:const ValueKey('transfer-status')),
      if (!supported) const Text('系统文件打开／保存目前接入 Android、iOS 和 macOS；此平台未启用迁移，不回退公共目录或剪贴板。'),
      if (supported) const Text('Android／Apple 系统文件选择交互仍需设备验收；编译与隔离测试不代表系统选择器已实测。'),
      if (widget.catalog.pendingCreation != null) const Text('存在尚未核实的身份创建操作 · 迁移已禁用，请先处理原记录。'),
      const Text('每次导出最多 16 条，只包含名称、provider、SSH 账号、主机公钥及路径；主机公钥仍需接收端独立核验。'),
      for (final profile in widget.catalog.profiles.where((p) => !p.retired)) CheckboxListTile(
        key:ValueKey('transfer-select-${profile.id}'),value:selected.contains(profile.id),
        onChanged:available && !busy ? (value) => setState(() { if (value == true) { selected.add(profile.id); } else { selected.remove(profile.id); } reviewed = false; }) : null,
        title:Text(profile.label),subtitle:Text('${profile.target['username']}@${profile.target['host']}:${profile.target['port']} / ${profile.target['session']}')),
      secret(password,'transfer-password','迁移口令（新导出至少 12 个 Unicode 字符）'),
      secret(repeatPassword,'transfer-password-repeat','重复新导出口令（只在导出时填写）'),
      FilledButton(key:const ValueKey('transfer-open'),onPressed:available && !busy ? open : null,child:const Text('打开加密文件')),
      if (archive != null) FilledButton(key:const ValueKey('transfer-decrypt'),onPressed:available && !busy ? decrypt : null,child:const Text('使用原口令解密并预览')),
      if (plan != null) ...[
        for (var index = 0; index < plan!.hosts.length; index++) Card(child:Padding(padding:const EdgeInsets.all(12),child:Column(
          crossAxisAlignment:CrossAxisAlignment.stretch,children:[
            Text(plan!.hosts[index].label),
            SelectableText('${hostProviderLabel(plan!.hosts[index].provider)}\n${plan!.hosts[index].target.entries.map((e) => '${e.key}: ${e.value}').join('\n')}'),
            Text(plan!.conflicts[index].isEmpty ? '没有同名或相同目标冲突' : '冲突：${plan!.conflicts[index].map((p) => '${p.label} · ${p.hasIdentity ? '含本机身份，替换会停用保留' : '未配对资料'}').join('；')}'),
            DropdownButtonFormField<ConfigImportAction>(key:ValueKey('transfer-choice-$index'),initialValue:choices[index],
              hint:const Text('请明确选择处理方式'),items:[
                const DropdownMenuItem(value:ConfigImportAction.add,child:Text('添加新条目（不复用身份）')),
                const DropdownMenuItem(value:ConfigImportAction.keep,child:Text('保留本机／跳过此条')),
                if (plan!.conflicts[index].isNotEmpty) const DropdownMenuItem(value:ConfigImportAction.replace,child:Text('替换全部所列冲突（原身份停用保留）')),
              ],onChanged:available && !busy ? (value) => setState(() { choices[index] = value; reviewed = false; }) : null),
          ]))),
      ],
      CheckboxListTile(key:const ValueKey('transfer-review'),value:reviewed,onChanged:available && !busy ? (value) => setState(() { reviewed = value == true; }) : null,
        title:const Text('我已核对范围与所有冲突；迁移不带入信任、身份或授权，替换先停止原标签')),
      FilledButton(key:const ValueKey('transfer-export'),onPressed:available && !busy && reviewed && selected.isNotEmpty && selected.length <= 16 ? export : null,child:const Text('加密并另存所选公开资料')),
      if (plan != null) FilledButton(key:const ValueKey('transfer-apply'),onPressed:available && !busy && reviewed && choices.every((value) => value != null) ? apply : null,child:const Text('按逐条选择原子导入一次')),
      if (busy) const LinearProgressIndicator(),
    ])))));
}
