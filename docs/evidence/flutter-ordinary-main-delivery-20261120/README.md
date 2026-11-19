# Flutter 普通 SSH 会话导航与关闭回执

2026-11-20，在独立临时工程复跑 `b491829ca8a4a64286b17c40470ce448fcd44d15`。其 Flutter `lib` 与集成提交 `f440c36611ab89b35bf7762044532ce600f2c34b` 的 Git tree 均为 `6ce0937754ccc17fb5a5691531531d30570ad3d5`。AppKit 安全输入实现和探针也逐文件一致。[Flutter 普通 SSH 入口](../../../validation/flutter/lib/direct_ssh_page.dart)

## 本地复跑

| 验证 | 结果 |
| --- | --- |
| 生产代码与 Android、iOS、Linux 集成测试入口 | Flutter 3.47.9 的隔离工程 analyzer 无问题 |
| 关停、键盘、布局、目录、网络及导入入口的 Widget 回归 | 58 通过，8 条需外部夹具的用例跳过 |
| 仓库普通 SSH 回环夹具 | 48 通过，涵盖密码、普通和加密 PEM、换钥拒绝和显式确认，以及关闭后清凭据、回到首页 |
| 另启隔离回环后复跑桌面认证、断开、宽度切换及认证前取消 | 18 通过，2 个宽屏备用入口用例条件跳过 |
| AppKit `NSSecureTextField` 和 Flutter 编解码探针 | 39 项通过，包含新私钥口令标签、字段撤除与清值。作用范围为本进程 AppKit 控件和方法消息编解码 |

桌面 Widget 渲染复跑 700×900、980×780、1440×900。每档使用独立 Paramiko 回环连接。三次认证、三次 PTY、三次输入流 EOF。看板、网络和设置往返后保持原终端、滚动和焦点，每条连接只收到返回后手动提交的一个 `Q`，均见回显。三档分别实测默认侧栏 64／224／224pt。126 个冻结布局锚点最大偏差 2pt。下列图片均为本次 Flutter Widget renderer 1× 原图。[终端 1440](terminal-1440.png) · [看板 700](board-active-700.png) · [网络 980](network-active-980.png) · [设置 1440](settings-active-1440.png)

自然结束实测五案包括 320 和 390 静默关通道、390 明确退出状态码 0、390 切到看板再静默关通道、980 明确 TERM 退出信号。每案一次认证、一次 PTY、一次 shell、零输入，对端在夹具清理前观察到客户端传输 EOF。两类明确退出报告才显示远端一句，五案均清空密码和口令。留在看板时，回执等用户重新打开普通 SSH 后才显示。单测模拟本机关闭失败和关停异步交错，核对结果页和首页独立显示失败并仍清空凭据。[关停回归](../../../validation/flutter/test/direct_ssh_shutdown_test.dart)

下列效果为相同 Flutter 生产代码树在 `3efed917af321a9c13946d6ff95b88a1fd5fd8a4` 采集的原图，使用可读中文字形。当前复跑使用默认 Widget 测试字形，再用同次界面文字和对端日志核对结果。[320 静默关闭](320-silent-close.png) · [390 明确退出状态码](390-exit-status-close.png) · [390 返回首页](390-silent-returned.png) · [980 明确退出信号](980-exit-signal-close.png) · [原图 SHA-256](SHA256SUMS)

## 历史设备工件

以下模拟器作业各覆盖密码、加密 OpenSSH Ed25519、密码换钥和加密私钥换钥四案，包含隔离 SSH 对端接收终端输入、关闭和设备原图。作业的成功记录、提交 SHA 和原工件摘要已通过 GitHub Actions 核对。各行使用表中历史源码。

| 环境与源码 | 官方原件 |
| --- | --- |
| Android API 35 x86_64 · `2e8c3557e2e51ae62b423f9e25a9f1fc5d72cecf` | [密码与换钥](https://github.com/Luck9Star/herdr-pocket/actions/runs/44573407155/artifacts/14555283420) · [加密私钥](https://github.com/Luck9Star/herdr-pocket/actions/runs/44573506017/artifacts/14556390968) · [加密私钥换钥](https://github.com/Luck9Star/herdr-pocket/actions/runs/44573516056/artifacts/14554934904) |
| iPhone 11 / iOS 26.2 模拟器 · `b3c1182b8860a0d1eda93f7402509938b836c715` | [密码、密码换钥与加密私钥](https://github.com/Luck9Star/herdr-pocket/actions/runs/44577362257/artifacts/14558242724) · [加密私钥换钥](https://github.com/Luck9Star/herdr-pocket/actions/runs/44577365059/artifacts/14559260076) |

本提交重新验证的是 Widget 引擎和隔离回环。新源码的 Android／iOS 模拟器、桌面原生窗口、实体手机、真实输入法和实际跨网络连接仍待运行验证。AppKit 探针记录的安全字段检查独立于系统辅助功能树和原生窗口验收。
