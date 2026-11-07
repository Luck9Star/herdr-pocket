import 'dart:async';
import 'package:flutter/material.dart';
import 'host_catalog.dart';
import 'zerotier_device.dart';

/// Mobile-first shared-device review. Inherits the Penpot v2 app theme.
class ZeroTierDeviceDialog extends StatefulWidget {
  const ZeroTierDeviceDialog({super.key,required this.catalog,required this.store,this.beforeForget});
  final HostCatalog catalog;
  final ZeroTierDeviceStore store;
  final BeforeZeroTierForget? beforeForget;
  @override State<ZeroTierDeviceDialog> createState() => _ZeroTierDeviceDialogState();
}

class _ZeroTierDeviceDialogState extends State<ZeroTierDeviceDialog> with WidgetsBindingObserver {
  late final session = ZeroTierDeviceSession(store:widget.store,
    impact:() => ZeroTierDeviceImpact.capture(widget.catalog),beforeForget:widget.beforeForget);
  late String catalogKey;
  bool acknowledged = false;
  Object? acknowledgedReview;
  @override void initState() {
    super.initState(); catalogKey = ZeroTierDeviceImpact.capture(widget.catalog).key;
    widget.catalog.addListener(catalogChanged); session.addListener(changed);
    WidgetsBinding.instance.addObserver(this); unawaited(session.refresh());
  }
  void changed() {
    final current = session.review ?? session.pendingReview;
    if (current != acknowledgedReview) { acknowledged = false; acknowledgedReview = current; }
    if (mounted) setState(() {});
  }
  void catalogChanged() {
    final next = ZeroTierDeviceImpact.capture(widget.catalog).key;
    if (next != catalogKey) { catalogKey = next; session.invalidate(); }
  }
  @override void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) { unawaited(session.resume()); }
    else { session.suspend(); }
  }
  @override void dispose() {
    WidgetsBinding.instance.removeObserver(this); widget.catalog.removeListener(catalogChanged);
    session.removeListener(changed); session.dispose(); super.dispose();
  }
  Widget section(String title,List<Widget> children) => Card(child:Padding(padding:const EdgeInsets.all(16),
    child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
      Text(title,style:Theme.of(context).textTheme.titleMedium),const SizedBox(height:8),...children])));
  String phaseLabel(String phase) => switch (phase) {
    'record-pending' => '创建记录待确认',
    'record-present' => '已有记录，操作尚未完成',
    'record-removed' => '记录已移除，清理尚未确认',
    _ => '最终确认待完成',
  };
  List<Widget> affected(ZeroTierDeviceImpact impact) => [
    if (!impact.ready) const Text('影响范围尚未确认 · 请等待主机与网络目录读取完成，再重新审查。',key:ValueKey('zt-impact-unknown'))
    else ...[
    Text('完整影响范围 · ${impact.networks.length} 个网络 / ${impact.hosts.length} 台主机'),
    const Text('包含停用网络、停用或归档主机，以及旧版 ZeroTier 标签主机。'),
    if (impact.networks.isEmpty) const Text('当前没有 ZeroTier 公开网络。'),
    for (final network in impact.networks) Padding(padding:const EdgeInsets.only(top:12),child:Column(
      crossAxisAlignment:CrossAxisAlignment.start,children:[
        Text(network.label,style:Theme.of(context).textTheme.titleSmall),
        Text('网络 ID：${network.settings['networkId']} · ${network.enabled ? '启用' : '停用'}'),
        SelectableText('配置：${network.id} · 版本 ${network.revision}'),
      ])),
    if (impact.hosts.isEmpty) const Padding(padding:EdgeInsets.only(top:8),child:Text('当前没有受影响主机。')),
    for (final host in impact.hosts) Padding(padding:const EdgeInsets.only(top:12),child:Column(
      crossAxisAlignment:CrossAxisAlignment.start,children:[
        Text('${host.label} · ${host.retired ? '归档' : host.enabled ? '启用' : '停用'}'),
        SelectableText('主机：${host.id}'),
        Text(host.networkProfileId == null ? '旧版 ZeroTier 标签 · 未绑定公开配置' : '绑定配置：${host.networkProfileId}'),
      ])),
    ],
  ];
  @override Widget build(BuildContext context) {
    final review = session.review,pendingReview = session.pendingReview,impact = ZeroTierDeviceImpact.capture(widget.catalog),status = session.status;
    return PopScope<void>(onPopInvokedWithResult:(didPop,result) {
      // A popped route remains mounted during its reverse animation. Revoke
      // the review immediately so a late stop proof cannot dispatch a write.
      if (didPop) session.suspend();
    },child:Dialog.fullscreen(child:Scaffold(appBar:AppBar(title:const Text('ZeroTier · 共享设备身份'),
      leading:IconButton(key:const ValueKey('zt-device-close'),tooltip:'关闭',icon:const Icon(Icons.close),onPressed:() => Navigator.pop(context))),
      body:SafeArea(child:Align(alignment:Alignment.topCenter,child:ConstrainedBox(constraints:const BoxConstraints(maxWidth:600),
        child:ListView(key:const ValueKey('zt-device-list'),padding:const EdgeInsets.all(16),children:[
          section('整台设备，一个身份',[
            const Text('所有 ZeroTier 公开网络共享同一个设备身份。退出或删除一个网络配置，不会删除此身份。'),
            const SizedBox(height:8),
            const Text('本页只管理设备身份，不启动网络连接、不导出身份，也不验证 SSH 或 herdr 连通。'),
          ]),
          if (session.busy) const LinearProgressIndicator(semanticsLabel:'正在读取或更新共享设备身份'),
          if (session.notice != null) Padding(padding:const EdgeInsets.all(12),child:Semantics(liveRegion:true,
            child:Text(session.notice!,key:const ValueKey('zt-device-notice')))),
          section('本机状态',[
            Semantics(liveRegion:true,child:Text(session.writePending ? '原设备操作尚未确认 · 本页暂时只读'
              : status == null ? '尚未确认 · 请读取原状态' : !status.available ? '设备身份暂不可用 · 可能是本版本未启用原生组件、设备锁定或读取失败；请核对后重新读取，不代表已入网'
              : status.absent ? '已确认：没有设备身份' : status.device != null ? '已确认：共享设备身份存在' : '有未完成操作 · 不能新建或替换',
              key:const ValueKey('zt-device-state'))),
            if (status?.device != null) ...[
              SelectableText('身份记录编号：${status!.device!.handle}'),
              const Text('此编号用于核对本机记录，不是 SSH 指纹或 ZeroTier 节点编号。'),
            ],
            if (status?.pendingCreation != null || status?.pendingDeletion != null) ...[
              SelectableText('身份记录编号：${(status!.pendingCreation ?? status.pendingDeletion)!.handle}'),
              Text('阶段：${phaseLabel((status.pendingCreation ?? status.pendingDeletion)!.phase)}'),
              const Text('仅处理这条原记录。请先审查全部影响并确认；不会自动恢复、丢弃、重新创建或重试移除。'),
              if (status.pendingCreation?.phase == 'finishing') const Text('最终确认阶段无法仅凭此页判断身份是否已安装。恢复或丢弃都可能被拒绝，结果需要重新读取核对。'),
            ],
            const SizedBox(height:8),
            OutlinedButton.icon(key:const ValueKey('zt-device-refresh'),onPressed:session.busy ? null : session.refresh,
              icon:const Icon(Icons.refresh),label:const Text('重新读取原状态')),
            FilledButton(key:const ValueKey('zt-device-create'),onPressed:session.canCreate ? session.create : null,child:const Text('创建设备身份')),
          ]),
          section(review == null && pendingReview == null ? '所有共享网络与主机' : '第 2 步 · 核对完整范围',affected(review?.impact ?? pendingReview?.impact ?? impact)),
          if (pendingReview != null) section(zeroTierPendingActionLabel(pendingReview.action),[
            SelectableText('原身份记录编号：${pendingReview.pending.handle}'),
            Text('已审查阶段：${phaseLabel(pendingReview.pending.phase)}'),
            Text(pendingReview.action == 'recoverPendingDeletion'
              ? '仅继续已经开始的原身份移除，不会发起新的移除。若相关连接仍未停止，操作会被拒绝。'
              : pendingReview.action == 'discardPendingCreation'
                ? '仅尝试清理原未完成创建。若身份已经安装，不能据此强行丢弃；结果以重新读取为准。'
                : '仅尝试完成原身份创建，不会换成新身份；结果以重新读取为准。'),
            CheckboxListTile(key:const ValueKey('zt-pending-acknowledge'),contentPadding:EdgeInsets.zero,value:acknowledged,
              title:const Text('我已核对原记录编号、当前阶段与上方全部受影响网络、主机'),
              onChanged:session.currentPendingReview(pendingReview) ? (value) => setState(() { acknowledged = value == true; }) : null),
            FilledButton(key:const ValueKey('zt-pending-confirm'),onPressed:acknowledged && session.currentPendingReview(pendingReview)
              ? () => session.confirmPending(pendingReview) : null,child:Text('确认${zeroTierPendingActionLabel(pendingReview.action)}')),
            TextButton(key:const ValueKey('zt-pending-cancel-review'),onPressed:session.cancelReview,child:const Text('取消审查')),
          ]) else if (review == null && (status?.pendingCreation != null || status?.pendingDeletion != null)) section('审查原待完成操作',[
            for (final action in ['recoverPendingCreation','discardPendingCreation','recoverPendingDeletion'])
              if (session.canReviewPending(action)) OutlinedButton(key:ValueKey('zt-pending-review-$action'),
                onPressed:() => session.beginPendingReview(action),child:Text('第 1 步 · ${zeroTierPendingActionLabel(action)}')),
          ]) else if (review == null) section('移除整台设备身份',[
            const Text('将影响上述全部网络与主机。需要先审查原身份，再明确确认；所有相关网络连接仍需确认已停止。'),
            if (widget.beforeForget == null) const Text('当前版本暂不支持此操作。相关网络连接仍需确认已停止。'),
            OutlinedButton(key:const ValueKey('zt-device-review'),onPressed:session.canReview ? session.beginReview : null,
              child:const Text('第 1 步 · 审查移除影响')),
          ]) else section('确认原身份',[
            SelectableText('将移除的身份记录编号：${review.device.handle}'),
            const Text('这是设备级移除，不能作为单网退出。不会自动新建身份或重连。'),
            CheckboxListTile(key:const ValueKey('zt-device-acknowledge'),contentPadding:EdgeInsets.zero,
              value:acknowledged,title:const Text('我已核对原身份记录编号与上方全部受影响网络、主机'),
              onChanged:session.currentReview(review) ? (value) => setState(() { acknowledged = value == true; }) : null),
            FilledButton(key:const ValueKey('zt-device-forget'),onPressed:acknowledged && session.currentReview(review)
              ? () => session.forget(review) : null,child:const Text('确认停止并移除共享设备身份')),
            TextButton(key:const ValueKey('zt-device-cancel-review'),onPressed:session.cancelReview,child:const Text('取消审查')),
          ]),
        ])))))));
  }
}
