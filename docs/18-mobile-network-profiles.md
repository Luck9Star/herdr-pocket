# 手机网络配置、迁移与节点生命周期

2026-11-06。本批在配对、主机看板、持续观察和受保护输入的基础上，接入独立网络配置、主机显式绑定、加密迁移 v2 与本机终端字号。Flutter 与 Tauri 继续使用同一份公开配置与加密样例；框架尚未定案。此前 Android 包及结果保留在[手机输入记录](16-mobile-input-and-config.md)，本批新版包和云结果待下文验收后补充。

## 手机入口与持久化

两套主机看板增加网络配置管理。Tailscale 收集控制地址和设备名称，EasyTier 收集公开网络名称和节点地址，ZeroTier 收集网络 ID。网络秘密和设备节点身份不进入此表单。配置可由多个主机引用；修改、停用或解除绑定前列出受影响主机，并撤销其旧标签连接许可。仍被引用的网络需要先处理主机绑定才能删除。

旧主机默认沿用原有系统连接路径。显式绑定 overlay 的主机在组件未接通时显示受阻状态，拒绝实际连接，不回退到普通 DNS／TCP。本地公钥生成、配对请求恢复和 helper 响应审查可以独立完成；停用网络后仍能进入这些离线步骤。连接、签名和观察另行检查当前网络与 revision。

加密迁移 v2 包含主机、公开网络参数及可选字号；v1 档案继续兼容。导出主机自动带入其依赖网络，也可单独导出网络或偏好。导入生成新本机网络 ID，网络默认停用，偏好默认不覆盖。保留冲突主机时保留旧绑定，不暗中创建该项的网络依赖。容量与引用检查先完成，主机、网络和所选偏好再通过一次目录 CAS 提交；保存结果未知时必须重读核查。

字号范围为 10–28，旧目录默认 14，只改变本机终端呈现。字号、窗口和软键盘变化均不隐式改远端共享 PTY 尺寸。详细字段、版本与上限见[共享契约](../validation/network-profiles/README.md)。

## 原生节点的证据边界

EasyTier 增加独立 managed-node ABI 和运行时包装，启动、状态、停止和流连接绑定不可复用的 node lease 与公开配置 revision。晚到启动、流关闭失败和停止超时保留其资源配额；清理只能针对原实例，失败后允许显式重试。现有五个 stream 符号保持兼容。

独立复核复现并修复两项生命周期问题：pending start 被 detach 后可能重新开放连接，以及旧 managed revision 可能匹配后续 legacy revision 0。修复将退休与激活检查放在同一 registry 锁下，并对所有显式 revision 严格匹配。合成回归覆盖两种先后顺序及超时后的迟到清理。

当前没有生产用 SecureConfigSource，缺少它时启动返回 IdentityUnavailable。新 ABI 尚未完成真实固定 Heeler 库的编译／链接验收，也未接入 GUI 的实际 overlay 路由。Tailscale 和 ZeroTier 仍在原生验证阶段。公开网络配置保存成功不代表节点已授权、已加入网络或可以连通。

## 本地验收与本批云验证

| 范围 | 当前证据 |
| --- | --- |
| Tauri 目录、离线配对与路由门禁 | Rust 16 项通过，含停用网络离线审查、容量前置校验和 v2 原子导入 |
| Tauri 页面状态 | JavaScript 54 项及前端构建通过，含保存失败后先撤销旧许可、等待主机刷新再重读网络 |
| 共享迁移 | Rust 4 项通过；独立 Python v2 加密黄金字节一致，v1 继续通过 |
| 网络记录 | 同一份 4 个有效、41 个拒绝样例由两条路线消费；Rust 已执行通过 |
| Flutter 新增页面与回归 | 45 个 Dart 文件语法检查和 8 项 Python 工具测试通过；本机无 Flutter SDK，新 widget／加密回归待云端执行 |
| Mac 原生 GUI | 独立应用在 390×844 窗口实际保存网络和字号、通过系统选择器导出与导入；预览保留同名原配置，新导入网络停用、偏好默认不应用 |
| EasyTier 包装层 | 默认缺桥门禁 1 项、C ABI fixture 23 项、精确模板 fake-engine 4 项通过；原 portable 8 项通过 |
| 实际网络与设备 | 新节点 ABI、真实三网、设备安全存储及手机触控／IME未验证 |

原生独立结果与来源摘要见[节点离线证据](../validation/native/evidence/2026-11-06-managed-node-offline.json)和[固定源码审计](../validation/native/managed-source-audit.json)。Portable 原模块仍有一条既有 Clippy `collapsible_if` 提示；新增运行时两种配置的严格 Clippy 均通过。

Mac 使用独立应用标识及合成公开资料，未创建设备密钥或真实节点。导出文件 236 bytes，经独立 Python 解密得到准确的 v2 载荷。测试应用已退出，并通过应用清单与确切进程路径确认关闭。文件选择器单击 Open 的自动化未完成，改用双击所选文件成功；截图接口返回空白，本次只记录实际控件交互，不作视觉验收。[Mac 记录与源码摘要](evidence/mobile-pair-gui/macos-network-config.json)

本批使用 `codex/batch/android-input-networks-*` 集中运行：两套 Android 普通测试包与独立 stock／guarded AVD、共享迁移与生命周期测试、三个桌面 runner 的真实 fixed-source native 编译／链接。原生库、GUI 和输入 helper 保持各自产物并记录同一源码版本。两套包 manifest 新增网络配置和 v2 迁移样例 SHA-256，正式 Release 与商店提交不在此批内。

源码 `040eb26` 已启动[集中运行 42158644225](https://github.com/Luck9Star/herdr-pocket/actions/runs/42158644225)。首个 macOS job 在分配 runner 前取消，注解为 `The configuration 'macos-14-arm64-us-default' is not supported`，没有编译步骤。2026-11-06 按 Context7 library → docs 核对[官方镜像表](https://github.com/actions/runner-images/blob/main/README.md)和[退役公告](https://github.com/actions/runner-images/issues/13518)，将余下的 `macos-14` 工作流固定为 `macos-15` arm64。原生候选增加仅 Mac 的 `codex/native-macos/**` 补验入口，避免重跑 Android 与其他已完成任务。runner 系统版本和应用最低运行版本分别记录。

## 下一步

先根据本批结果修复 Flutter 授权与输入驱动及新增模型回归，再完成设备安全存储与原生节点适配，打通显式 overlay 绑定下的配对接入、看板与持续观察。随后完善跨网络手机标签、断线／迟到数据和输入恢复，反馈到 Penpot 的连接受阻与配置迁移页面。桌面真实分屏和独立焦点排在手机闭环之后。没有真机或网络证据的格子继续标为未验证。
