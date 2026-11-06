# herdr-pocket

herdr-pocket 是手机优先的远端 herdr 图形客户端原型，目标覆盖 iOS、Android、Windows、macOS 和 Linux。桌面共享主机、会话和终端模型。项目独立于 herdr 官方，具体许可证待依赖和分发审查后确定。

**当前进度 · 2026-11-06**　Flutter 与 Tauri 在同源 `040eb26` 的 Android API 35 云模拟器完成 **配对审查 → 设备公钥认证 → 主机与会话看板 → 持续观察 → 主动停止**，原版用例远端输入为 0。Tauri 受保护输入通过；Flutter 普通包构建成功，受保护用例和新增回归仍有失败。[公开原型分支](https://github.com/Luck9Star/herdr-pocket/tree/codex/core-prototype-validation) · [当前实现与验证记录](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/18-mobile-network-profiles.md)

## Android 测试包

两份包都来自 `040eb26ba7c31e071048616a39591e17c74c99ab`，已下载核对源码、APK SHA-256、ABI、共享样例与原生声明。

| 应用 | 下载 | 实际结果 |
| --- | --- | --- |
| Flutter，arm64-v8a / armeabi-v7a / x86_64 | [debug APK](https://github.com/Luck9Star/herdr-pocket/actions/runs/42158644225/artifacts/13476846146) | 只读配对、看板、full/delta 和停止通过；受保护用例停在响应来源复选框确认；新增回归有测试代码错误，渲染回归 10 项通过 |
| Tauri，arm64-v8a | [debug APK](https://github.com/Luck9Star/herdr-pocket/actions/runs/42158644225/artifacts/13475774527) | 只读与受保护输入用例通过；逐键、草稿和隐藏后显式恢复得到两笔匹配回执，共 10 bytes；991 次 PTY 取样保持 119×40 |

GitHub artifact 需登录下载，保留期 14 天。完整摘要、解包与测试步骤见[下载说明](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/18-mobile-network-profiles.md#android-下载与实际结果)。本批整体状态为 cancelled，含退役 Mac runner 取消及 Flutter job failure；Mac 定向补验单独通过。后续修复 `61a6b09` 不在上述 APK 中，新 Flutter 回归尚未再跑。[逐项原始证据](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/evidence/mobile-pair-gui/network-config-build-040eb26.json)

## 手机实现与设计

- 两套 GUI 已接入独立网络配置、主机绑定、加密迁移 v2 和本机字号。停用网络仍可完成本地配对审查；真实连接检查桥接可用性，不回退到普通网络。导入网络生成新 ID、默认停用，字号默认不覆盖。Mac 已实际完成系统文件导出、解密预览与导入，测试应用已关闭。
- Penpot v2 沿用用户选定的 Tech Indigo／Slate，现有 30 个画板。网络列表、修改影响、迁移审查和导入结果已保存，重载读回并实际点击关键往返流程。[设计与覆盖清单](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/design/README.md) · [打开手机网络原型](https://design.penpot.app/?screen=viewer&file-id=b55064db-d93d-80f9-8008-ddd22e6d398f&page-id=7a22df08-251d-8016-8008-de03541c11da&section=interactions&frame-id=b9d502c0-514c-80a9-8008-e7033d91f34d)
- EasyTier 新节点生命周期接口已在 Linux、Windows、macOS 完成固定源码编译、链接和九个符号加载；真实节点启动、设备身份存储、GUI overlay 路由与三网并发仍待完成。Tailscale、EasyTier、ZeroTier 五端矩阵分别验收。
- 原版 herdr 维持只读，输入使用隔离候选扩展验证。发送结果未知时锁定输入，取得原目标新 full 并人工核实后才能继续。布局变化不隐式修改共享 PTY 尺寸。[产品设计](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/05-product-design.md)

真实手机 IME、触控、相机、iOS 签名安装和三网设备运行继续标为未验证。Flutter 与 Tauri 保留对照，先判断正确性，再比较性能和维护成本。后续按手机跨网接入与恢复、桌面分屏的顺序推进，集中构建，测试产物与正式发布分开。[实施顺序](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/04-roadmap.md) · [许可与分发审查](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/17-license-and-distribution-review.md)
