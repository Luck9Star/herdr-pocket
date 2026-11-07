# 第一次用手机连接主机

后续版本已接入设备公开请求的交接、原请求核查和手机撤销回执审查。[手机配对交接与复测步骤](45-mobile-pairing-handoff.md)

2026-11-07。主机 helper 可以生成公开连接资料的二维码。两套手机 GUI 均提供扫码和粘贴入口，预览地址、SSH 端口、账号、会话、路径和本地算出的主机指纹。用户明确填入表单，再从独立渠道核对指纹，才能创建设备身份。此改动位于原型分支。现有两份可下载 APK 对应较早的 `cb0fd1c`。[现有安装包和逐场 Android 结果](43-mobile-viewport-recovery.md#可下载的同源安装包) · [本次分层实测数据](evidence/mobile-pair-gui/connection-profile-20261107.json)

## 从资料到看板

1. 在隔离的非 root POSIX 测试账号上，由操作者指定手机可达地址、端口、命名会话、完整路径和 SSH 主机的 Ed25519 **公钥**，运行 helper 的 `profile` 子命令。它输出 SVG 二维码或同内容的 JSON，可在创建手机身份之前使用。[helper 命令示例](../helper/README.md)
2. 在手机打开新主机表单，扫描资料或粘贴 JSON。展开查看完整路径和指纹，与主机操作者从独立可信渠道提供的值核对。分别验证取消和明确填入两种操作。填入之后，创建身份还需要单独勾选核验；修改目标会使之前的核验失效。
3. 手机创建本设备的密钥并生成公开配对请求。主机用户审查请求、确认授权，手机再审查绑定到原请求的响应。扫码过程中切换目标、修改资料或取消时，迟到结果必须失效。授权结果未知时回到原请求核实。主机 helper 的撤销以原请求 ID 定位。
4. 使用 direct 可在核对连接信息后主动连接。初次扫码资料声明 Tailscale、EasyTier 或 ZeroTier 时，可以离线走配对步骤。首次连接前，必须先把该主机绑定到本机已启用、同类型的网络配置。资料没有本机节点 ID，手工编辑地址或重新打开记录都应保留待绑定状态。真实节点按网络与平台分别验收。
5. 主动连接并验证 SSH host key，经本机设备公钥认证进入看板。选择明确的会话和 pane，等待完整帧及后续增量，再停止观察。切换标签后主动恢复，检查没有输入重放或隐式 PTY 调整。此前两条 GUI 的隔离云模拟器闭环记录可按源码追溯。[两端四场通过的较早记录](40-android-paired-dashboard-validation.md) · [后续复测及三场输入法失败记录](43-mobile-viewport-recovery.md#修订批-android-实测)

## 公开资料的字段

格式 `herdr-connection-profile` v1 最多 2048 个 UTF-8 字节。除了整数 `version`、字符串 `type`，必填项有 `host`、整数 `port`、`username`、`provider`、`session`、`socketPath`、`herdrPath`、`expectedHostKey`。接收端拒绝缺项、多余字段、重复键、无效 UTF-16 代理项、违规路径及非规范 Ed25519 公钥。指纹取 RFC 4253 公钥二进制结构的 SHA-256。授权状态、设备句柄和本机组网身份均不在此格式中。[共用输入和指纹向量](../validation/shared/connection-profile-v1.json)

已有主机的网络标签保留原用途。新版只给通过扫码或粘贴新建的覆盖网络记录加上待绑定标记；绑定成功后保存明确的网络 ID。加密迁移 v2 可以保存待绑定状态，旧 v1 导出遇到这种状态会拒绝降级，避免迁移后意外走系统直连。设备私钥和组网身份分别由本机保管。

## 手机原型

Penpot v2 沿用现有配色。S05 接入 S48 资料预览，完整路径与本地指纹可换行阅读。S49 展示填入后待审查的表单，S51 展示独立核验后继续配对。S50 展示离线配对可用、连接等待本机网络绑定，并可进入 S27 网络配置。保存后经独立查看器实际点击六次，四块 390 × 844 画板均已通过 MCP 重新读取。[打开 S48](https://design.penpot.app/?screen=viewer&file-id=b55064db-d93d-80f9-8008-ddd22e6d398f&page-id=7a22df08-251d-8016-8008-de03541c11da&section=interactions&frame-id=ff7bd149-6597-80a5-8008-e8dca4d84f9b) · [打开 S50](https://design.penpot.app/?screen=viewer&file-id=b55064db-d93d-80f9-8008-ddd22e6d398f&page-id=7a22df08-251d-8016-8008-de03541c11da&section=interactions&frame-id=ff7bd149-6597-80a5-8008-e8dca5134ce1) · [实点记录与图像摘要](../design/evidence/v2-mobile-profile-viewer-20261107.json)

## 验证范围与下批顺序

Mac 上由 helper 生成 SVG，栅格化为 230 × 230 PNG，再用 ZXing 解码。含中文路径的 345 个 UTF-8 字节与 helper 直接生成的 JSON 逐字节相同。共享资料在 Dart 与 JavaScript 路径使用同一份夹具。Rust 的主机目录及传输测试使用临时目录和隔离回环 SSH，覆盖待绑定、恢复、持久化、导入和原目标校验。[逐项结果](evidence/mobile-pair-gui/connection-profile-20261107.json)

| 本次运行 | 实测结果 |
| --- | --- |
| 资料与打包 | Dart 和 JavaScript 均接受 4 个有效样本并拒绝 45 个无效样本。helper 的 13 项测试通过。实际执行了源码包组装步骤，并从包内入口生成资料。 |
| Tauri 与 Rust | 从干净基线加本次改动重新构建，345 项 Node 测试通过，Vite 构建完成。Rust Tauri 库 46 项、传输库 87 项通过。后者在允许本地回环端口后复跑。 |
| Mac 浏览器 | 320 和 390 像素各实测一次新资料扫码，分别让模拟相机在真实标签切回前、切回后返回。用户必须重新查看才能填入，原核验为未勾选，指纹完整可见。每场主动保存一次，设备创建与连接均为零。390 像素还走了原请求的授权响应扫码，重新查看后仍须勾选来源，点击接受才发出一次调用。相机、密钥及 SSH 的原生调用使用替身。 |
| Flutter | 实际运行 Dart 解析与指纹计算，14 份 Dart 文件完成语法解析。Flutter 新增的 widget 和保存恢复用例待云端引擎运行。 |

下批 Android 集中构建优先复跑 Flutter widget 与两端 API 35 配对场景，覆盖扫码返回、设备公钥、看板、完整帧、增量与停止，并复核系统输入法的窗口归属。安装包按提交、ABI 和 SHA-256 对照。物理相机、arm64 真机、真实中文输入法、iOS 安装、三网实连与跨网并发仍待相应设备及网络条件。框架选型保留到这些正确性结果具备可比性之后。
