# 普通 SSH Android 设备 UI 验收

这是可显式运行的独立验收，不属于 herdr 配对测试。Flutter 使用实际 `main()`、首页「普通 SSH」、真实 DartSSH2 和 TerminalView；不注入 adapter、signer、frame 或平台 mock。当前目标是 runner 自建的 Android API 35 x86_64 模拟器，不访问物理手机或用户主机。

## 触发固定源码

[独立工作流](../../.github/workflows/direct-ssh-android.yml)保留 `workflow_dispatch`，并只对 `codex/acceptance/direct-ssh-android-*` 的 push 自动运行。新增工作流尚未进入默认分支时，可把待测的固定提交推到此约定验收分支；不需要先合并 main，也不会在普通开发分支自动运行。

工作流复用项目已钉住的 Flutter 3.47.9、候选补丁、SDK-only `integration_test` 准备/锁文件核验和[独占 AVD 包装器](with-android-emulator.sh)。不要用伪造 CI 环境在已连接用户设备的机器上运行设备 runner。

## 验收断言

1. 正常首页进入普通 SSH，空凭据不能连接；探测结果必须与本次临时服务器的完整 SHA256 指纹一致，经显式确认后才认证。
2. 账号密码只供本次内存认证，取得标准 SSH PTY/shell，在实际 TerminalView 通过正常 TextInput debug-client 提交 `hp-check`，点击页面 Enter 辅助键。
3. 服务端只有收到该命令后才返回绿色 ANSI `POCKET-ANDROID-SSH-OK`；设备扫描实际终端缓冲确认回显，并保存连接画面。
4. 页面点击「断开」后终端消失、凭据清空。设备测试保持存活，直到 runner 独立确认服务端 shell 已关闭并回传确认，防止把 driver 退出造成的关闭误记成 UI 断开。
5. 退出后清理本次 reverse、安装包、新增 forward、Flutter 进程和临时服务。

自动提交不等于真实输入法触控或组字验证。Paramiko peer 提供标准 session/PTY/shell 和受控回显，不执行输入，也不启动主机 shell；真实 `/bin/sh` PTY 的证据属于 Rust 传输测试。

## 共享夹具与 Tauri 复用

[DirectSshFixture](direct_ssh_fixture.py)复用已有 Paramiko Server，仅绑定 `127.0.0.1:0`。在同目录 Python runner 中：

```python
from direct_ssh_fixture import DirectSshFixture

with DirectSshFixture() as peer:
    # 给本次隔离 UI 使用 peer.port / username / password / fingerprint。
    # 经 adb reverse 把模拟器相同端口映射到该 loopback listener。
    # 通过 UI 提交 peer.marker + Enter 后验证 peer.echo_marker。
    assert peer.wait_for('markerReceived')
    # 必须由 UI 断开后，在 driver 仍活着时检查。
    assert peer.wait_for('sessionClosed')
    evidence = peer.snapshot()
```

`public_key` 为规范 OpenSSH 公钥；`fingerprint` 为 SHA256。`snapshot()` 只含固定布尔、连接计数和 PTY 尺寸，不输出密码、密钥或输入正文。`sessionClosed` 不会由夹具强制清理冒充。退出上下文关闭 listener、所有 transport/worker，并清除夹具对象上的密码引用。私钥和主机授权文件完全不参与。

## 证据与本地检查

公共 artifact 只含已白名单化的 `result.json`、无秘密的首页/连接后/断开后 PNG，以及 AVD 版本和生命周期记录。不上传 APK、认证 defines、原始输入或 Flutter 私有日志；临时认证文件与日志在清理时删除。调试 APK、公开 Release 和手机真机验收是独立交付。

Python 守卫及真实 loopback 协议测试可在安装 Paramiko 4.0.0 的隔离环境运行，无需 adb：

```sh
python -m unittest discover -s validation/remote-harness -p 'test_direct_ssh_android.py' -v
```

[设备集成测试](../flutter/integration_test/android_direct_ssh_test.dart)与[CI-only runner](flutter_direct_ssh_android.py)必须由实际云模拟器运行后，才可记录设备通过。本地解析、analyzer 和 loopback 测试不能代替该结论。
