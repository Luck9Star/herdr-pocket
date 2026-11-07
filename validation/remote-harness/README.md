# 手机优先 M1a／M1b：两条真实只读适配器对照

此目录把 Flutter/DartSSH2 与 Tauri/russh 所用适配代码放进同一个临时 OpenSSH + herdr 目标验证。它不是 UI 自动点击或手机运行证据；工作流结果、源码 SHA 和下载 manifest 必须对应后，才能记实际通过。

当前 M1b：资料审查／预期 host key → SSH 公钥认证 → streamlocal `session.snapshot` → 明确选择当前 pane → full/delta 连续只读 → 主动停止或显式再连。保留 M1a 首个 full 后关闭路径。远端输入、GUI 点击、扫码、安全存储、三网和手机 IME 不在本探针范围。

## 隔离边界

- `run-ci.py` 在 fixture 创建前检查 `GITHUB_ACTIONS=true`、数字 run ID 与 `refs/heads/codex/`。本机只运行下面的纯逻辑测试，不启动 sshd/herdr。
- 同一新建 `/tmp/hp-mobile-*` 包含临时 Ed25519 host/wrong/client keys、专用授权文件、独立 XDG 目录和两个命名 session。sshd 只监听 `127.0.0.1` 高端口，禁止 SSH PTY、密码／交互认证和 agent forwarding。它不读取或修改用户 `~/.ssh`、真实授权或组网身份。
- fixture setup 可创建自己的 herdr pane 并运行合成画面／输入计数器；这与两个只读客户端分开。客户端过程期间计数器必须仍在运行，接收字节必须保持 0。
- `herdrPath` 是校验过的真实二进制，不使用 wrapper 覆盖 XDG。客户端从已审查的命名 session socket 路径推导 XDG 根，并用 snapshot 里 pane 对应的 `terminal_id` 建立观察，不能以多个 session 都有 `w1:p1` 推断同一目标。
- 每个 CLI 配置只在私有临时目录保存，结束即删除。stdout/stderr 不上传；原始 sshd/herdr 日志只留临时目录。artifact 从严格的报告字段／类型白名单重建，不复制私钥、配置、远端文本或任意异常消息。
- 只终止本次记录的进程组、清除本次生成的 keys，不停止系统服务或递归删除用户目录。cleanup 状态单独报告。

## 同条件用例

两适配器依次使用同一 sshd、host key、合成 pane 内容与 80×24 目标，每条最多 60 秒。某条失败仍尝试其余用例，并增量保存结果。

| 用例 | 必须取得的实际证据 |
| --- | --- |
| positive | host key 比对、认证、snapshot 与 full 均真实完成 |
| wrong-pin | 实际 key 回调执行，匹配为 false，认证未开始；TCP 拒绝／超时不能通过 |
| missing-session | 有效 socket 返回 snapshot 后，错误 session 被拒绝，无 full；可以在绑定检查时拒绝，不能称已执行 observe |
| cross-session | 第二个真实 session 确有相同 pane ID，socket/session 错配仍被拒绝，不发布其他 session 的画面 |
| cancel | 实际 SSH 已完成 snapshot 后取消，无 full；开始前取消不能代替本项。迟到结果发布另由适配器单测检查 |
| reconnect | 显式再次执行 positive，取得新 full；输入计数仍为 0，没有自动重试或重放 |
| observe-positive | 同一连接至少3帧、至少1个delta后主动取消；必须确认cancelled |
| observe-cancel | 第一张full后主动取消，恰好1帧、0delta |
| observe-reconnect | 同一CLI显式调用两次观察，每次新full和delta，总计至少4帧、2delta、2连接 |

## 执行与产物

本机允许的轻量检查：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s validation/remote-harness -p 'test_*.py' -v
```

2026-10-30 首版 7 项 guard 测试通过，加入有限协议诊断后为 8 项全部通过；3 个 Python 文件语法解析通过。这些只证明隔离门禁和结果分类，不证明 SSH 用例已经执行。

云端工作流：[mobile-remote-validation.yml](../../.github/workflows/mobile-remote-validation.yml)。它使用 Rust 1.96.0 和已有固定 Flutter 3.47.9/c197ca5 来源，在 runner 构建两适配器。候选 terminal 包首次 hosted→path 转换按既有 `pub get` + `candidate.py verify-lock` 执行，除候选本体外不得漂移。源锁与实际阶段结果在编译失败时也上传，实际协议结果在 `probe/manifest.json`；缺失该文件表示未进入完整协议探针，不能算通过。

真实协议来源仍固定 herdr v0.9.5 / `2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01`，Linux x86_64 二进制 SHA256 `14d9e8bc8b4a9e0118d77c32266f76d461f09b40342eb23752960bd89f59929d`。新 workflow 保留 14 天测试 artifact，不创建 Release、不提交商店、不合并主分支。

2026-10-30 已按 Context7 `library OpenSSH` → `docs /openssh/openssh-portable` 核查 `AuthorizedKeysFile`、`AllowStreamLocalForwarding local`、`AllowTcpForwarding local` 与 `PermitTTY no`。依据[官方 sshd_config 文档](https://github.com/openssh/openssh-portable/blob/master/sshd_config.5)及 [streamlocal 服务端处理](https://github.com/openssh/openssh-portable/blob/master/serverloop.c)；固定 runner 的实际 OpenSSH 版本应随云端执行记录核对。

首轮实际 [41046472357](../../docs/evidence/mobile-remote/41046472357/README.md) 为 2/12 通过、10/12 失败；仅两端错误 pin 拒绝通过。后续增加 readiness snapshot 的 version/protocol 类型与受限值诊断、CLI 退出码和报告长度，仍不输出原始响应或错误。实际版本记录为 OpenSSH 9.6p1 Ubuntu-3ubuntu13.20。

第二轮 [41047398465](../../docs/evidence/mobile-remote/41047398465/README.md) 为 7/12 通过：Rust 6/6；Dart 仅错误 pin 通过，其余认证后、snapshot 前发生安全报告中的 `async_state_error`。真实 readiness 确认 tagged `result.snapshot` 与 0.9.5 / protocol 22。接收器 0 bytes，cleanup 通过；Dart 修复仍需后续实际 run。

第三轮 [41048094519](../../docs/evidence/mobile-remote/41048094519/README.md) 在源码 `d15da12` 上 **12/12 通过**，Rust、Dart 各 6/6；移除 Dart channel 的竞争 `flush()` 后，实际正向 full、snapshot 后取消和显式重连均通过。接收器 0 bytes，cleanup 通过；脱敏 artifact 的两层 SHA 已下载复核。这里的 reconnect 是新 CLI 调用，missing-session 是有效 socket 返回 snapshot 后的名称绑定拒绝；不外推到 GUI 连续恢复或真正不存在 socket 的观察命令。elapsedMs 包含进程启动／JIT，不作为公平性能排名。


M1b [run 41060251076](../../docs/evidence/mobile-observe/41060251076/README.md) 在源码 `73ce2f8` 上 **18/18 通过**，两路线各9项。full/delta来自同一个每200ms更新的合成终端；输入计数0、cleanup通过。新三项分别取得3/2、1/0、4/2张总帧/delta，最后一项连接数2。`bufferHighWaterBytes=2572` 只统计解码单帧，不能当SSH缓冲或全进程内存。当前10项harness guard检查通过；不是手机或GUI持续运行证明。


## 配对 GUI 与稳定目标写入的批次探针

[批次工作流](../../.github/workflows/batch-validation.yml)在同一源码提交上调用 GUI 探针。主机 helper 的真实代码只访问 runner 新建的临时 home；helper 审查通过的唯一公钥进入测试 sshd 的专用授权文件。实际 sshd 日志中的 Accepted publickey 必须与请求中的设备指纹匹配。原版 herdr 0.9.5 场景要求接收器记录0字节。扩展候选由固定源码及补丁单独构建，验来源与哈希后才允许运行；输入场景必须恰好收到显式确认的一笔 `Pocket测`，不附加回车。

Linux Tauri 用 WebKitWebDriver 驱动窗口，观测 xterm 写回调消费的 full/delta、停止后的陈旧状态。Flutter Widget 驱动产品配对页和同一适配器，使用明确注入的测试 signer／写入标记存储。Android Tauri 另建 API35 x86_64 临时模拟器，以 adb reverse 连接同一 runner 的 loopback sshd，驱动真实 WebView 和 AndroidKeyStore 签名路径。每个场景单独记录实际结果。构建脚本存在不等于设备结果。

WebDriver 测试采用官方 [Tauri 测试说明](https://v2.tauri.app/develop/tests/webdriver/)，固定 tauri-driver 2.1.0。Android AVD 使用[官方命令行工具](https://developer.android.com/studio/run/emulator-commandline)，记录实际 image/emulator revision，使用完成后关闭本次启动的 AVD。编译上游候选只在临时 checkout，不更新用户主机。

### Android 逐键、草稿与隐藏标签

`codex/batch/android-input-*` 集中运行两个手机候选。每条路线先在独立 API 35 AVD 中运行原版主机用例，必须收到零字节。受保护输入用例另开一次性 AVD，要求同时指定 `--android-guarded-input` 和 `--input-fixture`。runner 核对同一来源构建的二进制、固定上游 commit、补丁字节、能力自检和 SHA，再创建临时 host/helper。两种模式各自输出 manifest。

用户在已选 pane 上发送单个 `k`，编辑尚未发送的草稿 `Pocket测`，回到看板，再主动打开原标签、连接、取得该 pane 的新 full。只有再次预览并确认后才发送草稿。验收要求两笔请求 ID 不同、分别受理 1 和 9 字节，pane 与稳定 terminal ID 均匹配主机独立查询的快照。真实临时 PTY 最终须恰好收到 UTF-8 的 `kPocket测`（共 10 字节，无回车）。清理后再次核对内容，拒绝额外输入。产物仅保留数字、公开测试标识与清理状态。此流程覆盖模拟器 GUI 和隔离 SSH 链路，物理设备、真实中文输入法与组网状态需要另验。

## 在临时终端中操作真实 TUI

在仓库根目录运行以下命令。需要 POSIX、Python 3 的 curses、xterm-256color terminfo，以及对应候选已有的 Node 或 Dart。也可以通过 `--runtime` 指定该可执行文件。

```sh
python3 validation/remote-harness/phone_tui_probe.py tauri
python3 validation/remote-harness/phone_tui_probe.py flutter
```

每次运行新建 80×24 PTY 和临时结果文件。进入真实 curses 界面后，指定路线的生产编码器依次移动选中行、切换焦点、退格、插入和删除行、打开及关闭帮助、刷新，最后通过 F10 退出。JSON 中的 `passed` 同时要求十个动作按序发生、最终选中 Review、终端属性恢复及视口尺寸不变。

可用显式选定的 herdr 可执行文件检查观察帧。探针单独启动临时本地会话，核对首次全帧、四次模式变化、后续有序画面和共享 PTY 尺寸样本。普通 0.9.5 使用 `--expect stock`，含本仓库固定候选补丁的二进制使用 `--expect candidate`。此探针只读，SSH 和手机系统输入单独验收。

```sh
python3 validation/remote-harness/observer_mode_probe.py --binary /path/to/herdr --expect stock
```

## 配对手机操作同一远端 TUI

一次云批次可以在两个现有受保护输入模拟器任务中继续操作 curses。选择 `codex/network-batch/with-emulators-input-tui-*` 测试分支时，工作流向这两项传入 `--android-tui`、`--android-guarded-input` 和同一批构建的 `--input-fixture`。普通 0.9.5 场景继续验收零输入；每条路线沿用自己的已配对测试主机。候选二进制须附带与其 SHA-256 相符的模式探针结果，包含四次纯模式变化和有序的新画面。

原有逐键与草稿的两笔回执、10 字节接收记录通过后，测试主机在原 pane 的同一 PTY 中一次性启动 curses。手机核对当前目标的新全帧，经可见按键执行十个动作。十笔新回执必须来自原 pane 和稳定 terminal，且与先前两笔请求 ID 全部不同。看见选中行、焦点、详情、帮助与刷新次数依次变化后，以 F10 完成。主机独立校验程序动作、最终状态、终端属性和接收日志。网络超时或发送结果未知时不会重发。

报告中的 `tui` 是手机观察与回执，`hostTui` 是独立主机结果。`receivedInputBytes` 只计 curses 之前和之后的原始接收器字节，curses 阶段的按键另有十笔回执。后续撤销或清理失败时，整体仍失败，已经完成的主机状态可单独核查。局部 PTY 和浏览器检查、云模拟器、物理设备分别记录。
