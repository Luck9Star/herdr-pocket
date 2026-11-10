# M0 证据归档：依赖来源、可重跑步骤与降级行为

本文对应 [roadmap](04-roadmap.md) M0 三条未勾条目的证据归档（[04-roadmap.md:46-48](04-roadmap.md)）：关键依赖来源与未验证边界、可重放命令与通过/失败/未执行分记、能力缺失时的降级行为。按 [回填口径](04-roadmap.md)（五维度分记、证据分级），本文只归档证据，不改勾选状态；勾选由 roadmap 维护任务决定。

口径说明：

- 版本一律取自仓库锁文件或固定源 manifest；`核查日期` 取源文件内 `checked_at`/`asOf` 字段，无显式日期的取该文件 git 最后提交日（2026-11-10 查）。
- 许可证结论引用 [许可与分发审查](17-license-and-distribution-review.md)（下称 doc17），本文不复制其声明表，只记录证据视角（来源、版本、核查方式、边界）。
- 「未验证边界」= 该依赖什么没验过、为什么没验；参考项目采用某方案不代替本项目运行结果（[04-roadmap.md:50](04-roadmap.md)）。

## 1. 关键依赖证据归档表

### 1.1 GUI 框架与终端层

| 组件 | 版本或 commit | 来源 | 许可证 | 核查日期 | 核查方式 | 未验证边界 |
| --- | --- | --- | --- | --- | --- | --- |
| Flutter SDK | 3.47.9，源码 commit `c197ca5199e9ee5661e865596c9c07294dfab51c` | github.com/flutter/flutter（固定于 [ci.py:20](../validation/flutter/tool/ci.py)、[flutter/README.md:29](../validation/flutter/README.md)） | BSD-3-Clause | 2026-11-07（doc17 提交日） | LICENSE 链接与版本核对（doc17:25） | root 许可不覆盖 engine、第三方 C/C++、Dart runtime 与生成工程声明；须从实际 SDK/engine 构建输入汇总 |
| terminal_view | 0.5.0（pub.dev 归档 SHA-256 `5f8cf2e9…`，[pubspec.yaml:10](../validation/flutter/pubspec.yaml)） | pub.dev 官方归档 + 补丁 manifest | MIT（LICENSE sha `fa9c766d…`、NOTICE sha `c307f60f…`） | 2026-11-07 | 重新下载验 hash（doc17:26） | NOTICE 源自 xterm.dart 4.0.0 fork；ASCII 组合重音绘制缺陷已在 CI 复现（[09-prototype-validation.md:31](09-prototype-validation.md)），非数据丢失 |
| dartssh2 | 4.1.0（归档 SHA-256 `39359ace…`） | pub.dev（[pubspec.yaml:11](../validation/flutter/pubspec.yaml)） | MIT | 2026-11-07 | 归档 hash 复核 + `SSHIdentity.custom` 异步 signer 源码核对（[flutter/README.md:141](../validation/flutter/README.md)、doc17:27） | 真实设备 PEM 路径与硬件签名未验；私钥不进 Dart 仅是设计断言 |
| pointycastle / pinenacl / asn1lib | 4.0.0 / 0.6.0 / 1.5.8（[pubspec.lock:158](../validation/flutter/pubspec.lock) 等） | pub.dev 锁定 | MIT / MIT / BSD-3-Clause（remote-dependencies.json，doc17:27） | 2026-11-07 | 历史 hash 清单核对，本轮未重下（doc17:27 明示） | 历史 hash 记录不冒充本轮下载核验（doc17:27 原口径） |
| Tauri core / build / utils | 2.12.5 / 2.7.4 / 2.10.2 | crates.io，[src-tauri/Cargo.toml](../validation/tauri/src-tauri/Cargo.toml) + Cargo.lock | MIT OR Apache-2.0（doc17:35） | 2026-11-07 | Rust/npm 清单与 lock 固定、上游 Cargo.toml 对照（doc17:35） | 不能用 core 许可替全部 WebView/GUI 系统库背书；选用的许可分支、NOTICE 待逐项收集 |
| @tauri-apps/api / cli | 2.12.4（[package.json](../validation/tauri/package.json)，lock v3） | npm registry | 同上（doc17:35 一并记录） | 2026-11-07 | npm lock 固定 | 同上 |
| @xterm/xterm | 6.0.0（lock 固定） | npm registry | MIT（doc17:36） | 2026-11-07 | 固定版本 LICENSE 与本地安装包文本核对（doc17:36） | 打包 minified JS 仍须保留版权；现有 package 脚本未显式收集该文件 |
| @xterm/addon-unicode-graphemes | 0.4.0，来源提交 `f447274f430fd22513f6adbf9862d19524471c04` | npm registry（doc17:134） | MIT（独立版权信息） | 2026-11-07 | tarball SHA-512 与 npm lock 比对（doc17:134） | 上游标记实验性；grapheme 行为以实测为准 |
| vite | 8.3.5（devDependencies） | npm registry | 未确认（doc17 未单列，未另行核查） | — | 仅 lock 固定 | 许可证与声明收集未做 |

### 1.2 Rust crates（transport-rust / tauri / ssh / android-network-source 等 Cargo.toml 锁定）

| 组件 | 版本或 commit | 来源 | 许可证 | 核查日期 | 核查方式 | 未验证边界 |
| --- | --- | --- | --- | --- | --- | --- |
| russh | =0.65.0（`default-features=false, features=["ring"]`；本地 vendor 副本 [vendor/russh-0.65.0](../validation/vendor/russh-0.65.0)） | crates.io + 本机 registry 源码核对 | Apache-2.0（doc17:37） | 2026-11-08（transport Cargo.lock 提交日） | Context7 文档 + 固定 0.65.0 源码双查（[transport-rust/README.md:41](../validation/transport-rust/README.md)） | 不能照默认 feature 误报为已链接 aws-lc-rs；SSH RustCrypto/ssh-key 传递包声明未闭合 |
| ring | =0.17.14（crate SHA-256 `a4689e6c…`，doc17:38） | crates.io | Apache-2.0 **AND** ISC（复合，非二选一） | 2026-11-07 | crate 归档 hash 与两份 Rust lock 一致（doc17:38） | root LICENSE 指向 BoringSSL/other-bits/once_cell 等文本需实际收集，不能只放一份 Apache |
| tokio | =1.54.1（transport/tauri/ssh）；portable-stream 单独锁 =1.53.1 | crates.io | MIT/Apache 双许可主干（doc17:39 初步元数据） | 2026-11-07 | lock + registry 元数据抽查（doc17:39,41） | 初步元数据核对，非逐包全文复核 |
| serde / serde_json | =1.0.229 / =1.0.154 | crates.io | 同上 | 2026-11-07 | 同上 | 同上 |
| base64ct / zeroize / libc | =1.8.3 / =1.9.1 / 0.2.191（doc17:39） | crates.io | MIT/Apache/BSD 主干 | 2026-11-07 | 同上 | 同上 |
| jni | =0.21.1（android-network-source、flutter-network-runtime） | crates.io | 未确认（doc17 未单列） | — | 仅 lock 固定 | 许可证未核查 |
| lock 覆盖范围 | transport lock 180 条 / tauri lock 515 条 | — | — | 2026-11-07 | 本机 registry manifest 覆盖抽查（doc17:41） | 覆盖率≠运行时链接数；缺失包含 Windows/Linux GUI、WASM、Android 目标项，须各平台实际构建补齐（doc17:41） |

### 1.3 三网 native 候选与补丁（`validation/native/`）

| 组件 | 版本或 commit | 来源 | 许可证 | 核查日期 | 核查方式 | 未验证边界 |
| --- | --- | --- | --- | --- | --- | --- |
| tailscale tsnet | v1.104.1，commit `9a522a9786c97eb7910c01ccb7bd66557b04c910` | github.com/tailscale/tailscale（[tailscale-runtime-source.json](../validation/native/tailscale-runtime-source.json)） | BSD-3-Clause（doc17:49） | 2026-11-06 | go.mod/go.sum SHA-256 双记录（reference 与实际比对）+ LICENSE 核对 | Go 标准库、实际链接模块与原生输出声明未收集；仅编译/加载探针，未启动真实节点、未读真实身份（sources.json scope） |
| tsnet 补丁 | `patches/0002-tsnet-explicit-auth.patch` sha256 `29b70583…`；patched tsnet.go sha256 `86d45bde…` | 本仓库 patch + 固定源 | 本项目修改（doc17:109 要求保留归属） | 2026-11-06 | manifest 哈希闭环 + patch 测试 `tsnet-explicit-auth-test.go` | 补丁检查≠编译或运行通过（[flutter/README.md:87](../validation/flutter/README.md) 同口径） |
| heeler-overlay-natives（参考框架） | commit `6a2817fc02aeb552df251d9478753c22fd4738bb`（sources.lock 固定） | github.com/Ylarod/heeler-overlay-natives | root/多 glue Apache-2.0，**不覆盖 native/easytier 及子模块**（doc17:45） | 2026-11-06 | 固定 README+sources.lock 重读，未改用 main | LGPL/MPL 边界须逐子模块核对（doc17:43） |
| libzt | Ylarod fork commit `7e5d0f99a2de81c45faa28e44289bcd19d933bf2`（源 tar sha256 `ba9ade19…`） | github.com/Ylarod/libzt（[zerotier-runtime-source.json](../validation/native/zerotier-runtime-source.json)） | LICENSE.txt：Change Date 2026-01-01、Change License Apache-2.0（doc17:51） | 2026-11-07 | 固定版本 LICENSE 核对 | 转换判断仅覆盖该 Licensed Work，不扩展到 main/别的版本/全部子模块/商标（doc17:51） |
| ZeroTierOne core | gitlink `fc5c3ec22090b5b2a0f274e863651fe9ca489bf4`（1.16.2） | github.com/zerotier/ZeroTierOne | MPL-2.0，core 与 `nonfree/` 分开（doc17:52） | 2026-11-07 | root LICENSE + MPL 文本核对 | MPL 文件头/Exhibit B 排除未逐件检查，不能仅据 root MPL 认定全部可转许可（doc17:52） |
| lwIP / lwip-contrib | `32708c0a…` / `4fd612c9…` | github.com/joseph-henry/lwip(-contrib) | lwIP BSD 三条款；contrib root COPYING URL 404（doc17:54） | 2026-11-07 | COPYING 核对 | contrib 许可以实际采用文件头定位，未逐件复核（doc17:54） |
| libzt 上游补丁 0001–0004 | 独立 root sets / managed gateway routes / metrics saver / rebind defunct UDP（各 sha256 见 zerotier-runtime-source.json） | 本仓库 `patches/libzt/` | 本项目修改 | 2026-11-07 | manifest 哈希闭环 | 离线验证 only，无入网/真实身份（scope 声明） |
| ZeroTier 候选补丁 0008 | `0008-streams-and-hp-boundary.patch` 终版 911 行，sha256 `ba4654f9…`；BOUND_SYMBOLS 六元组符号契约 | `candidates/zerotier/patches/` + `zerotier-candidate.json` | 本项目修改（MPL 文件须可取得 Source Code Form） | 2026-11-09（docs/58 记录） | 三轮独立评审（B1 UAF/B2 ABBA 修复）+ 4055 项 libzt 测试全过 + CI run `42632587131` 全绿（[56-project-status-and-handoff.md:32](56-project-status-and-handoff.md)） | S5 真机物理网络入网与多机并发验收未做；系统 KeyStore 硬件隔离与真实拨号/SSH 链路未验（docs/56:32） |
| EasyTier engine | 开发提交 `728ba94b5029240add6204eed591f22e4e039e6b`（**非** 2.7.0 release） | github.com/EasyTier/EasyTier（managed-source-audit.json） | LGPLv3（doc17:48） | 2026-11-06 | 固定提交 LICENSE + 6 个关键源文件 sha256 静态审查（[managed-source-audit.json](../validation/native/managed-source-audit.json)，asOf 2026-11-06） | 仅静态源审查；management feature 被排除、IdentityUnavailable 无明文回退是源码结论，未跑更新版固定源 check/link/load（audit limits） |
| portable-stream（Heeler ABI） | managed-node 补丁 SHA-256 `98897e41…`（新增生命周期接口） | heeler native/easytier + 本项目 [portable-stream](../validation/native/portable-stream/Cargo.toml) | LGPL-3.0-or-later（doc17:48） | 2026-11-07 | 8/8 本地测试（rustc 1.96.0）+ reviewer 复跑（[portable-stream/README.md:26](../validation/native/portable-stream/README.md)） | GPL+LGPL 文本、对应源码/重链接材料未闭合（doc17:48）；历史桌面编译记录不覆盖此补丁版 |

### 1.4 配对与平台安全依赖

| 组件 | 版本或 commit | 来源 | 许可证 | 核查日期 | 核查方式 | 未验证边界 |
| --- | --- | --- | --- | --- | --- | --- |
| BouncyCastle | `org.bouncycastle:bcprov-jdk18on:1.86` | Maven + [pairing/sources.json](../validation/pairing/sources.json) | MIT（doc17:63） | 2026-11-05 | LICENSE 原文与仓库 notice 语义核对（HTML↔Markdown 不要求逐字） | 未证明硬件 Keystore 行为（doc17:63 原口径） |
| zxing 扫码 | `zxing-android-embedded:4.3.0` + `zxing core:3.5.3` | github journeyapps/zying（[pairing/native/camera/sources.json](../validation/pairing/native/camera/sources.json)） | 均 Apache-2.0（doc17:64） | 2026-11-05 | 固定 COPYING/LICENSE + artifact 来源追溯；APK 检查器强制唯一一份且 hash 一致 | — |
| pyca/cryptography | 46.0.3 | github.com/pyca/cryptography（pairing/sources.json） | Apache-2.0 OR BSD-3-Clause | 2026-11-05（checked_at） | 固定官方 46.0.3 文档双查（context7 + 官网） | fixture 公钥随机生成即弃，不对应用户身份（pairing/README.md:26） |
| Android KeyStore/KeyMint | API 35 模拟器（软件 KeyMint）；Keystore 线程自 `onCreate` 启动（commit `5959b0d`） | Android 平台 API | 平台条款 | 2026-11-08（docs/56 记录） | 不注册 JCE provider 的三个生产文件仪器化验证，CI 产物为准（[56-project-status-and-handoff.md:32](56-project-status-and-handoff.md)） | **模拟器软件 KeyMint 不构成硬件隔离结论**；硬件 KeyStore 隔离未做（docs/56:66 遗留台账） |
| Apple CryptoKit / Keychain | iOS 15 compile target / macOS SDK 26 本地编译；ThisDeviceOnly | Apple 平台 API | 平台条款 | 2026-11-05 | 官方 JSON 文档独立核对（pairing/sources.json apple 节） | 仅 memory backend 探针，系统 Keychain 未实例化；iPhone 签名安装、锁屏、重启未验（[15-mobile-gui-validation.md:42](15-mobile-gui-validation.md)） |
| herdr（协议对端） | 0.9.5 / 协议 22，固定 commit `2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01` | github.com/herdrdev/herdr（[transport-rust/README.md:45-47](../validation/transport-rust/README.md)；运行时校验 `--version`=herdr 0.9.5，[blocked_fixture_probe.py:61](../validation/remote-harness/blocked_fixture_probe.py)） | 未确认（doc17 未单列） | 2026-11-08 | CI 下载真实二进制并校验版本/协议号（blocked_fixture.py:79 断言 0.9.5+protocol 22） | 许可证未核查；仅 loopback 隔离 harness，用户主机未接入 |
| CI sshd（OpenSSH） | runner 自带，未锁版本 | GitHub runner 预装 | 未确认 | — | 查证 ssh-validation.yml 与 remote-harness README，无版本锁定记录 | 版本漂移未管控；隔离靠配置（127.0.0.1 高端口、禁 PTY/密码与交互认证/agent forwarding，[remote-harness/README.md:10-15](../validation/remote-harness/README.md)） |

### 1.5 工具链锁点与共享 fixture

| 组件 | 版本或 commit | 来源 | 许可证 | 核查日期 | 核查方式 | 未验证边界 |
| --- | --- | --- | --- | --- | --- | --- |
| 工具链三件 | go 1.27.1 / rust 1.95.0（CI）/ protoc 36.2（三平台 zip + sha256） | [native/sources.json](../validation/native/sources.json) | 各上游 | 2026-11-06 | sources.lock 固定 + 平台包哈希 | 本地 rustc 1.96.0 与 CI 1.95.0 并存（[portable-stream/README.md:26,28](../validation/native/portable-stream/README.md)），结果须绑定工具链 |
| Android NDK | 28.2.13676358 | [android-network-experiment.yml:207,342](../.github/workflows/android-network-experiment.yml) | 平台条款 | 2026-11-09 | workflow 固定路径 | 本机无 SDK，仅编译校验（docs/56:32） |
| 测试 Mac | Mac17,3 / arm64 / macOS 26.6.2 | [09-prototype-validation.md:26](09-prototype-validation.md) | — | 2026-10-30 | 构建记录绑定 | 当前 runner 版本未复核（2026-10-30 批次记录） |
| 终端字体 | JetBrainsMonoNerdFontMono-Regular.ttf（Nerd Fonts v3.4.0 / JetBrains Mono 2.304），fixture sha `f01031f4…` | [shared/fixture.json](../validation/shared/fixture.json) | OFL-1.1（JetBrains）+ Nerd Fonts 总许可（doc17:62） | 2026-11-07 | 与上游 v3.4.0 OFL 副本核对（doc17:62,84） | 所含 Codicons/FA/MDI 等 glyph 来源声明未逐件审清（doc17:84）；不能改标 GPL/AGPL 或单卖 |
| 共享 fixture | 80×24、ANSI/Unicode/负载文件 + SHA256SUMS | [shared/README.md](../validation/shared/README.md) | — | 2026-10-30 | 两路线同 fixture（docs/09:26） | 终端布局/内容区尺寸未完全校准，无性能胜负结论（docs/09:26） |

## 2. 可重跑命令清单

通用口径（沿用 [09](09-prototype-validation.md)/[15](15-mobile-gui-validation.md)）：每条命令按 **通过 / 失败 / 未执行** 三态分记；通过须绑定源码 commit 与环境（run 编号或本地记录）；云端/本机/设备结果分开计数，不互相替代（[04-roadmap.md:23-25](04-roadmap.md)）。

### 2.1 Python 纯逻辑测试（remote-harness）

- 用途：隔离门禁与结果分类的单测；不启动 sshd/herdr。
- 前置：仓库根目录，Python 3。
- 命令（[remote-harness/README.md:37](../validation/remote-harness/README.md)）：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s validation/remote-harness -p 'test_*.py' -v
```

- 预期产物：逐文件 OK/FAIL 清单。
- 记录口径：通过只证明门禁与分类逻辑，不证明 SSH 用例已执行（README:40）。
- 现状：2026-10-30 首版 7→8 项通过（README:40）；后续新增文件以最新一轮为准。

### 2.2 remote-harness CI 驱动（真实 sshd + herdr）

- 用途：两适配器对照的隔离 SSH/herdr 协议用例（positive/wrong-pin/missing-session/cross-session/cancel/reconnect/observe-*）。
- 前置：**仅 CI**——`run-ci.py` 在 fixture 创建前检查 `GITHUB_ACTIONS=true`、数字 run ID、`refs/heads/codex/` 分支（[README.md:9](../validation/remote-harness/README.md)）；本机禁止启动 sshd/herdr。
- 命令（CI 内实际形态，[mobile-remote-validation.yml:71](../.github/workflows/mobile-remote-validation.yml)）：

```sh
python3 validation/remote-harness/run-ci.py --flutter-app "$RUNNER_TEMP/flutter-remote-probe" --output "$RUNNER_TEMP/mobile-remote-artifacts/probe"
```

- 预期产物：白名单字段重建的 JSON 证据（不复制私钥/配置/远端文本，README:13-15）。
- 记录口径：逐用例通过/失败；artifact 14 天过期后须从 codex 分支重跑并以 manifest+SHA256SUMS 核查（docs/09:64）。
- 现状：近期记录见 [58-session-handoff-2026-11-09-r2.md:260,278](58-session-handoff-2026-11-09-r2.md)（0015 绿、0016 CDP 抖动失败、0017 恢复）。

### 2.3 native 工具 Python 测试

- 用途：native 打包/校验工具自身的回归（fail-closed 行为）。
- 命令（CI 已核实形态，逐文件跑）：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s validation/native/tool -p test_android_bundle.py -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s validation/native/tool -p test_android_zerotier.py -v
```

（[android-network-experiment.yml:140,336](../.github/workflows/android-network-experiment.yml)；另有 `python validation/native/tool/portable_candidate.py`，[native-candidate-validation.yml:36](../.github/workflows/native-candidate-validation.yml)。）
- 记录口径：逐文件通过/失败；全目录 `-p 'test_*.py'` 形式为同约定外推，未在 CI/文档中显式出现，未单独核实。

### 2.4 Rust crate 测试

- transport（[transport-rust/README.md:21](../validation/transport-rust/README.md)）：

```sh
cargo test --locked --manifest-path validation/transport-rust/Cargo.toml
```

  现状：42 项 library + 1 项 CLI report 通过，含 11 项 overlay adapter（README:72）。overlay 合成 fixture 变体：`CARGO_TARGET_DIR=/private/tmp/… cargo test --locked --offline --manifest-path validation/transport-rust/Cargo.toml --features overlay-native-fixture`（README:77）。

- Tauri native：`cargo check --locked --manifest-path validation/tauri/src-tauri/Cargo.toml`（README:22）。注意 network-zerotier 的 `start()` 带 `#[cfg(any(test,target_os="android"))]`，须 `--all-targets` 才编译 test cfg；「0 errors (0 crates)」是假绿（[58:287](58-session-handoff-2026-11-09-r2.md)）。
- overlay-runtime：`cargo test --locked --offline --features native-fixture` / clippy `-D warnings` / `tailscale-fixture` / `native-fixture,tailscale-fixture` 各态分跑（[overlay-runtime/README.md:14-16,87-88,129-130](../validation/overlay-runtime/README.md)）。
- portable-stream：`cargo test --locked --manifest-path validation/native/portable-stream/Cargo.toml`（[README.md:26](../validation/native/portable-stream/README.md)，本地 8/8 rustc 1.96.0；CI 1.95.0 分层跑）。
- ssh：本机仅 `cargo check --locked --manifest-path validation/ssh/Cargo.toml`；构建与真实协议在 CI（`cargo build --locked` + `python3 validation/ssh/run-ci.py`，[ssh-validation.yml:32-34](../.github/workflows/ssh-validation.yml)）。
- remote-probe CLI（协议可重放探针，[transport-rust/README.md:34](../validation/transport-rust/README.md)）：

```sh
cargo run --locked --manifest-path validation/transport-rust/Cargo.toml --bin remote-probe -- \
  --config TEMP_CONFIG_PATH --case positive --output SAFE_REPORT_PATH
```

  仅接受 `GITHUB_ACTIONS=true`、`127.0.0.1` 非特权端口、显式临时文件；四 case 为 positive/wrong-pin/missing-session/cancel。

### 2.5 Flutter 测试的正确姿势（不能在 validation/flutter/ 直接跑）

`validation/flutter/` 是模板源目录（只有 lib/test/tool/patches 等，无 `flutter create` 生成的平台脚手架），工程须由 `ci.py prepare` 在**不存在的目标目录**生成：脚本拷入 pubspec.yaml/lock 并从 SHA-256 固定的 pub.dev 归档建立 terminal_view 引用（[ci.py:35-50](../validation/flutter/tool/ci.py)），拒绝覆盖已有目录（[ci.py:36-37](../validation/flutter/tool/ci.py)）。完整序列（[flutter/README.md:55-62](../validation/flutter/README.md)）：

```sh
python3 validation/flutter/tool/ci.py prepare --destination /tmp/herdr-flutter-probe
cd /tmp/herdr-flutter-probe
flutter pub get
flutter analyze
flutter test
```

- `ci.py` 子命令固定为 `bootstrap | prepare | package`，`--destination` 必填（[ci.py:337-338](../validation/flutter/tool/ci.py)）。
- 重跑须换新临时路径（README:64）。
- 记录口径：analyzer、单测/widget、渲染回归（regression/）分别计数（如 [15-mobile-gui-validation.md:7,60,70](15-mobile-gui-validation.md) 的「N 项通过」口径）；本地通过不等于 CI/设备通过。

### 2.6 native 候选源码准备与 Android 打包

```sh
python3 validation/native/tool/tailscale_candidate.py prepare /absolute/fresh/work --cache /absolute/dedicated/cache
python3 validation/native/tool/tailscale_candidate.py build /absolute/fresh/work --cache /absolute/dedicated/cache
```

（[native/README.md:65-66](../validation/native/README.md)；工作目录与缓存须绝对路径、全新。）Android 打包链 `android_bundle.py build|verify|apk|report` 见 [android-network-experiment.yml:153,207,254,283](../.github/workflows/android-network-experiment.yml)。

### 2.7 CI 触发分支命名规则

- push 触发的工作流只有三个前缀：`codex/network-batch/**`（[android-network-experiment.yml:4](../.github/workflows/android-network-experiment.yml)）、`codex/batch/**`（[batch-validation.yml:4](../.github/workflows/batch-validation.yml)）、`codex/native-macos/**`（[native-candidate-validation.yml:6](../.github/workflows/native-candidate-validation.yml)）；其余 workflow 仅 workflow_call/workflow_dispatch。
- 命名规则（[58:136-138](58-session-handoff-2026-11-09-r2.md)）：`codex/network-batch/with-emulators-<主题>-<批次NNNN>-<HEAD 7 位短 sha>`，如 `with-emulators-zerotier-0010`；TUI 输入批次用 `with-emulators-input-tui-<批次>-<SHA>`（[58:281](58-session-handoff-2026-11-09-r2.md)）。推送时以实际 HEAD 为准；concurrency 按分支隔离。
- 推送纪律（[58:149-150](58-session-handoff-2026-11-09-r2.md)）：一轮只推一个触发分支；不 force push；不删远端分支；不用 workflow_dispatch。

## 3. 降级行为清单

错误码均为源码中真实字符串（已逐个给出 file:line）。总原则：能力缺失时**停在该能力边界内**，不静默改走系统通道、不生成替代身份、不重放输入（docs/02:93 禁止静默降级）。

| 场景 | 触发条件 | 系统行为 | 用户可见反馈 | 失败错误码 | 依据 |
| --- | --- | --- | --- | --- | --- |
| Android 设备密钥插件未加载/未注册 | MethodChannel `dev.herdr/device-keys` 调用抛异常或返回 null | 四方法边界整体失败，不落明文、不生成替代身份 | 「设备密钥锁定、丢失或不可用 · 已停止，不会生成替代身份或使用明文」 | `device_key_unavailable` | [device_keys.dart:19-21,37,57](../validation/flutter/lib/device_keys.dart)、[remote_page.dart:554](../validation/flutter/lib/remote_page.dart) |
| 设备安全存储桥平台不支持（Windows/Linux 探针） | 平台无 Keychain/Keystore 桥接线 | 设备配对入口禁用，保留手动隔离实验 | 「此平台的设备安全存储桥不可用 · 设备配对已禁用，可返回手动隔离实验」 | （UI 禁用态，无码） | [pairing_page.dart:478](../validation/flutter/lib/pairing_page.dart)、[flutter/README.md:143](../validation/flutter/README.md) |
| Android 网络原生库缺失 | `System.loadLibrary("heeler_easytier"/"hp_tailscale"/"hp_zerotier")` 抛 LinkageError，或 `bindNative` 失败 | 加载失败静默捕获、对应 provider 置为未绑定，服务保持不可用；不 crash | 该网络不可启动；连接时按 provider 不可用降级 | 后续操作返回 `provider_unavailable` | [NetworkRuntimeChannel.kt:86-93](../validation/flutter/native/android/NetworkRuntimeChannel.kt)、[58:287](58-session-handoff-2026-11-09-r2.md) |
| 网络 provider 不可用（feature 关闭/桥缺失） | provider 不在已启用集合、runtime 不可用或 feature 未编译 | 停止连接，不改走系统 TCP/DNS | 「provider_unavailable · 此平台或网络的连接桥不可用，已停止；不会改走系统 TCP 或 DNS」 | `provider_unavailable`（Flutter）、`overlay_provider_unavailable`（Tauri，含 `_ => Err` 兜底）、Rust 层 `Failure::ProviderUnavailable` | [network_profiles.dart:154](../validation/flutter/lib/network_profiles.dart)、[remote_page.dart:549](../validation/flutter/lib/remote_page.dart)、[lib.rs:217,224,246](../validation/tauri/src-tauri/src/lib.rs)、[overlay lib.rs:43](../validation/overlay-runtime/src/lib.rs)、[zerotier.rs:164](../validation/overlay-runtime/src/zerotier.rs) |
| 节点运行时状态不可确认 | runtime 状态读取失败 | 停止并要求刷新后重新审查 | 「节点状态或连接桥不可确认 · 已停止，请刷新状态后重新审查」 | `network_runtime_unavailable` | [network_runtime.dart:27](../validation/flutter/lib/network_runtime.dart)、[remote_page.dart:552](../validation/flutter/lib/remote_page.dart) |
| 设备密钥存储不可用（锁定/丢失/身份变更） | 签名/读取失败或身份代际不匹配 | 连接中止；迟到签名不可用；ZeroTier 设备身份降为只读 | 密钥类提示（同上）；ZeroTier 设备显示「设备身份暂不可用 · 可能是本版本未启用原生组件、设备锁定或读取失败…」；不可用时不自动入网 | `device_key_unavailable`、`device_key_changed`、`key_unavailable`（Tauri 桩实现）、`zerotier_device_unavailable` | [connection_diagnostics.dart:59](../validation/flutter/lib/connection_diagnostics.dart)、[zerotier_device_dialog.dart:93](../validation/flutter/lib/zerotier_device_dialog.dart)、[tauri lib.rs:561-563](../validation/tauri/src-tauri/src/lib.rs)、[zerotier_device.rs:17-19](../validation/tauri/src-tauri/src/zerotier_device.rs) |
| ZeroTier 设备写结果未知 | 写入通道异常（不能确认落盘与否） | 不重放变更；unknown 结果后仅允许状态读取，无 fallback | 状态页明示未知；人工恢复须重连取新 full | `zerotier_device_write_unknown`、`zerotier_device_result_unknown` | [zerotier_device.dart:84,92](../validation/flutter/lib/zerotier_device.dart)（注释「Unknown: read only」「Never repeat a mutation after an unknown result」，:237,:281,:320） |
| 观察通道不可用/中断 | SSH channel 打开、exec 或关闭失败 | 观察流以明确错误终止；迟到事件不撤销新状态；可显式重连取新 full | 终端标陈旧；远端输入字节保持 0（不重放） | `observe_failed`、`observe_close_failed`、`snapshot_failed`、`socket_unavailable`、`pane_missing`、`session_mismatch` | [controlled.rs:629,669,748,765,784,830](../validation/transport-rust/src/controlled.rs)、[remote-probe.rs:185,229](../validation/transport-rust/src/bin/remote-probe.rs) |
| Android 看板搜索拿不到 IPC 计数器 | 看板 counter 经 CDP 不可达（三分支互斥根因） | 有界等待失败并报码；不把未决快照当成功 | 判读按三分支签名：①「本机资料不可用；仍可打开手动连接表单」②停留「正在读取本机资料…」③「浏览器预览不读取本机主机资料。」 | `android_board_search_counter_no_ipc`；CDP 层 `android_cdp_transport_failed` | [android_gui.py:897,371](../validation/remote-harness/android_gui.py)、[58:120-131](58-session-handoff-2026-11-09-r2.md) |
| 主机资料存储不可用 | 主机目录创建/读写失败 | 主机资料操作失败返回错误码；已读到的关联主机与网络仍可显示，目录读取失败显示范围未知 | `no_ipc` 分支①文案（手动连接表单兜底） | `host_storage_unavailable` | [hosts.rs:206-236,303,331](../validation/tauri/src-tauri/src/hosts.rs)、[56:32](56-project-status-and-handoff.md) |
| 剪贴板不可用/超大/失焦 | 系统剪贴板读取异常、内容超限或目标窗口失焦 | Flutter：跳过粘贴，提示手动输入；Tauri：未聚焦/超大分别拒绝，其余塌缩为通用码；配对复制不可用时可手动选择公开请求全文 | 「系统剪贴板不可用，可手动输入临时私钥」「复制不可用时，可手动选择上方公开请求全文」 | `clipboard_unavailable`（塌缩码）、`clipboard_too_large`、`clipboard_unfocused` | [remote_page.dart:1175-1177](../validation/flutter/lib/remote_page.dart)、[clipboard.rs:36-38](../validation/tauri/src-tauri/src/clipboard.rs)、[pair_copy.rs:39,363](../validation/tauri/src-tauri/src/pair_copy.rs)、[pairing_page.dart:236,512](../validation/flutter/lib/pairing_page.dart) |
| 相机不可用/权限被拒 | 无视频设备、输入无法加入 session、授权拒绝或用户取消 | 扫描终止并返回公开文本 null；不阻塞手动路径 | 「相机不可用、权限被拒绝或扫描取消 · 可继续手动输入响应」「扫描不可用或资料无效 · 未填入表单，可手动粘贴」 | `camera_unavailable`、`camera_permission_denied` | [PairScanner.swift:44,47,56,61,65](../validation/pairing/native/camera/apple/PairScanner.swift)、[pairing_page.dart:429,450](../validation/flutter/lib/pairing_page.dart) |
| 凭据服务锁定或缺失（Linux Secret Service） | Dart tailscale wrapper 场景：`secret-tool` 缺失或 Secret Service 未解锁 | 该 wrapper 持久身份不可用——**须作为安装与存储失败验收项**，不是运行时自动回退；当前两壳在 Windows/Linux 直接禁用设备桥（见上行），Linux Secret Service 运行时路径未实测 | 探针层为禁用提示；产品层行为未实现/未验证 | 无专用码（未实现）；设计要求禁止明文回退 | [00-research.md:23](00-research.md)、[02-architecture.md:53](02-architecture.md)、[03-pitfalls.md:92](03-pitfalls.md)、[flutter/README.md:143](../validation/flutter/README.md) |
| 多标签容量/陈旧 | 标签满（8 个上限）或 owner/generation 不匹配 | 容量：拒绝新标签；陈旧：取消旧 claim 并拒绝操作，防跨代误用 | 标签操作失败并报码 | `tab_capacity`、`tab_stale`、`state_unavailable`、`input_stale` | [remote_sessions.rs:45](../validation/tauri/src-tauri/src/remote_sessions.rs)（`>=8`）、[remote_tab_commands.rs:23,33,45,56](../validation/tauri/src-tauri/src/remote_tab_commands.rs) |

## 未确认项清单

1. **vite 8.3.5、jni 0.21.1、herdr 0.9.5 的许可证**：查证 docs/17 全文与 remote-dependencies.json 范围，均未单列；按未确认记录，不做推测。
2. **CI sshd/OpenSSH 版本**：查证 ssh-validation.yml、mobile-remote-validation.yml 与 remote-harness README，使用 runner 预装且无版本锁定记录。
3. **native/tool 全目录 unittest discover**（`-p 'test_*.py'`）：CI 只按单文件形态跑（android-network-experiment.yml:140,336）；全目录形式未核实，文中已标注为同约定外推。
4. **docs/17 的核查日期**：文内无显式日期字段，取 git 最后提交日 2026-11-07。
5. **Linux Secret Service 锁定/缺失的运行时降级**：仓库内无该场景的代码路径实测；现有证据止于调研文档（docs/00:23、docs/02:53、docs/03:92）与两壳探针的「平台禁用」实现。
6. **Mac17,3 / macOS 26.6.2**：为 2026-10-30 批次记录（docs/09:26），当前 runner 版本未复核。
