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
| Tauri ARM64 原生双启动 R8 | 产品 `59892bac`，驱动 `4b15cb63`。两个独立的原生 GTK 应用进程在同一私有会话以原公钥各认证一次。第二进程获得 1 次 full、1 次 delta，接收端终端输入共 0 字节。重启段无密钥环写入，原主机、密钥和授权不变。另两轮锁定、服务消失均保持原记录，没有第二次 SSH 认证。 | 真实原生开发构建、暂用 GNOME 总线、受控 OpenSSH 与 herdr 0.9.5。属于本机只读配对证据，保持原源版本和驱动版本。 |
| 官方 Linux 配对与软件包 | 已以 `75df6463` 调度，初录暂无正式回执。 | 分别验正式包、原生布局、配对审核后的 OpenSSH 实际认证和 herdr 单主机／双主机只读观察。实体设备、用户现有 GNOME／KWallet 配置及真实跨网另验。 |

[GNOME 脱敏回执](private-service-receipt.json) · [Tauri R8 脱敏回执](tauri-stock-restart-receipt.json) · [随包署名](../../../THIRD_PARTY_NOTICES.md) · [归档校验和](SHA256SUMS)

官方调度按各自运行核对。 [双端单主机](https://github.com/Luck9Star/herdr-pocket/actions/runs/44672493040) · [双端 S06](https://github.com/Luck9Star/herdr-pocket/actions/runs/44672498778) · [Flutter Linux 打包](https://github.com/Luck9Star/herdr-pocket/actions/runs/44672504764) · [Tauri 打包矩阵](https://github.com/Luck9Star/herdr-pocket/actions/runs/44672510155)

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

在归档目录先用 `shasum -a 256 -c SHA256SUMS` 核对回执，再对照 `private-service-receipt.json` 的四个源码摘要。Flutter C++ 进程锁测试从 Linux runner 的 [源码](../../../validation/flutter/native/linux/host_catalog_file.cc) 和 [测试目录](../../../validation/flutter/native/linux/tests) 编译，使用 C++17 与 `pkg-config --cflags --libs glib-2.0`。Flutter 22 项从已生成的 `e5c3baf2` 隔离工程运行 `flutter test --no-pub --reporter expanded test/linux_pairing_store_test.dart test/macos_secure_credential_field_test.dart test/pairing_gui_test.dart test/device_keys_test.dart`。有权调度时，分别使用 [Linux 单／双主机和两套软件包入口](../../../validation/remote-harness/README.md)。软件包报告需读回 `linuxPackagedNotices`，配对报告需核对界面公钥、密钥环条目与 sshd 认证是否同一。Tauri 双启动 R8 保留独立的构建和驱动 SHA，复跑应在新的临时应用目录和私有总线上使用同一对源码。 [R8 驱动](https://github.com/Luck9Star/herdr-pocket/blob/4b15cb630b3706fc983169ad2460ba94bc8b9f87/validation/remote-harness/tauri_linux_pairing_restart.py)

回滚对照用 `b8651f73`，在新的隔离检出与一次性目录验证。旧版 Flutter Linux 无法恢复本批设备身份，旧版 Tauri Linux 的临时身份也无法替代持久句柄。回滚代码时保留原公开目录、待确认记录及密钥环；不把不可读记录当成空目录，不重新生成或删除原密钥。
