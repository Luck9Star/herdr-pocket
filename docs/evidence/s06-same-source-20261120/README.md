# S06 同源双端 guarded 双真实回环证据（2026-11-20）

正式行动 [44583986909](https://github.com/Luck9Star/herdr-pocket/actions/runs/44583986909)（attempt 1，conclusion `success`）在同一提交 `c5aa64a0c9703d0494f5694ec0028018f7f2a0b8`（分支 `codex/ordinary-ssh-desktop-ui-r3`，提交说明 *Integrate the Flutter and Tauri host-board pairing entry checks*）上并行完成两个 S06 `S06-two-real-ssh-herdr-targets` 作业：

- [paired-observe (flutter) 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44583986909/job/135775045118)：Ubuntu 24.04（`20261111.127.1`），Flutter Widget，显式测试签名器、目录与输入日志（`scope: Flutter widget with explicit test signer, catalog and input journal`）。
- [paired-observe (tauri) 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44583986909/job/135775044971)：同镜像，原生 Linux GTK WebView，进程内测试身份（`scope: Linux GTK WebView with native process-memory test identity`）。

两份 manifest 的 `status` 均为 `passed`，`sourceSHA` 均等于 `c5aa64a0c9703d0494f5694ec0028018f7f2a0b8`，`fixtureSharedBetweenAdapters` 均为 `false`（两适配器各自独立夹具），`remote-contract.json` 逐字节一致（两侧 SHA256 相同）。herdr 验证二进制同源：upstream `2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01` + 补丁 SHA256 `7f89a79677a456f024bd73555130861cd1b0b47e9d4d69f98d4e18ffc7f1ed8a`，dev 构建，`binarySHA256` `8cb39663b4e466006ffb0d68b5efe5be61701446b6c9877bf84cce2c0f762dbc`，`readinessAndCapabilitySmokePassed=true`。OpenSSH `9.6p1 Ubuntu-3ubuntu13.20, OpenSSL 3.0.13`。

## 两端共同核验事实（guarded 受保护输入模式）

- 首页正常、两条已审查身份、相同 pane ID 解析为不同终端（`samePaneDifferentTerminal`）、两侧均可见且帧独立推进。
- 单一输入焦点；切走焦点不恢复旧输入模式；迟到输入被拒（`lateInputRejected`）。
- 服务端实际收字节两端一致：A 侧 9 字节、B 侧 1 字节（`peerInputBytes [9,1]`，`exactRemoteBytes=true`）。
- 每侧恰好 1 次连接、1 次设备公钥认证（`peerAuthenticationCounts [1,1]`、`matchedDeviceKeyInSshd`、`distinctAuthenticatedDeviceKeys`）；目标绑定保持。
- 驱动退出前两侧 peer 均确认关闭（tauri `peersClosedBeforeDriverExit`；`s06-tauri-peer-close.json` 记录 before/final/steps 三段，final 两条 `recognizedCloseCount=1`、socket `absent`、0 reset）。
- 共享 PTY 数值记录：0 次尺寸变化（119×40 保持）、0 读错/捕获错、`winchHandlers=0`；Flutter 采样 630 次/31.6 s，Tauri 1719 次/86.3 s（`maxSampleGapMs` 61/85）。
- 清理四项全真：owned 进程停止、临时密钥移除、未触碰用户授权文件、无原始日志上传；`revokedFixtureKeys=true`。
- `physicalImeVerified=false`；`unverified` 明确列出：物理手机、摄像头、真实输入法、overlay 网络、像素渲染、硬件密钥保护、生产部署、受保护系统密钥库运行时。

## Flutter 侧（Widget）

帧证据为 `Terminal.write` 后的 Widget 状态：A 12 帧（增量 10）、B 16 帧（增量 15），两侧各 1 次连接并接受输入。第二条共享 PTY 数值记录同样 0 resize（623 样本/31.3 s）。

## Tauri 侧（原生 Linux GTK）

帧证据为公开可见终端文本 UI 快照 + 原生 WebDriver 动作。另含三项 guarded 直接输入探针（`frameEvidence: xterm parser callback after consuming a frame`）：

- `s06-tauri-first-direct-key.json`：首枚受保护真实按键前/后状态——B 处于 direct 模式、编辑器聚焦可写，A 只读；`keydown` 事件 `trustedOriginal=1`、`preventedAtEditor=1`、无合成输入（`beforeinput/composition` 全 0），按键落在原 B 编辑器。
- `s06-tauri-direct-escape.json`：受信任 Esc 组合键被消费、DOM 焦点移到 A、选中目标仍为 B、原目标与 peer 保持、双端只读、无额外输入字节。
- `s06-tauri-direct-resize.json`：1440→700→1440 窗口往返（viewport 同步变化）；布局暂停 A 并以同目标新帧恢复（`aFixtureTicks 313→338`），原编辑器焦点与输入状态、目标与回执、面板列数、peer 认证计数（[1,1]）均保持；DOM 焦点全程 `panel-b`。
- `s06-tauri-connected.png`：1440×1200 连接态截图（像素比 1，未缩放）。
- `gtk-fonts.txt`：fontconfig 2.15.0、fonts-noto-cjk `20230817`，Noto Sans CJK SC Regular/Mono。
- `s06-tauri-panel-geometry.json` / `s06-tauri-xvfb-pointer.json`：面板几何与 Xvfb 指针停靠记录。

## 归档文件

| 文件 | 说明 | SHA256 |
| --- | --- | --- |
| [s06-same-source-flutter.zip](s06-same-source-flutter.zip) | 官方原件（run 44583986909 flutter 工件，含 pubspec/Cargo lock） | `89d554b45d028e5e20f03823f9437a2cb880d3e52f27fe1a4c919688e9d06cbe` |
| [s06-same-source-tauri.zip](s06-same-source-tauri.zip) | 官方原件（run 44583986909 tauri 工件，含截图与探针 JSON） | `c0eb8d31532ec6771cff63dd31b11e482f334662377fa21c311f14ad0685fb5d` |
| [s06-same-source-flutter-manifest.json](s06-same-source-flutter-manifest.json) | 从上 ZIP 提取的脱敏 manifest | 见 [SHA256SUMS](SHA256SUMS) |
| [s06-same-source-tauri-manifest.json](s06-same-source-tauri-manifest.json) | 从上 ZIP 提取的脱敏 manifest | 见 [SHA256SUMS](SHA256SUMS) |

校验命令：

```sh
cd docs/evidence/s06-same-source-20261120
shasum -a 256 -c SHA256SUMS
unzip -t s06-same-source-flutter.zip
unzip -t s06-same-source-tauri.zip
```

## 边界

- 真机、真实跨网、系统输入法、物理键盘、像素级渲染、平台密钥库与生产部署均未验证（`physicalImeVerified=false` 及 `unverified` 列表）。
- Flutter 帧证据是 Widget 状态（`Terminal.write` 后），非像素渲染；Tauri 帧证据是公开可见终端文本快照 + 原生 WebDriver。
- 本归档只记录该同源双端通过事实，不改写此前分源 stock/guarded 结论；历史 S06 运行范围见 [docs/74 运行表](../../74-desktop-split-resize.md)。
