# 核心流程覆盖清单

日期：2026-10-30。56 个状态画板 + START 导航；全部为交互设计状态，真实能力另行验证。

| 画板 | 状态 | 可点击出口 |
| --- | --- | --- |
| P1-empty | 随时接住下一步 | 开始配对 → P2-request；手动配置 → P2-manual；浏览演示看板 → P1-dashboard |
| P2-request | 添加这台手机 | 查看主机端步骤 → P2-helper；已有 SSH 凭据 → P2-manual；取消配对 → P1-empty |
| P2-helper | 核对后授权 | 主机端明确确认 → P2-authorized；拒绝授权 → P2-denied |
| P2-authorized | 主机已添加公钥 | 手机扫描响应码 → P2-scan；查看撤销说明 → P2-revoke |
| P2-scan | 扫描主机响应码 | 模拟扫描响应 → P2-review；相机不可用 → P2-camera；模拟错配或过期 → P2-invalid |
| P2-review | 先确认是谁 | 已核对来源，保存资料 → P2-ready；指纹与来源不符 → P4-fingerprint；取消并保留授权说明 → P2-unverified |
| P2-ready | 资料已保存 | 完成网络授权 → P5-auth；主动连接（演示） → P2-success；目标不可达 → P2-unverified |
| P2-success | 连接验证完成 | 进入主机会话看板 → P1-loading |
| P2-unverified | 已授权，尚未验证 | 检查网络 → P5-networks；查看撤销方式 → P2-revoke；返回接入资料 → P2-ready |
| P2-revoke | 只撤销这次授权 | 模拟主机确认撤销 → P2-denied；保留授权并返回 → P2-unverified |
| P2-camera | 相机暂不可用 | 手动输入 → P2-manual；重试相机 → P2-scan |
| P2-invalid | 无法使用这份响应 | 重新取得正确响应 → P2-scan；查看授权清理 → P2-revoke |
| P2-denied | 本次配对未完成 | 返回主机入口 → P1-empty |
| P2-manual | 手动添加主机 | 审查并保存 → P2-ready；返回扫码 → P2-scan |
| P1-dashboard | 今天的远端工作 | 打开待处理终端 → P3-observe；网络与主机 → P5-networks；桌面工作台 → D1-workspace |
| P1-stale | 主机状态待确认 | 主动重新连接 → P4-recovering；查看网络状态 → P5-networks；返回看板 → P1-dashboard |
| P3-observe | 先观察，再输入 | 进入逐键输入 → P3-direct；编辑草稿 → P3-draft；选择与粘贴 → P3-selection |
| P3-direct | 输入指向 agent-a | 收起键盘 → P3-keyboard-closed；改用草稿 → P3-draft；演示发送中断 → P4-unknown |
| P3-small | 小屏也能看清目标 | 收起键盘 → P3-keyboard-closed；回到标准手机 → P3-direct |
| P3-keyboard-closed | 键盘已收起 | 展开键盘 → P3-direct；组合键辅助 → P3-combo；跨网络标签 → P4-tabs |
| P3-draft | 先把话写完整 | 预览草稿 → P3-draft-preview；回到观察 → P3-observe；切换标签 → P4-tabs |
| P3-draft-preview | 检查要发送的内容 | 发送这段文本 → P4-sending；继续编辑 → P3-draft；取消发送 → P3-observe |
| P3-selection | 选择、复制与粘贴 | 预览多行粘贴 → P3-paste；复制后返回 → P3-observe |
| P3-paste | 确认粘贴到哪里 | 明确发送粘贴内容 → P4-sending；放入本地草稿 → P3-draft；取消粘贴 → P3-selection |
| P3-combo | 组合键已准备 | 发送 Ctrl+C（演示） → P4-received；取消组合键 → P3-direct；小屏键盘变体 → P3-small |
| P4-sending | 正在发送 | 演示服务端接收 → P4-received；演示结果未知 → P4-unknown；演示明确未发送 → P4-not-sent |
| P4-received | 服务端已接收 | 返回实时观察 → P3-observe；切换另一网络标签 → P4-tabs |
| P4-not-sent | 明确未发送 | 返回原目标草稿 → P3-draft；回到观察 → P3-observe |
| P4-unknown | 发送结果待核实 | 主动恢复并核实 → P4-recovering；查看连接诊断 → P5-networks |
| P4-recovering | 正在恢复当前画面 | 模拟新全量到达 → P4-restored；模拟指纹改变 → P4-fingerprint；模拟目标已退出 → P4-target-gone |
| P4-restored | 当前画面已恢复 | 核对后进入逐键 → P3-direct；继续观察 → P3-observe；返回看板 → P1-dashboard |
| P4-fingerprint | 主机指纹发生变化 | 查看原主机资料 → P2-manual；取消连接 → P1-stale |
| P4-target-gone | 原目标已失效 | 复制草稿并回看板 → P1-dashboard；查看原目标旧画面 → P1-stale |
| P4-tabs | 三个网络，三个上下文 | 打开暂停的 B 标签 → P4-hidden；返回 A 终端 → P3-observe；查看并发网络 → P5-networks |
| P4-hidden | 标签 B 正在刷新 | 模拟 B 新全量到达 → P4-b-ready；保持暂停返回 A → P3-observe |
| P4-b-ready | 当前焦点：agent-b | 回到 A 标签 → P3-observe；桌面分屏查看 → D1-workspace |
| P5-networks | 连接各有状态 | Tailscale 配置 → P5-ts；EasyTier 配置 → P5-et；ZeroTier 配置 → P5-zt |
| P5-ts | Tailscale 配置 | 查看待授权状态 → P5-auth；查看停用影响 → P5-impact；返回网络列表 → P5-networks |
| P5-et | EasyTier 配置 | 演示节点未就绪 → P5-node；停用前预览影响 → P5-impact；返回网络列表 → P5-networks |
| P5-zt | ZeroTier 配置 | 查看授权状态 → P5-auth；查看地址隔离限制 → P5-overlap；返回网络列表 → P5-networks |
| P5-auth | 等待网络授权 | 模拟授权完成，回接入 → P2-ready；保留待授权并返回 → P5-networks |
| P5-node | 网络节点未就绪 | 重新检查配置 → P5-et；查看其他网络 → P5-networks |
| P5-impact | 停用前看影响 | 确认停用此网络（演示） → P1-stale；取消并保留连接 → P5-networks |
| P5-overlap | 这个并发组合暂不可用 | 返回网络选择 → P5-networks |
| P6-export | 选择加密导出范围 | 设置口令并导出（演示） → P6-file；取消 → P1-dashboard |
| P6-file | 配置文件已准备 | 演示另一设备导入 → P6-import；返回看板 → P1-dashboard |
| P6-import | 先审查，再写入 | 保留现有，导入新增 → P6-done；预览替换在用项 → P6-conflict；模拟无法解密 → P6-invalid |
| P6-conflict | 替换会停止哪些连接 | 确认替换并停止连接 → P6-done；保留现有配置 → P6-import；演示提交失败 → P6-commit-failed |
| P6-invalid | 无法验证或解密 | 重新选择文件 → P6-import；取消导入 → P1-dashboard |
| P6-done | 配置已保存，等待核验 | 审查主机再主动连接 → P2-ready；返回看板 → P1-dashboard |
| P7-font | 字体与字符格诊断 | 查看手机终端示意 → P3-observe；返回看板 → P1-dashboard |
| D1-workspace | 远端工作台 | 把输入焦点移至 B → D1-focus-b；收窄窗口 → D2-narrow；模拟 A 断线 → P4-unknown |
| D1-focus-b | 输入焦点在 B | 焦点回到 A → D1-workspace；查看窄窗口 → D2-narrow；恢复手机标签布局 → P4-tabs |
| D2-narrow | 窄窗口，保留上下文 | 展开主机侧栏 → P1-dashboard；恢复宽桌面分屏 → D1-workspace；切换活动标签 → P4-tabs |
| P1-loading | 正在获取当前状态 | 模拟快照到达 → P1-dashboard；模拟失联 → P1-stale |
| P6-commit-failed | 配置提交失败 | 回到导入审查 → P6-import；查看原主机配置 → P2-manual |

## 共用输入与恢复规则

- 观察默认不发送；逐键提交文字一次发送；草稿需预览、显式发送，不补回车。
- 所有按键、组合键、IME提交与粘贴都绑定明确目标；切标签先释放组合状态。
- 结果未知不自动重试、不回填待发草稿；恢复新状态和 full 后默认观察。
- 布局、键盘和分屏只改变本地视口，不隐式修改远端共享 PTY。
- 配对成功节点为演示状态，不表示本轮操作过真实 authorized_keys。

## 可访问性与布局规格

- 主操作和辅助键目标不小于 44 × 44，主操作默认 48 高。
- 焦点可见；状态同时用文字、图标、颜色，禁用同时给理由。
- 手机从目标/模式、状态、主操作依序导航，桌面可轮转主机栏、标签、分屏与辅助操作。
- 360 / 390 / 430 手机视口及 800 / 1360 桌面视口分别建稿。
- 窄窗口收纳侧栏和分屏，保留各目标状态；终端长行由本地滚动/裁切处理。
- 原型中的终端文本是静态示意，字体、IME、cell、实际读屏支持留给运行组件验证。
- Penpot预览热点是设计审阅工具，不等同正式App的键盘或读屏实现。
