# ADR-0002 · SSH streamlocal 为唯一首发 RPC 路径

状态：已接受设计（2026-10-29）；目标上游为 herdr 0.9.5，待 M0.5 记录端到端验证。

## 背景

已有调研记录中的 herdr API 使用 unix socket。移动和桌面客户端的首发远端路径均通过 SSH 到达该 socket。Windows GUI 的加入不等于支持 Windows 本地 herdr 服务端。终端 observe 是远端 CLI 的另一种输出路径，不能把它和 socket RPC 混成一条连接。

## 决策

普通 RPC 使用 `direct-streamlocal@openssh.com`：**一请求一 channel**。事件订阅使用独立长连接。每个可见终端通过无 PTY 的 SSH exec channel 运行 `herdr terminal session observe`。

首版远端连接不提供 exec+socat/python 的 RPC 回退，也不实现第二个 relay 后端。用户已确定首版只连接远端；本地 socket adapter 是后续扩展，不进入首版 API/验收，也不引入本地 daemon/WSL 管理。减少传输分支，让错误归因、资源清理与安全检查可验证。客户端请求 ID 不改变服务端连接生命周期，不提供自动重试写入的依据。

## 理由

dartssh2 的 `forwardLocalUnix` 可用于建立 streamlocal channel。该路径不额外要求 socat/python 或常驻应用网关，但仍要求 SSH、herdr、正确权限及 socket 可达。参考实现已展示类似路径；本项目的库版本与五端运行环境仍要独立验证。

## 主机前提

- sshd 允许所需的 streamlocal 转发；SSH 用户能够访问 herdr socket。
- 终端观察要求 exec 权限及可定位的 herdr CLI；客户端明确配置/探测路径，不假设非交互 shell 的 PATH 与桌面相同。
- 所有路由在传递认证凭证之前验证 host key；SSH 接通不代表 herdr 能力可用。

## 失败与恢复

channel open 失败不能可靠区分 socket 不存在、权限、服务状态或转发策略。可用一次受控、正确引用路径的 `test -S` 辅助诊断，但“文件存在”也不能证明 daemon 活跃或转发被允许。

读取可在重新建立连接后刷新；写入超时或断线进入“结果未知”，不自动重放。事件断开后按订阅启动、快照读取与失效通知的协议重新同步。终端重开等待新 full 帧，旧连接帧不得进入新画面。

## 后果

需限制 RPC channel 并发、合并重复读取、及时关闭 observe 和失效连接。文件、Git diff 等能力后置，未来若加入远端命令必须独立约束参数与权限；不以“本来就有 SSH”为由自动扩大执行范围。

详见[架构运行契约](../02-architecture.md)及[可靠性边界](0004-mvp-reliability-boundaries.md)。
