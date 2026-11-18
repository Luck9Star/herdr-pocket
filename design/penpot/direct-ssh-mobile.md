# 普通 SSH 手机设计与像素验收

Flutter 和 Tauri 共用同一套画板与测量规则。行为沿用 [docs/63 普通 SSH](../../docs/63-design-parity-and-direct-ssh.md)。首页沿用已归档 [v2 S01](../evidence/v2-S01.png) 和 [空首页 P1-empty](../evidence/penpot-final-after-reload-20261030.json) 的入口层级，指纹审查借鉴 [S49](../evidence/v2-S49-profile-review-20261107.png)，阻断状态借鉴 [S10](../evidence/v2-S10.png)，终端沿用 [S43](../evidence/v2-S43-keyboard-20261107.png) 的键盘开合与辅助键布局。颜色、圆角、普通字号和命中区使用[共享 v2 tokens](../../validation/shared/design-tokens-v2.json)。

## 打开与编辑

[打开离线画板总览](direct-ssh-mobile.svg)。[生成源](direct-ssh-mobile.mjs)保留可编辑的文本与矢量图层，工作流不依赖线上预览或生产截图。从仓库根目录导出逐页文件与坐标清单：

```sh
node design/penpot/direct-ssh-mobile.mjs \
  design/penpot/direct-ssh-mobile.svg \
  /tmp/herdr-pocket-ssh-design
```

直接打开目录内的 `<状态>-390.svg` 或 `<状态>-320.svg` 即可按原尺寸测量。`geometry.json` 中每页的 `atlas` 指定其在总览中的裁切区域，`anchors` 给出画板内坐标。总览画板组以 `<状态>-<宽>` 命名，内部层为 `<状态>-<宽>-<锚点>`。标签标题在裁切区域外。Penpot 可逐页拖入 SVG 后将要编辑的画面建为画板。此次交付在线编辑器登录未就绪，实际导入时的文本转换和字体回退仍待核对。 [导入与图层](https://help.penpot.app/user-guide/designing/layers/) · [SVG 数据模型](https://help.penpot.app/technical-guide/developer/data-model/)

## 页面与状态

画板呈现每一步的独立状态。普通 SSH 可以从空首页直接进入，也可经「添加主机」进入连接方式选择。空首页画板用于无已保存主机的默认首页。已有主机、搜索与筛选态继续沿用 [v2 S01](../evidence/v2-S01.png) 与[主机筛选记录](../evidence/mobile-host-filter-20261108.json)。P1-empty 是历史设计来源，演示数据属于历史原型。主路径为填写地址、探测、核对、账号认证、活动终端、断开后回首页。凭据字段为示意，域名、账号、指纹和终端输出均使用虚构数据。实测时可用临时夹具替换这些值，保留状态和测量条件。

| 画板前缀 | 截取条件与预期行为 | 必测锚点 |
| --- | --- | --- |
| `home` | 没有主机。点击「普通 SSH」直达目标表单，「添加主机」打开接入选择。 | `home-empty-card`、`home-add`、`home-direct-ssh`、`home-tabs` |
| `choose` | 显示普通 SSH 与 herdr 接入，选择普通 SSH 后进入目标表单。 | `app-header`、`back`、`choose-ssh`、`choose-herdr` |
| `target` | 填写主机地址、用户名、端口，默认端口 22。画板取三个字段已填的状态，点击探测后获取主机密钥。 | `host`、`username`、`port`、`probe` |
| `target-focused` | 用户名获焦、键盘展开，用户名和端口同排。仍能查看聚焦字段，空间不足时可滚到探测操作。 | `username`、`port`、`probe`、`system-keyboard` |
| `trust` | 首次见到该目标的密钥，先显示 `用户@主机:端口`、算法、完整 SHA256 指纹和独立核对提示。显式选择「指纹一致，确认继续」才进入认证，取消回到目标表单。 | `target-card`、`key-evidence`、`key-fingerprint`、`trust-confirm`、`trust-cancel` |
| `password` | 核对后选择密码，画板取密码已填写且遮罩、连接可用的状态。 | `target-card`、`trust-approved`、`auth-password`、`auth-key`、`password`、`connect` |
| `private-key` | 核对后选择已有私钥。独立的 PEM 编辑区、粘贴操作和加密私钥口令。口令输入后遮罩；画板取 PEM 空白的状态，连接不可用。完整 PEM 与该认证方式所需的值齐备后，连接按钮启用。 | `target-card`、`trust-approved`、`auth-password`、`auth-key`、`key-pem`、`paste-key`、`passphrase`、`connect` |
| `terminal-open` | 已建立 PTY 与 Shell，真实系统键盘展开，底栏收起。顶部保持连接身份和可命中的断开操作，辅助键在 IME 上方，终端可见远端回显。 | `disconnect`、`terminal-status`、`keyboard-toggle`、`terminal-panel`、`terminal-keys`、各 `key-*`、`system-keyboard` |
| `terminal-closed` | 同一活动会话收起系统键盘，终端扩展。底栏恢复，辅助键留在底栏上方，可重新打开键盘或去设置。 | `disconnect`、`terminal-status`、`keyboard-toggle`、`terminal-panel`、`terminal-keys`、各 `key-*`、`terminal-tabs`、`tab-settings` |
| `settings-active` | 在活动连接期间切到设置，显示连接仍活动及原目标。点击底栏「终端」回到同一会话的键盘收起状态。 | `active-ssh`、`target-card`、`settings-tabs`、`tab-terminal` |
| `disconnected` | 显式断开，回到保留连接目标的表单。临时密码、私钥与口令已清空，可重新探测或返回首页。 | `closed-feedback`、`host`、`username`、`port`、`probe`、`return-home` |
| `returned` | 返回未添加主机的首页，显示一次「普通 SSH 已断开」反馈。 | `closed-feedback`、`home-empty-card`、`home-direct-ssh`、`home-tabs` |
| `key-changed` | 发现主机密钥不同，阻断认证和终端输入。可独立比对旧指纹与本次呈现的新指纹，或取消并保留旧信任。 | `changed-warning`、`target-card`、`changed-keys`、`previous-key-fingerprint`、`presented-key-fingerprint`、`recheck`、`keep-previous-trust` |
| `previous-trust` | 用户放弃换钥后回到原目标表单，旧信任保留。后续探测仍按该目标的已核对结果处理。 | `trust-preserved`、`host`、`username`、`port`、`probe` |
| `recheck-trust` | 重新探测后独立审查目标、密钥算法和完整新指纹。显式确认才更新该目标的信任并继续认证；取消保留旧信任。 | `target-card`、`key-evidence`、`key-fingerprint`、`trust-confirm`、`trust-cancel` |

完整指纹支持断行，拼接后须与独立取得的 `SHA256:` 指纹逐字符一致。目标的长主机名可断行，必要时允许从字段查看完整地址。原始公钥如有展示需求，放在可选详情。轮换画板演示已获得新旧指纹且算法相同的状态。实际算法不同时分别标明，未取得新指纹时显示「待重新探测」。密码与私钥是互斥认证表单，临时秘密不应出现在日志、验收截图或取消后的界面中。

## 键盘、导航与退出

- 终端可用状态下，键盘操作的无障碍名称随状态为「打开键盘」或「收起键盘」。该操作只变更输入焦点和画面可用高度，终端、连接和已有回显继续保留，切换本身零输入。画板中的辅助键为两壳共有键，其他已支持的键仍按各自现有入口提供。
- 收起键盘后可用底栏切换看板、网络或设置。切出终端时退出终端输入焦点，隐藏页禁止输入，回到底栏「终端」恢复原会话及原回显，无需重认证。此处仅指应用内切页，应用进入系统后台仍按现有客户端的连接生命周期处理。
- 「断开」关闭当前 SSH 会话并清空本次凭据，随后可退回首页。原生系统返回若关闭 SSH 路由，也应关闭会话和清理凭据。关闭路由和底栏跨页切换在验收时分别记录。
- 基线 Tauri 的底栏可切到设置再回到同一连接，已有 macOS 原生证据。R19 的 iOS 终端截图记录了 Tauri 底栏遮挡按钮边缘。基线 Flutter 普通 SSH 是独立路由，返回会销毁该页的连接。画板将底栏往返和正常退出同时列为共用视觉目标。 [既有功能证据](../../docs/63-design-parity-and-direct-ssh.md#本轮实际验证) · [R19 终端截图观察](../../docs/70-ios-ssh-host-key-rotation.md#r19-同源结果两壳通过活动标题与顶栏分离)

## 坐标与判定

| 参考视口 | 顶部安全区 | 底部安全区 | 键盘顶部 | 内容水平边距 |
| --- | ---: | ---: | ---: | ---: |
| 390 × 844 pt | 47 pt | 34 pt | 553 pt | 24 pt |
| 320 × 640 pt | 24 pt | 24 pt | 402 pt | 16 pt |

1. 以全屏画板左上角为 `(0, 0)`，x 水平向右，y 垂直向下。1 SVG 单位对应 1 逻辑点，用 iOS point、Android dp、Flutter logical pixel 或正常缩放下的 CSS px 记录。屏幕截图使用实测像素与逻辑点比例换算。如果采集范围从应用内容开始，先补上相应的系统安全区偏移。配对平台、方向、字体缩放、IME 开合状态和画面滚动位置。
2. 逐页记录 `anchors` 各矩形的 x、y、宽、高与实际状态，四项各自的绝对偏差须 ≤2 pt。`role: hit` 记录真实可触区域，图标边界可更小，点击最小尺寸仍为 44 × 44 pt。`geometry` 与 `disabled` 测显示区域和启用状态。`system` 统计系统区域外框，状态栏、系统手势指示条及 IME 内部容貌随设备变化。
3. 不同设备使用同样的锚点关系。顶部测 `y − 顶部安全区`，底部测 `可用区下缘 − (y + 高)`。用系统 IME 顶缘、底栏上缘或底部安全区上缘中最靠上的实际可见边界作为应用内容下缘。底栏固定 56 pt，贴底部安全区上缘。终端辅助键与终端可用区下缘相距 12 pt，终端内容框与辅助键区相距 8 pt。宽度按左右边距与列间距适配，小于 360 pt 用 16 pt 边距与两行辅助键。两套参考尺寸可以逐项直接核对，其他设备遵守这些关系、控件尺寸和阅读顺序。
4. 更短的屏幕、系统放大字体或较高的 IME 使用应用内容区纵向滚动。标题、安全区与 IME 上缘共同划定内容边界。字段获焦后滚动至可见，按钮仍可滚到并触达。指纹审查先展示目标和完整指纹，再到确认与取消。活动终端在 IME 上方保留终端与辅助键可用区，空间不足时终端内容可滚动，键盘切换与断开仍可命中。正常页面没有弹出的系统键盘图层；画板中键盘内部仅作位置示意。
5. 视觉检查另核对字号、语义颜色、圆角、1 pt 分隔线、长文完整性和是否互相遮挡。矢量稿用中文系统回退字体预览，终端工程字形以[仓库等宽字体](../../validation/shared/fonts/JetBrainsMonoNerdFontMono-Regular.ttf)为准。由于字形栅格化和系统输入法外观随设备变化，比较应用控件与排版，不逐像素比较字形抗锯齿。

每壳按相同顺序关联脱敏截图、相应画板 ID、设备与安全区、差值、触控范围和行为结果。缺少截图、坐标或可命中证据的条目保留未验。功能证据沿用 [docs/63](../../docs/63-design-parity-and-direct-ssh.md) 中的服务端独立认证、PTY、回显和关闭记录。离线 SVG 的渲染和几何检查属于设计稿验证。

## 产品验收索引

[2026-11-18 本地验收记录](../evidence/direct-ssh-mobile-20261118/README.md)提供固定画板对应的两壳 15 状态前测，以及空首页、接入选择两种尺寸的修前／修后图和逐锚实测。首批两页的 52 项应用锚点达到 2 pt 阈值。其余 13 页保留前测及待修状态，原生设备证据单独认定。
