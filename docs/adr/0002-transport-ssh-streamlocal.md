# ADR-0002 · 传输用 SSH direct-streamlocal，不做 relay 优先

状态：已接受（2026-10-29）

## 背景

herdr 只监听 unix socket。客户端到达它有三条路：SSH streamlocal、SSH exec + 主机转发器、主机 relay（HTTPS+WS）。

## 决策

主路径用 SSH `direct-streamlocal@openssh.com` 直连 socket；**不保留 exec+socat/python 兼容回退**；relay 作为可选的第二后端（若做），不与主路径混在一条代码路径里。

## 理由

1. 零主机依赖：只要 sshd 允许 socket 转发，不需要装任何工具。
2. 隐私最好：没有中间进程、没有额外端口、没有额外鉴权层要设计。
3. Heeler 的 ADR-0011 已经证明这条路在 libssh2 上可行；dartssh2 4.x 也支持。
4. 保留两条传输路径的代价是永久的：双份配置、双份错误处理、双份测试面（Heeler ADR-0002 → 0011 的演进就是被这个逼着收敛的）。

## 后果

- 服务器禁用 `AllowStreamLocalForwarding` 的机器不可用；失败只能报一条合并原因（附 `test -S` 只读诊断）。
- 每请求要开一个 channel（socket 一次连接一请求）→ 需要客户端侧做请求合并与缓存。
- 文件、Git diff 等"主机侧能力"不能靠直连白拿；要么走 exec（按需，不常驻），要么做可选 relay。
