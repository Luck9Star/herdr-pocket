# Linux 配对与系统密钥环 · 2026-11-20

源码基线为 `07fd0c99`，合入前的主分支为 `b8651f73`。此前 Flutter Linux 的设备配对入口禁用，Tauri Linux 使用明确标示的进程内测试身份，退出后旧句柄可能找不到密钥。本批两壳静态链接同一 Secret Service 桥。普通 SSH 手动凭据、三网络节点身份和 Windows 设备桥各有独立范围。[Flutter Linux runner](../../../validation/flutter/README.md) · [Tauri Linux 接线](../../../validation/tauri/src-tauri/build.rs) · [M0 降级表](../../60-m0-evidence-archive.md#3-降级行为清单)

## 使用边界

按已确认的使用范围，应用使用用户自行解锁的桌面会话 Secret Service。未安装、未配置、所需集合锁定或服务不可达时，停止读取、签名、新建或删除所需身份，保留主机资料和原句柄供核验。应用不会自行解锁、写入明文种子、换钥或以临时身份重试。本批测试使用一次性密钥环，未访问个人桌面密钥环。

- 新建只使用已解锁的默认集合。默认别名若解析到已知临时 `session` 集合，拒绝新建持久身份。读取、签名和删除原句柄查找所有集合，不随默认别名迁移。若集合锁定、查询失败或条目重复，不能把无法核实的引用判为不存在。
- Flutter 和 Tauri 分别用 `herdr-pocket.flutter`、`herdr-pocket.tauri`，并匹配用途和句柄。测试证明同服务上的应用级查找不会误取另一命名空间的句柄。二者仍在同一桌面 D-Bus 安全域，系统访问控制由密钥环提供。应用命名空间、独立测试总线和 Linux 网络命名空间分别记录，均不代表独立系统用户之间的访问控制已经验收。
- 两壳先持久保留句柄，再发一次创建。结果未知时保留原记录，禁止自动重发和生成替代身份。Flutter 对旧待确认记录只读核验原公钥，保留待确认状态。Tauri 可由用户审查同一主机与目标后，用原句柄和公钥恢复请求并提交公开目录记录。显式删除原身份另走用户审查；本机删除不会撤销主机授权。两壳的公开目录和待确认状态均不写入私钥种子。[共享查找与写入](../../../validation/linux-secure-identity/src/lib.rs) · [Flutter 待确认入口](../../../validation/flutter/lib/host_catalog_page.dart) · [Tauri 恢复入口](../../../validation/tauri/src-tauri/src/lib.rs)

## 本机证据

| 验证层 | 已核对 | 范围 |
| --- | --- | --- |
| Flutter Linux ARM64 原生桥 | `0d5e74d2` 的生成 GTK runner 在隔离 Ubuntu ARM64 用 CMake 3.28.3、Ninja、Flutter 3.47.9 与真实 Rust 静态库链接。私有 GNOME 服务上验证跨进程原句柄复用、签名和锁定后的拒绝，目录摘要保持一致。 | 临时入口操作实际原生通道。早轮构建用来证明桥接，不给最终软件包或完整首页配对与 SSH 作结论。 |
| 共享 Secret Service，`2a89f0e9` | Linux ARM64、Rust 1.96.0。专用 GNOME Keyring 主程序 2 项通过，内部再启动 1 个子进程用原句柄验签。真实测试还验证客户端命名空间、默认别名切换后查找与删除、临时集合拒绝新建、锁定时读取和删除失败。无服务另跑 4 项库测试。 | 子进程是共享库验签见证，已包含在私有服务测试内。GNOME 服务和总线均为一次性。四份源码摘要与下方回执可逐一复核。 |
| 客户端回归 | `e5c3baf2` 的 Flutter 22 项通过，Tauri Linux 的 JS 套件 734 项通过，Flutter 打包脚本 11 项通过，Debian 夹具两项通过。另在 Linux ARM64 执行 Flutter 的 C++ 目录文件和进程锁测试，两项通过。 | Widget／JS 使用模拟通道和公开夹具。C++ 测试验证子进程竞争同一目录文件锁。Linux 两壳的许可与修改声明已用实际 CMake 安装和 Tauri Debian 打包器做字节比对，使用最小夹具。完整 Flutter 产品重启、签名软件包和桌面布局另验。 |
| Tauri ARM64 R8 定位记录 | 产品 `59892bac`，驱动 `4b15cb63`。正常、锁定、服务消失三份原报告已按归档 SHA-256 回查。本机包装器调用仅供 CI 的入口，填入仿形 GitHub 运行信息。报告宣称 x86_64，容器实际为 ARM64。 | 保留原脱敏记录，三轮只供定位。正常双进程以本页官方单主机作业为准，锁定与服务消失的桌面双进程正式负例待验。 |

[GNOME 脱敏回执](private-service-receipt.json) · [Tauri R8 脱敏回执](tauri-stock-restart-receipt.json) · [随包署名](../../../THIRD_PARTY_NOTICES.md) · [归档校验和](SHA256SUMS)

## 官方运行 R1

本节五次运行均为 `75df6463c7784899f5661cc4e43cc72eab89596d`、第 1 次尝试。回执保留五次运行的 job ID 和结论、九个 ZIP 的工件 ID 与 GitHub SHA-256。原 ZIP 逐一核对官方摘要、CRC 和内附校验表的列出项。仓库保留脱敏字段，原图、运行日志和安装包从各运行原工件查阅。 [R1 脱敏回执](official-r1-receipt.json) · [归档校验和](SHA256SUMS)

### Linux 单主机配对

Ubuntu 24.04 x86_64、一次性 GNOME Secret Service、回环 OpenSSH 9.6p1 与 herdr 0.9.5。两端都从审核配对进入选定窗格，用密钥环中的同一公钥完成 sshd 认证、显示 full/delta 观察帧、停止后标记陈旧画面。两端终端输入均为 0 字节，撤销临时主机授权并清理一次性进程和密钥。 [单主机运行](https://github.com/Luck9Star/herdr-pocket/actions/runs/44672493040)

- Flutter 3.47.9 以 `integration_test` 驱动真实 Linux GTK runner。原生目录读回、暂停及同连接继续通过，共 8 帧，其中 6 个 delta。该作业没有第二个独立 Flutter 应用进程。 [Flutter job](https://github.com/Luck9Star/herdr-pocket/actions/runs/44672493040/job/136076474580)
- Tauri 使用两个独立原生 GTK/WebView 应用进程。第一进程退出并释放目录锁，第二进程复用同一私有会话、同一已存主机与目标，以原密钥重新认证。sshd 恰有两次认证，两条连接均关闭。第二进程收到 1 次 full、2 次 delta，期间没有密钥环写入，原公钥与授权保持一致。 [Tauri job](https://github.com/Luck9Star/herdr-pocket/actions/runs/44672493040/job/136076474081)

### Linux 双主机 S06 R1

两端作业均失败，仍记录终端输入 0 字节及夹具撤销、清理。本轮停在焦点和布局路径，后续同范围复验见 R2。 [双主机 R1](https://github.com/Luck9Star/herdr-pocket/actions/runs/44672498778)

- Flutter 在重新等待分屏恢复时退出，固定错误码 `s06_widget_exited_before_focused_close_s06_split_resume`。当时只有一个标签可见，A 的观察以 `cancelled` 结束，B 仍持续收帧，未到达焦点侧关闭断言。 [Flutter job](https://github.com/Luck9Star/herdr-pocket/actions/runs/44672498778/job/136076491061)
- Tauri 已取得双侧原生画面和分屏几何，焦点操作返回 `s06_tauri_input_focus_webdriver_click_stale_element_reference`。首轮回执未定位到该阶段的具体点击。后续本机 GTK 夹具在节点替换时复现旧错误，`bee84cab` 只在确知点击未派发时重定位一次。正式双主机复验见 R2。 [Tauri job](https://github.com/Luck9Star/herdr-pocket/actions/runs/44672498778/job/136076490769)

### 五端构建与 Linux 包内许可

| 工作流 | 作业范围与结果 |
| --- | --- |
| Flutter 原始依赖对照 | Linux x86_64 debug tar 构建成功。未打补丁的 `terminal_view` 0.5.0 保留缓冲区组合字符，但基础字与组合字的非透明像素均为 138，诊断失败，整个工作流为红。 [Linux build](https://github.com/Luck9Star/herdr-pocket/actions/runs/44672504764/job/136078278147) · [对照诊断](https://github.com/Luck9Star/herdr-pocket/actions/runs/44672504764/job/136078278165) |
| Flutter 实验候选 | 同一提交应用 `terminal_view` 0.5.0 实验补丁第 2 版，补丁检查、macOS 渲染及 Android、iOS、macOS、Linux、Windows 构建共 7 个 job 全绿。Ubuntu 的组合字符渲染探针为 138→169。应用包为开发测试制品。 [候选矩阵](https://github.com/Luck9Star/herdr-pocket/actions/runs/44673360914) · [候选 Linux build](https://github.com/Luck9Star/herdr-pocket/actions/runs/44673360914/job/136081274539) |
| Tauri 验证包 | Android、iOS 模拟器、iOS 设备目标、macOS、Linux、Windows 共 6 个 job 全绿。Android 为临时 debug 签名，iOS 设备目标为无签名构建，Linux 生成 amd64 Debian 测试包。 [Tauri 矩阵](https://github.com/Luck9Star/herdr-pocket/actions/runs/44672510155) · [Linux build](https://github.com/Luck9Star/herdr-pocket/actions/runs/44672510155/job/136076535159) |

直接读回 Flutter 两个 tar 和 Tauri Debian 包的 `LICENSE-APACHE`、`LICENSE-MIT`、`UPSTREAM`，分别与同一源码的 vendored Secret Service 5.1.0 三份文件及包清单摘要比对。R1 的外侧诊断仍有旧 Python 工具和字节码，Tauri 浏览器预览也含旧工具。`2c720887` 迁移校验器，`37e2d4a9` 排除来源目录的旧字节码。R2 正式定向复验这两个修正。五端构建待另验生产签名、安装运行、实体设备、物理输入法、实际跨网和用户环境中的其他密钥环。 [R1 Linux 包摘要与路径](official-r1-receipt.json)

## 官方运行 R2

下列四个运行的源码均为 `1abdfe4425b667dbb23311870338df9b299d91fb`、第 1 次尝试。已将六个 ZIP 与 GitHub 的 SHA-256 比对，校验 CRC 和内附校验表列出的文件。回执保留作业、工件、Linux 包和三张原图的摘要。 [R2 脱敏回执](official-r2-receipt.json) · [归档校验和](SHA256SUMS)

### Linux 双主机 S06 R2

Ubuntu 24.04 x86_64，两端私有 Secret Service 的两把设备公钥均与各自回环 OpenSSH 认证匹配。同名 pane 的两个 terminal 分别推进。两端只读运行的对端输入分别为 0／0 字节，两个远端 PTY 均无尺寸变化，夹具授权、进程和密钥清理完成。 [双主机 R2](https://github.com/Luck9Star/herdr-pocket/actions/runs/44677046419)

- Flutter 由 `integration_test` 驱动真实 GTK runner 与原生目录。关闭焦点标签时，先确认原 SSH 已关闭，另一侧继续在原连接收帧。随后主动停止幸存侧，退出驱动前及退出后均确认两侧关闭。两侧共 10／14 帧，各连接一次。此次没有独立程序重启、原生窗口宽度往返或像素验收。 [Flutter job](https://github.com/Luck9Star/herdr-pocket/actions/runs/44677046419/job/136091248572)
- Tauri 通过原生 GTK/WebView 走完 1440→700→1440。原目标、左右位置和选中输入侧保持。布局暂停的副侧在回宽后在原连接显示新完整帧，手动暂停的观察在回宽后仍须主动恢复。DOM 焦点采样为 B、面板外、面板外。随后分别用界面关闭 A、B，关闭 A 时 B 仍在线，退出驱动前两端各认证一次、各关闭一次、均无 reset，两个原 socket 均消失。 [Tauri job](https://github.com/Luck9Star/herdr-pocket/actions/runs/44677046419/job/136091248786) · [原始工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44677046419/artifacts/14602811287)

| Tauri 原图 | 像素尺寸 | 画面 |
| --- | --- | --- |
| [收窄](s06-tauri-resize-narrow.png) | 700 × 1200 | B 保持观察，另一侧显示已暂停。 |
| [回宽恢复](s06-tauri-resize-wide-restored.png) | 1440 × 1200 | 原左右面板各自显示观察画面。 |
| [手动暂停回宽](s06-tauri-resize-manual-paused.png) | 1440 × 1200 | 停在旧画面，选中侧显示主动恢复按钮。 |

三张 PNG 保留原 ZIP 字节。画面仅含隔离终端样本、测试窗格标识和界面。受保护输入、物理输入法、实际跨网及其他密钥环由独立场景取证。

### Flutter 外部驱动单主机

首次正式外部驱动的 Flutter GTK 作业完成明确授权及同钥 SSH 认证，随后以 `stock_flutter_observation_pixels_missing` 结束。工件未留下窗口原图或第二进程验收回执，临时授权已撤销，专用进程和密钥已清理。此处只记录像素检查断点。 [外部驱动作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44677046387/job/136091247782) · [原始工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44677046387/artifacts/14603410208)

### Linux 测试包定向复验

Flutter 实验候选通过 Ubuntu 补丁与锁定检查，安全测试 696 通过、43 跳过，渲染回归 10 通过，随后生成 Linux debug tar。Tauri 生成 Linux amd64 Debian 测试包。两个包内的两份许可与 `UPSTREAM` 均与同一源码逐字节一致。两份外侧 `shared/` 和 Tauri 浏览器预览的 59 个共享资产均与源码一致，且无迁走的校验脚本、`__pycache__` 或 `.pyc`。R2 只复验 Linux 构建产物，R1 记录原五端矩阵。 [Flutter 候选 Linux job](https://github.com/Luck9Star/herdr-pocket/actions/runs/44677046405/job/136092777380) · [Flutter 候选检查](https://github.com/Luck9Star/herdr-pocket/actions/runs/44677046405/job/136091246849) · [Tauri Linux job](https://github.com/Luck9Star/herdr-pocket/actions/runs/44677046240/job/136091246844)

## 复跑与回滚依据

在隔离 Linux 用户环境准备 Rust 1.96.0、Python 3、`dbus-run-session`、`gdbus` 与 GNOME Keyring。命令显式使用测试目录和一次性密钥环，无须解锁个人密钥环。先将下列 SHA 导出到新目录，保留已存在的工作树和任何待确认记录。

```sh
set -eu
dir=$(mktemp -d)
git archive 2a89f0e9c8c06b6dd96a525dd96d5850c4ea8683 validation/linux-secure-identity validation/remote-harness/linux_pairing_keyring.py | tar -x -C "$dir"
cd "$dir"
cargo_bin=$(rustup which --toolchain 1.96.0 cargo)
RUSTC=$(rustup which --toolchain 1.96.0 rustc)
export RUSTC CARGO_TARGET_DIR="$dir/target"
python3 validation/remote-harness/linux_pairing_keyring.py -- "$cargo_bin" test --locked --manifest-path validation/linux-secure-identity/Cargo.toml --test private_service -- --nocapture
HP_TEST_NO_SERVICE=1 DBUS_SESSION_BUS_ADDRESS="unix:path=$dir/no-service" "$cargo_bin" test --locked --manifest-path validation/linux-secure-identity/Cargo.toml --lib
```

在归档目录先用 `shasum -a 256 -c SHA256SUMS` 核对回执，再对照 `private-service-receipt.json` 的四个源码摘要。Flutter C++ 进程锁测试从 Linux runner 的 [源码](../../../validation/flutter/native/linux/host_catalog_file.cc) 和 [测试目录](../../../validation/flutter/native/linux/tests) 编译，使用 C++17 与 `pkg-config --cflags --libs glib-2.0`。Flutter 22 项从已生成的 `e5c3baf2` 隔离工程运行 `flutter test --no-pub --reporter expanded test/linux_pairing_store_test.dart test/macos_secure_credential_field_test.dart test/pairing_gui_test.dart test/device_keys_test.dart`。

官方 ZIP 可在保留期内按回执的 artifact ID 从 Actions 下载，通过 `gh api repos/Luck9Star/herdr-pocket/actions/artifacts/<id>/zip` 取原件后与 `zipSha256` 比对。有权调度时，使用正式工作流在私有总线上运行。软件包报告需读回 `linuxPackagedNotices`，配对报告需核对界面公钥、密钥环条目与 sshd 认证是否同一。R8 只保留供定位的构建和驱动 SHA。 [Linux 单／双主机与两套基础包入口](../../../validation/remote-harness/README.md) · [R8 驱动](https://github.com/Luck9Star/herdr-pocket/blob/4b15cb630b3706fc983169ad2460ba94bc8b9f87/validation/remote-harness/tauri_linux_pairing_restart.py)

回滚对照用 `b8651f73`，在新的隔离检出与一次性目录验证。旧版 Flutter Linux 无法恢复本批设备身份，旧版 Tauri Linux 的临时身份也无法替代持久句柄。回滚代码时保留原公开目录、待确认记录及密钥环；不把不可读记录当成空目录，不重新生成或删除原密钥。
