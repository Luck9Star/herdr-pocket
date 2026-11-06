# 手机双网络集中云验收

2026-11-07（北京时间）。手机持续看板、按目标隔离的未知输入，以及 Tailscale 身份／显式登录／原节点路由已进入两份 Android 测试包。源码为 [`750798fe`](https://github.com/Luck9Star/herdr-pocket/commit/750798fe6bf5e396768333c1abe8c96ff0dd2178)，[run 42247482105](https://github.com/Luck9Star/herdr-pocket/actions/runs/42247482105) 的五个 job 全部成功。此前失败及实际校验见[完整记录](evidence/mobile-pair-gui/mobile-tailscale-ci-20261107.json)。本批仍未验证 Android 安装、KeyStore、真实组网或手机输入体验。

## 下载与来源

| 路线 | 测试归档 | 解压后 app.apk SHA-256 |
| --- | --- | --- |
| Flutter | [arm64 debug APK 与报告](https://github.com/Luck9Star/herdr-pocket/actions/runs/42247482105/artifacts/13519144162) | `a82ba20373b978148c3e4e79578762f15fe70db506b042302ba22bba8688d856` |
| Tauri | [arm64 debug APK 与报告](https://github.com/Luck9Star/herdr-pocket/actions/runs/42247482105/artifacts/13518524214) | `c9d29debe48e7766938b0e7b9586ceb5d0507bce96194bc58bcc0063be6b5edf` |

两份归档均已实际下载，ZIP digest、SHA256SUMS、APK hash、来源提交和包内原生库字节已核对。Flutter APK 为 483,705,420 字节，Tauri 为 591,434,055 字节；保留调试符号用于检查，体积不是正式版本目标。两份 artifact 分别保留至 2026-11-20 16:06:49／16:08:38 UTC（北京时间 11 月 21 日凌晨）。目标为 Android API 35、arm64-v8a；一次性 debug 签名不保证与旧包原地升级。未创建 Release、tag 或提交商店。

[独立原生来源包](https://github.com/Luck9Star/herdr-pocket/actions/runs/42247482105/artifacts/13518118351)固定 NDK 28.2.13676358、Rust 1.95.0、Go 1.27.3 与 Tailscale v1.104.1，保留上游、补丁、对应源码、构建日志和声明。两 APK 内的 EasyTier／Tailscale 库与本次来源包逐字节一致，JNI、ABI 和动态依赖检查通过。**包中没有 ZeroTier**；其后续源码不能用本次结果验收。许可审查的未闭合项仍见[发行审查](17-license-and-distribution-review.md)。

## 实际执行与失败

| 检查 | 本批结果 | 范围 |
| --- | --- | --- |
| Flutter analyzer | 通过 | runner 中的完整候选工程 |
| Flutter 常规 suite | 248 通过、1 跳过 | 状态、输入、网络与 widget；跳过项是单独执行的 opt-in SSH 用例 |
| 组合重音绘制 | 10 通过 | 固定 terminal_view 修复候选 |
| 共享 Rust transport | 95 library + 1 CLI 通过 | 合成 provider 与自建隔离连接 |
| Tauri JavaScript | 115 通过 | 本批实际执行；Android Rust target 编译通过，未另跑 Rust 测试 suite |
| 两套 APK | 构建与静态检查通过 | 不等于设备安装或动态加载 |
| Flutter 配对／持续观察 | 独立隔离 SSH job 通过 | 真实 OpenSSH/herdr，测试 signer 与本地存储替身 |

[首轮 42243620730](https://github.com/Luck9Star/herdr-pocket/actions/runs/42243620730)使用 `ff28d858`，实际失败：Linux GCC 将 C fixture 的六处误导缩进升级为错误；Flutter 有四个 analyzer 诊断及四个测试失败。虽然那一轮也生成了 APK，整批仍为失败，不作为本页推荐版本。

修复包括显式 C 分支、异步测试异常等待、后台隐藏表单的正确断言、明确的已停止节点 fixture、测试结束前恢复平台 override，以及允许合法 Tailscale 路由并继续拒绝非规范版本号。保留对跨 provider 未知输入隔离的断言，没有放宽生产保护条件。所有修复集中在一个后续提交与一次复验，不逐项触发 Actions。下载阶段的 DNS／部分传输错误经同一 artifact 的有界重试恢复，没有重新构建。

[隔离 SSH 原始 manifest](evidence/mobile-pair-gui/mobile-tailscale-flutter-ssh-20261107.json)记录：配对审查 → 看板 → 选择 pane → full／delta 持续观察 → 隐藏后保留同一 SSH 并明确恢复 → 主动停止。收到 6 帧，4 个 delta 被绘制；两次本地视口变化下远端输入为 0、共享 PTY 始终 119×40。身份由 runner 临时生成，显式测试 signer 完成签名；授权仅在自建 fixture sshd，结束后清理，不操作用户主机授权文件。这是 Ubuntu headless widget 与链路证据，未证明 Android 安全存储、像素观感或经真实 Tailscale／EasyTier 的 SSH。

## 手机验收步骤与后续顺序

1. 下载并解压所选归档，保留 `app.apk`、`report.json`、校验和及来源材料；先核对上表 SHA。使用单独测试设备或测试环境，记录安装与首次加载结果；目前这些项均为未验证。
2. 先验证配对审查、host key 核对、设备钥引用、看板和持续观察；不把扫码内容当作主机确认，不自动授权或连接。观察后切换标签、收起／展开键盘，再明确恢复原 pane，记录是否保留原目标与是否出现迟到画面。
3. Tailscale 先保存公开配置、创建本机身份、明确启动，再分别请求授权与打开已审查 URL；返回后只读核对原节点。EasyTier 使用本机独立身份。没有就绪或正确桥接时须拒绝连接，不能回退系统 TCP。
4. 断线或输入结果未知时先核对，不自动重放；布局变化不应修改共享 PTY。中文 IME、触控、快捷键、TUI、真实网络并发与 Android KeyStore 逐项记录，未有设备结果就保持未验证。更多步骤沿用[手机终端验收](22-mobile-terminal-tabs.md#新包的手机验收步骤)。

当前只能使用 Mac 与云端，因此先继续 ZeroTier 的设备级身份、单节点多网络租约、定向 socket 与手机 GUI，再统一测试；桌面分屏随后推进。五平台十五个 provider 格及并发矩阵仍须独立验证，框架未定案。已有严格 transport Clippy 的 12 项诊断也未被本次成功的测试／构建抹去。
