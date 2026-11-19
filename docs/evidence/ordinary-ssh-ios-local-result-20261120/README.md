# iOS 普通 SSH 本机断开回执验收

2026-11-20，Flutter 源码 `b3c1182b8860a0d1eda93f7402509938b836c715` 在 iPhone 11 / iOS 26.2 模拟器通过两个官方 XCTest 作业，覆盖密码、密码换钥、加密 OpenSSH Ed25519 私钥及加密私钥换钥四案。每作业执行 1 项 XCTest 并通过。Tauri 较早源码 `2e8c3557e2e51ae62b423f9e25a9f1fc5d72cecf` 的密码和手输加密私钥作业均在进入 SSH 协议前失败。四份原始 ZIP 按 Actions 公布的大小和 SHA-256 核对。各作业使用临时回环 SSH 对端。[逐文件索引](official-index.json)

| 作业 | 官方结果与来源 | 原始 ZIP |
| --- | --- | --- |
| Flutter R2 密码、密码换钥、加密私钥 | 通过 · [作业 135748357206](https://github.com/Luck9Star/herdr-pocket/actions/runs/44577362257/job/135748357206) · [工件 14558242724](https://github.com/Luck9Star/herdr-pocket/actions/runs/44577362257/artifacts/14558242724) | [9 项原件，585,955 字节](44577362257-14558242724.zip) |
| Flutter R2 加密私钥换钥 | 通过 · [作业 135748377946](https://github.com/Luck9Star/herdr-pocket/actions/runs/44577365059/job/135748377946) · [工件 14559260076](https://github.com/Luck9Star/herdr-pocket/actions/runs/44577365059/artifacts/14559260076) | [4 项原件，201,004 字节](44577365059-14559260076.zip) |
| Tauri R1 密码，尝试 2 | 失败 · [作业 135746345036](https://github.com/Luck9Star/herdr-pocket/actions/runs/44573407807/job/135746345036) · [工件 14558498583](https://github.com/Luck9Star/herdr-pocket/actions/runs/44573407807/artifacts/14558498583) | [仅脱敏结果，2,325 字节](44573407807-14558498583.zip) |
| Tauri R1 手输加密私钥，尝试 2 | 失败 · [作业 135745516595](https://github.com/Luck9Star/herdr-pocket/actions/runs/44573496445/job/135745516595) · [工件 14558906376](https://github.com/Luck9Star/herdr-pocket/actions/runs/44573496445/artifacts/14558906376) | [仅脱敏结果，2,033 字节](44573496445-14558906376.zip) |

## Flutter 连接、回显与关闭

| 案例 | 对端连接 | 原图与操作证据 |
| --- | --- | --- |
| 密码 | A → A。先探测，同一主机指纹经独立核对后才认证 | `ordinary-terminal.png` 和对应 OCR。开合系统键盘、看板往返、网络往返、设置往返共八项均保持 ID 2 的原会话，认证、PTY 和 shell 各一次，导航期间 0 字节输入 |
| 密码换钥 | A → B → B → B。拒绝 B，取消保留 A，显式重探、核对及确认 B 后才认证 | `key-change-review.png` 保存换钥阻断和两个操作选项。 `key-change-terminal.png` 的回显原屏保留展开的键盘 |
| 加密私钥 | A → A。错误口令在本机拒绝时仍只有原探测记录，正确口令后仅一次公钥认证 | `encrypted-key-terminal.png` 和对应 OCR。通过应用粘贴按钮填写临时 PEM，口令字段遮罩，密码和私钥的认证方式切换会清空旧字段 |
| 加密私钥换钥 | A → B → B → B。前三条均在认证前关闭，显式确认 B 后一次公钥认证 | `encrypted-rotation-review.png` 与 `encrypted-rotation-terminal.png`。临时 PEM 通过粘贴按钮填写；本组没有错误口令重试 |

四案探测或拒绝阶段的认证、PTY、shell 和收发均为零。每案末条连接独立记录一次成功认证、一次 PTY、一次 shell、恰好 9 字节输入和 102 字节输出。四案均主动断开，末条连接由对端记录为 `peer_eof`，并在驱动退出前关闭。测试核对本机回执、凭据清空及返回首页。两个加密案的 `returnedHome` 另在结果中单独列出。清理记录包括模拟器、应用、Flutter 工具、夹具和私有文件；两个加密案还核对临时凭据输入文件移除和剪贴板清空。原始日志未上传。[通过版本的 Flutter 用例](https://github.com/Luck9Star/herdr-pocket/blob/b3c1182b8860a0d1eda93f7402509938b836c715/validation/flutter/integration_test/ios_direct_ssh_test.dart) · [设备操作与返回断言](https://github.com/Luck9Star/herdr-pocket/blob/b3c1182b8860a0d1eda93f7402509938b836c715/validation/flutter/integration_test/direct_ssh_ui_steps.dart)

七张 828 × 1792 系统原图按原字节保留。四张终端图都核对了图像 SHA-256、同图 OCR 文件 SHA-256、终端及目标区域。原作业的 Tesseract 5.5.4 识别了合成回显标记与紧接的两行本次夹具词串，独立区域同时核对可见连接目标。两张审查图记录拒绝状态，`preconnect.png` 记录遮罩后的临时密码字段。原图 EXIF 只含色域和像素尺寸。图中可见的账号、地址、指纹和词串均来自临时夹具。[逐文件索引](official-index.json)

## Tauri R1 的两个停止点

- 密码作业在 iPhone 17 Pro Max / iOS 26.2 模拟器实际打开添加页及普通 SSH 目标表单，随后在 `ordinary_host` 的地址字段读回失败，错误为 `native_input_value_invalid`。清理前和清理后均记录 0 条对端连接、0 条连接事件，SSH 输入写入为 0。换钥未执行，无截图。
- 加密私钥作业在同类模拟器的 `encrypted_key_open_add` 停止，错误为 `native_home_navigation_failed`。配置的输入方式是 XCTest `nativeTypeText`，驱动尚未进入凭据界面或执行手输 PEM。清理前后同样记录 0 条对端连接、0 条连接事件与 0 远端写入。密码和换钥未执行，无截图。

两次失败清理均移除了模拟器并关闭夹具、删除私有文件。手输案另记录临时密钥清空且未上传原始日志。Flutter 的粘贴结果只覆盖该输入路径。实体设备、物理键盘、真实中文输入法组字和真实跨网仍待验收。

## 校验及后续运行入口

在本归档目录执行以下命令。原件解压到新的临时目录，退出码为 0 表示四份 ZIP 及十五个内部成员的 SHA-256 均匹配。

```sh
set -e
shasum -a 256 -c SHA256SUMS
originals="$(mktemp -d)"
members="$PWD/SHA256SUMS.members"
for archive in *.zip; do
  unzip -t "$archive"
  unzip -q "$archive" -d "$originals/${archive%.zip}"
done
(cd "$originals" && shasum -a 256 -c "$members")
```

已以 Flutter 原作业源码上的发布门重新校验两份成功原件，按文件比较均与原始 ZIP 字节一致。两份 Tauri 失败件各保留原始 `result.json`。维护者可从后续源码 `c5aa64a0c9703d0494f5694ec0028018f7f2a0b8` 的工作流或对应运行入口查看后续结果，本归档仅记录表中四次作业。[后续工作流](https://github.com/Luck9Star/herdr-pocket/blob/c5aa64a0c9703d0494f5694ec0028018f7f2a0b8/.github/workflows/direct-ssh-ios.yml) · [Flutter 密码及单独私钥](https://github.com/Luck9Star/herdr-pocket/actions/runs/44584233340) · [Flutter 私钥换钥](https://github.com/Luck9Star/herdr-pocket/actions/runs/44584305176) · [Tauri 密码](https://github.com/Luck9Star/herdr-pocket/actions/runs/44583882651) · [Tauri 手输私钥](https://github.com/Luck9Star/herdr-pocket/actions/runs/44583969020)
