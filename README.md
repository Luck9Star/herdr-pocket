# herdr-pocket

herdr-pocket 是手机优先的远端 herdr 图形客户端原型，目标覆盖 iOS、Android、Windows、macOS 和 Linux。桌面共享主机、会话和终端模型。项目独立于 herdr 官方，具体许可证待依赖和分发审查后确定。

**当前进度 · 2026-11-06**　配对审查、设备密钥、主机与会话看板、持续观察已接入 Flutter 和 Tauri GUI，两条路线此前均在 Android API 35 走通只读闭环。本批继续接入逐键／组合键、主机受理回执、隐藏恢复和加密主机资料迁移。Tauri 的受保护输入用例通过，Flutter 新包构建和回归通过，Android GUI 仍有失败。[公开原型分支](https://github.com/Luck9Star/herdr-pocket/tree/codex/core-prototype-validation) · [本批实现与验证记录](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/16-mobile-input-and-config.md)

## Android 测试包

| 应用与源码 | 下载 | 当前证据 |
| --- | --- | --- |
| Flutter `007e20d` | [debug APK](https://github.com/Luck9Star/herdr-pocket/actions/runs/42147341123/artifacts/13472225200) | 普通应用构建、analyzer、100 项测试、10 项渲染回归通过，另有 1 项跳过。原版 AVD 在授权确认处超时，受保护用例被既有设备保护拦截 |
| Tauri `8daf1bc` | [arm64 debug APK](https://github.com/Luck9Star/herdr-pocket/actions/runs/42141054727/artifacts/13466854945) | API 35 配对、持续观察、单键、草稿与隐藏后恢复通过。两笔匹配回执，接收端精确收到 10 bytes，共享 PTY 814 次取样保持 119×40 |

两包已下载核对源码、APK SHA-256、共享样例与随包声明。GitHub artifact 需登录下载且有保留期限。解包步骤、完整摘要及各平台待验项见[下载说明](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/16-mobile-input-and-config.md)。此前同源 `307c863` 的双路线只读闭环和测试包继续保留在[历史验收记录](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/15-mobile-gui-validation.md)。

## 已保存的设计与当前边界

- Penpot v2 沿用 Tech Indigo／Slate，新版共 26 个画板、149 条有效交互，补齐受理回执、隐藏恢复、组合键和导入冲突。替换冲突链已实际点击，其他分支按读回与手点分别记录。Penpot 链接沿用现有团队权限。[设计入口与截图](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/design/README.md) · [覆盖清单](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/design/v2-coverage.md)
- 手机从公开配对请求、主机确认和响应审查进入看板，再选定 pane 持续观察。源码已接入设备独立密钥与加密主机资料迁移，完整系统文件选择、真实相机／IME／触控和跨重启身份仍需验收。[配对和测试步骤](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/14-mobile-pairing-workbench.md)
- 原版 herdr 0.9.5 维持只读，输入使用隔离候选扩展验证。发送结果未知时锁定输入，取得原目标新 full 并人工核实后才能继续。布局变化保持远端共享 PTY 尺寸。三网逐平台能力与前台并发继续按矩阵推进。[产品设计](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/05-product-design.md)
- 已补固定字体来源和许可全文，Flutter 最新包内材料逐字核对。完整依赖清单、项目许可证、签名和正式发行仍待完成。[许可与分发审查](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/17-license-and-distribution-review.md)

继续以手机为先，集中修复当前失败、接入网络配置与跨网络标签，再完善桌面分屏。Flutter 与 Tauri 保留对照，框架选型依据终端正确性和设备实测。云构建按功能批次执行，测试产物与正式发布分开。[实施顺序](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/04-roadmap.md)
