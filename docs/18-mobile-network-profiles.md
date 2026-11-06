# 手机网络配置、迁移与节点生命周期

2026-11-06。本批在配对、主机看板、持续观察和受保护输入的基础上，接入独立网络配置、主机显式绑定、加密迁移 v2 与本机终端字号。两份同源 Android 包已构建并下载核验，两端只读配对与持续观察通过；Tauri 受保护输入通过，Flutter 回归及受保护用例有失败。Flutter 与 Tauri 继续使用同一份公开配置与加密样例，框架尚未定案。此前包及结果保留在[手机输入记录](16-mobile-input-and-config.md)。

## 手机入口与持久化

两套主机看板增加网络配置管理。Tailscale 收集控制地址和设备名称，EasyTier 收集公开网络名称和节点地址，ZeroTier 收集网络 ID。网络秘密和设备节点身份不进入此表单。配置可由多个主机引用；修改、停用或解除绑定前列出受影响主机，并撤销其旧标签连接许可。仍被引用的网络需要先处理主机绑定才能删除。

旧主机默认沿用原有系统连接路径。显式绑定 overlay 的主机在组件未接通时显示受阻状态，拒绝实际连接，不回退到普通 DNS／TCP。本地公钥生成、配对请求恢复和 helper 响应审查可以独立完成；停用网络后仍能进入这些离线步骤。连接、签名和观察另行检查当前网络与 revision。

加密迁移 v2 包含主机、公开网络参数及可选字号；v1 档案继续兼容。导出主机自动带入其依赖网络，也可单独导出网络或偏好。导入生成新本机网络 ID，网络默认停用，偏好默认不覆盖。保留冲突主机时保留旧绑定，不暗中创建该项的网络依赖。容量与引用检查先完成，主机、网络和所选偏好再通过一次目录 CAS 提交；保存结果未知时必须重读核查。

字号范围为 10–28，旧目录默认 14，只改变本机终端呈现。字号、窗口和软键盘变化均不隐式改远端共享 PTY 尺寸。详细字段、版本与上限见[共享契约](../validation/network-profiles/README.md)。

## 原生节点的证据边界

EasyTier 增加独立 managed-node ABI 和运行时包装，启动、状态、停止和流连接绑定不可复用的 node lease 与公开配置 revision。晚到启动、流关闭失败和停止超时保留其资源配额；清理只能针对原实例，失败后允许显式重试。现有五个 stream 符号保持兼容。

独立复核复现并修复两项生命周期问题：pending start 被 detach 后可能重新开放连接，以及旧 managed revision 可能匹配后续 legacy revision 0。修复将退休与激活检查放在同一 registry 锁下，并对所有显式 revision 严格匹配。合成回归覆盖两种先后顺序及超时后的迟到清理。

当前没有生产用 SecureConfigSource，缺少它时启动返回 IdentityUnavailable。新 ABI 已在 Linux、Windows 和 macOS 完成真实固定 Heeler 库的编译、链接及九个符号加载，尚未接入 GUI 的实际 overlay 路由。Tailscale 和 ZeroTier 仍在原生验证阶段。公开网络配置保存成功不代表节点已授权、已加入网络或可以连通。

## 本地验收与本批云验证

| 范围 | 当前证据 |
| --- | --- |
| Tauri 目录、离线配对与路由门禁 | Rust 16 项通过，含停用网络离线审查、容量前置校验和 v2 原子导入 |
| Tauri 页面状态 | JavaScript 54 项及前端构建通过，含保存失败后先撤销旧许可、等待主机刷新再重读网络 |
| 共享迁移 | Rust 4 项通过；独立 Python v2 加密黄金字节一致，v1 继续通过 |
| 网络记录 | 同一份 4 个有效、41 个拒绝样例由两条路线消费；Rust 已执行通过 |
| Flutter 新增页面与回归 | 本地语法及工具检查通过；本批云回归因测试方法引用和旧 schema 断言失败，渲染 10 项通过；见下方具体结果 |
| Mac 原生 GUI | 独立应用在 390×844 窗口实际保存网络和字号、通过系统选择器导出与导入；预览保留同名原配置，新导入网络停用、偏好默认不应用 |
| EasyTier 包装层 | 默认缺桥门禁 1 项、C ABI fixture 23 项、精确模板 fake-engine 4 项通过；原 portable 8 项通过 |
| 实际网络与设备 | 新节点的真实启动／加入／拨号、三网、设备安全存储及手机触控／IME未验证 |

原生独立结果与来源摘要见[节点离线证据](../validation/native/evidence/2026-11-06-managed-node-offline.json)和[固定源码审计](../validation/native/managed-source-audit.json)。Portable 原模块仍有一条既有 Clippy `collapsible_if` 提示；新增运行时两种配置的严格 Clippy 均通过。

Mac 使用独立应用标识及合成公开资料，未创建设备密钥或真实节点。导出文件 236 bytes，经独立 Python 解密得到准确的 v2 载荷。测试应用已退出，并通过应用清单与确切进程路径确认关闭。文件选择器单击 Open 的自动化未完成，改用双击所选文件成功；截图接口返回空白，本次只记录实际控件交互，不作视觉验收。[Mac 记录与源码摘要](evidence/mobile-pair-gui/macos-network-config.json)

Penpot v2 已根据这些结果保存 S27–S30：网络列表、编辑影响、迁移审查及导入后状态，现共 30 个画板。新增 19 个导航对象目的地重载后均有效，实际点击编辑往返和完整迁移返回回路。导出图经检查修正 S29 顶部小标；设计不代表原生桥接或真机通过。[打开网络原型](https://design.penpot.app/?screen=viewer&file-id=b55064db-d93d-80f9-8008-ddd22e6d398f&page-id=7a22df08-251d-8016-8008-de03541c11da&section=interactions&frame-id=b9d502c0-514c-80a9-8008-e7033d91f34d) · [设计证据与覆盖](../design/v2-coverage.md)

本批使用 `codex/batch/android-input-networks-*` 集中运行：两套 Android 普通测试包与独立 stock／guarded AVD、共享迁移与生命周期测试、三个桌面 runner 的真实 fixed-source native 编译／链接。原生库、GUI 和输入 helper 保持各自产物并记录同一源码版本。两套包 manifest 新增网络配置和 v2 迁移样例 SHA-256，正式 Release 与商店提交不在此批内。

源码 `040eb26` 已启动[集中运行 42158644225](https://github.com/Luck9Star/herdr-pocket/actions/runs/42158644225)。首个 macOS job 在分配 runner 前取消，注解为 `The configuration 'macos-14-arm64-us-default' is not supported`，没有编译步骤。2026-11-06 按 Context7 library → docs 核对[官方镜像表](https://github.com/actions/runner-images/blob/main/README.md)和[退役公告](https://github.com/actions/runner-images/issues/13518)，将余下的 `macos-14` 工作流固定为 `macos-15` arm64。原生候选增加仅 Mac 的 `codex/native-macos/**` 补验入口，避免重跑 Android 与其他已完成任务。runner 系统版本和应用最低运行版本分别记录。

| 原生 runner / 来源 | 真实固定源码与符号结果 | 可获取证据 |
| --- | --- | --- |
| Ubuntu 24.04 x64 / `040eb26` | check、link、load 通过；loopback 9 通过、21 筛除 | [artifact 13476275992](https://github.com/Luck9Star/herdr-pocket/actions/runs/42158644225/artifacts/13476275992) |
| Windows 2022 AMD64 / `040eb26` | check、link、load 通过；loopback 8 通过、21 筛除 | [artifact 13476172232](https://github.com/Luck9Star/herdr-pocket/actions/runs/42158644225/artifacts/13476172232) |
| macOS 15 arm64 / `1fc7dce` | 定向补验通过；loopback 9 通过、21 筛除 | [运行 42159392366](https://github.com/Luck9Star/herdr-pocket/actions/runs/42159392366) · [artifact 13477075011](https://github.com/Luck9Star/herdr-pocket/actions/runs/42159392366/artifacts/13477075011) |

三份产物均已下载校验，每份 28 条校验和通过，补丁 SHA-256 同为 `98897e41300496ad20b4708172c1c111f8ecab08e7cb279530b5a10f0e3620d7`。Mac 后续提交只调整工作流和文档，原生与 GUI 源码相同。加载器验证五个 stream 和四个 managed-node 导出符号，并仅调用无效 handle；没有启动真实节点。ZIP 包含来源、补丁、日志和库摘要，**不包含编译出的动态库文件**，尚不能直接供 GUI 链接分发。

## Android 下载与实际结果

两份普通应用来自同一 `040eb26ba7c31e071048616a39591e17c74c99ab`。下载 GitHub artifact 需要登录，保留期为 14 天。新网络绑定仍会因原生桥未接入而拒绝连接；原有系统 SSH 路径可用于已授权的独立测试目标。

| 候选 | 下载与解包 | APK SHA-256 |
| --- | --- | --- |
| Flutter，三种 ABI | [artifact 13476846146](https://github.com/Luck9Star/herdr-pocket/actions/runs/42158644225/artifacts/13476846146)，取 `flutter-appmain-package/flutter-android-debug.apk`，157351963 bytes | `12346fd09e22e6d0c03d2c37fc5ff34c5f52d0325fd3358a07b33c09d3e92ff7` |
| Tauri，arm64-v8a | [artifact 13475774527](https://github.com/Luck9Star/herdr-pocket/actions/runs/42158644225/artifacts/13475774527)，解压后取 `app-arm64-v8a-debug.apk`，177077085 bytes | `6e660b0138cb7b2fc5772efd428212b68e5706bfafc85ca2bd58c58526bebd8c` |

已独立核对源码、实际 APK 哈希、ABI、v1 迁移／v2 迁移／网络配置三份 fixture 摘要及三份原生许可声明。两份 artifact 附带的共享字体来源材料校验通过；Flutter APK 内 35 个字体与声明文件逐字匹配。Tauri 网页资源内嵌方式未做逐文件解码，不能将外层来源材料校验冒充 APK 内每个字体文件的字节证明。[机器可读的产物和运行记录](evidence/mobile-pair-gui/network-config-build-040eb26.json)

- 两端原版用例通过配对审查、设备公钥 SSH 认证、看板、选 pane、full/delta 与主动停止，远端输入为 0。Flutter 清理报告通过；签名探针也通过。
- Tauri 扩展用例通过逐键 `k`、隐藏后显式恢复同一目标、新 full、草稿 `Pocket测`，两笔不同请求 ID 的回执分别受理 1 和 9 bytes。接收端恰好 10 UTF-8 bytes，991 次共享 PTY 取样保持 119×40，最大间隔 81ms，未观测到 resize。临时授权撤销及进程／密钥清理通过。
- Flutter analyzer 的 `PendingDevicePairing.toPublicRecord` 引用错误使三个新测试文件无法加载；旧导入回归还期待 schema 3，实际为 4。渲染回归 10 项通过。guarded AVD 在 `response_source_confirm` 单击后仍未选中复选框，尚未进入 SSH 或输入阶段；这份报告不能证明签名或远端输入有错。该 lane 清理通过。
- 原批次整体结论为 **cancelled**，同时含 Flutter job failure；Mac 定向补验单独为 success。不能合并称整批通过。[逐 lane 的安全报告](evidence/mobile-pair-gui/gui-040eb26/index.json)

测试步骤：先核验 APK 摘要，再以合成公开资料检查网络新建、停用、主机绑定影响和本机字号；导出所选网络与偏好，再导入预览，确认同名原配置保留、新网络停用、字号默认不覆盖。配对与 SSH 继续采用[隔离云 harness](../validation/remote-harness/README.md)；不把真实主机授权或凭据交给实验驱动。手机 IME、触控和相机需具备真机条件后另验，用完关闭测试应用。

## 验证后的源码修正

`61a6b09` 修正了 Flutter 测试方法引用、旧 schema 断言与一处冗余导入。Android 驱动有界等待真实视口和 Checkbox 命中位置稳定，仅点击一次真实控件，再断言选中状态；没有直接赋予审查许可。它是测试动作改进，尚不能确认 guarded 失败的根因。

同一后续提交修正 Tauri 导入后的导出选项刷新及主机计数文案。保存成功或结果未知后均重读网络目录，读取失败禁用导出，不沿用旧列表。JavaScript 58 项通过，新增四项覆盖成功／未知与读取成功／失败的组合；父代理独立复跑通过。Flutter 语法、工具与隔离 Python 检查通过，新 Flutter/widget 和 AVD 尚未再跑。这些后续改动**不包含在上面的 `040eb26` APK**，随下一批集中验收。

## 下一步

先随下一批复验 Flutter 测试驱动与模型回归的源码修正，再完成设备安全存储与原生节点适配，打通显式 overlay 绑定下的配对接入、看板与持续观察。随后完善跨网络手机标签、断线／迟到数据和输入恢复，反馈到 Penpot 的连接受阻与配置迁移页面。桌面真实分屏和独立焦点排在手机闭环之后。没有真机或网络证据的格子继续标为未验证。
