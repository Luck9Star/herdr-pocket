# S06：两条真实 SSH / herdr 观察连接

此显式验收复用 `run-ci.py` 的 Ubuntu loopback OpenSSH、临时密钥、隔离 XDG 根和两个真实 herdr 命名会话。默认测试与产品行为保持原样；入口在已注册的 `paired-gui-validation.yml`，无需先合并默认分支。

先以本次代码所在的 `codex/` 分支触发 stock 零写验证：

```sh
gh workflow run paired-gui-validation.yml --ref codex/design-parity-direct-ssh \
  -f s06_split=true -f s06_guarded=false
```

stock 通过后，以相同源码触发 guarded 验证：

```sh
gh workflow run paired-gui-validation.yml --ref codex/design-parity-direct-ssh \
  -f s06_split=true -f s06_guarded=true
```

第二条会调用现有 input-extension 构建，仍核对固定上游、补丁、二进制哈希与能力探针，不替换 stock 结论。两次均须回读 manifest 的 `sourceSHA` 与工件，不能只凭工作流绿灯判断。

实际路径为正常 `HostCatalogPage` 首页 → 两次资料/指纹审查与设备配对 → 两个主机标签各自的连接和目标选择 → 并排观察 → 显式恢复第一侧 → 两侧持续输出 → 换焦点 → 分别停止。两个 session 使用相同 pane ID、不同 terminal ID；每侧使用独立临时设备密钥和原样 `RemoteReadOnlyAdapter`，并核对自己终端中的不同固定文字与持续 delta。没有注入适配器或帧。

stock 要求两侧输入模式均不可用，所有尝试最终在两份远端 `received.bin` 中仍为零字节。guarded 要求 B 选中时仅 B 收到 `b`，换焦点且显式选择草稿后仅 A 收到 UTF-8 的 `Pocket测`（9 字节）；旧侧迟到输入、换焦点后未显式恢复的输入均不得增加字节。独立 runner 核对两次 sshd 认证指纹、原 terminal 绑定和两份精确远端字节，不能用 GUI 自报代替。

公开 manifest 只含固定检查布尔、计数、数字 PTY 证据和来源元数据。请求、授权响应、临时 PEM、原始日志与终端字节留在 runner 私有临时目录，不上传；测试结束撤销两份授权、删除新增密钥，原有 runner 终止自建进程。两个共享 PTY 均须无观测尺寸变化。

这属于真实 Flutter Widget 引擎和真实 SSH/herdr 协议的桌面宽屏验收。signer、主机目录与输入 journal 使用明确的测试内存实现，不证明原生桌面窗口、系统密钥存储/journal 落盘、手机、物理 IME 或跨网络运行。尚未执行的云运行不计通过。

本地安全检查：

```sh
python3 -m unittest discover -s validation/remote-harness -p test_s06_split_gui.py -v
actionlint .github/workflows/paired-gui-validation.yml
```

需安装 `validation/pairing/requirements.txt` 才能实际执行三项证据门槛测试；缺少依赖时会明确跳过。Flutter 用例仅由隔离 runner 设置 `HERDR_S06_*` 环境后运行，常规套会明确跳过。
