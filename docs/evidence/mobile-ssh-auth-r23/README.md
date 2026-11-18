# 普通 SSH R22/R23 可复核证据

[R22 Actions 记录](r22-actions.json)保存两份原 ZIP 及内部结果文件的重算 SHA256、显式通过项和 iOS 两次尝试的四个零步骤作业。R23 [应用锚点逐项矩形](geometry.json)、[截图来源与哈希](screens.json)和[校验和](SHA256SUMS)来自独立本地引擎。完整背景、停止点与恢复步骤见[验收快照](../../72-mobile-ssh-auth-snapshot.md)。

## R23 四对同尺寸对照

每对为同一操作阶段的修前、修后视口。旧版核对在同页内进行，Tauri 的修前指纹图保留滚动到同页指纹区的状态。画面中的回环地址、账号和指纹均属一次性夹具。归档保持原像素尺寸及图像数据，移除 PNG 文本与 EXIF 元数据，并分别记录源图与归档图哈希。 Flutter 锁定的布局采样先于边缘返回修复 `3fdd11b`，该修复只改变返回时机与相关测试。Widget 手势结果独立记录。

| 壳与视口 | 操作阶段 | 修前 | 修后 |
| --- | --- | --- | --- |
| Flutter 320×640 | 换钥阻断 | [旧换钥页](screens/flutter-key-changed-320-before.png) | [新换钥页](screens/flutter-key-changed-320-after.png) |
| Flutter 390×844 | 断开后保留目标 | [旧表单](screens/flutter-disconnected-390-before.png) | [断开反馈与返回](screens/flutter-disconnected-390-after.png) |
| Tauri 320×640 | 首次核验 | [滚动后的同页核验](screens/tauri-trust-320-before.png) | [独立公钥核对](screens/tauri-trust-320-after.png) |
| Tauri 390×844 | 断开后保留目标 | [旧表单](screens/tauri-disconnected-390-before.png) | [断开反馈与返回](screens/tauri-disconnected-390-after.png) |

## 量测口径

两档参考视口对应上／下安全区 24/24 与 47/34 pt，各按 DPR 1 采样。矩形顺序为 x、y、宽、高，差值按实测减设计。Flutter 的全宽 AppBar 囊括模拟顶部安全区，归档只将有原始尺寸的 AppBar 按设计内容带扣除顶部模拟值。其他源未量的锚点存为 `null`。每个展示行保留原始中心命中结果。禁用按钮的启用状态由另行实点或语义检查判定，因此矩形阈值与命中／启用结果各自读取。

| 壳 | 可比矩形 | ≤2 pt | 源未量 | 最大单项差 |
| --- | ---: | ---: | ---: | ---: |
| Flutter Widget | 140 | 140 | 18 | 2 pt |
| Tauri WebKit | 158 | 158 | 0 | 1 pt |

Flutter 遗漏的 18 项由两尺寸下 9 个相同锚点构成，涉及独立核对提示、认证成功提示以及部分换钥和重探页头数据。源未量只表示缺该矩形数据。两壳按目标、聚焦目标、核对、密码、私钥、换钥、保旧、重探、断开、返回逐状态保留余下数值。系统键盘外框来自模拟，系统状态栏及手势条不计入上表。可用 [PR #4 画板生成源](https://github.com/Luck9Star/herdr-pocket/blob/79deef0e9c03425f368966e32ff1f1d399a3ac02/design/penpot/direct-ssh-mobile.mjs)复算设计矩形。

从本目录运行 `shasum -a 256 -c SHA256SUMS` 校验归档文件。
