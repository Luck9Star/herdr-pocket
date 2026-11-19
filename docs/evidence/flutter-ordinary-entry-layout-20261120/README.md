# Flutter 普通 SSH 桌面接入与认证布局

## 画面来源

- [before](before/) 来自 `99f73f35793fc8117b61bf2482f38e9fe771173d`。[after](after/) 来自本提交。两批都从首页按实际控件进入，使用 Paramiko 回环探测，保存 1440×900、980×780、700×900 的选择、目标、目标聚焦、核对、密码和已有私钥共 18 张原图。两批截图测试都未点击连接，没有账户认证或 PTY。
- [geometry.json](geometry.json) 对照 [冻结 SVG 生成源](../../../design/penpot/direct-ssh-desktop.mjs) 的 geometry。修复后 234 个锚点均在 2pt 内，最大偏差 0.5pt。桌面默认侧栏宽 224／224／64pt，阅读列宽 560／560／556pt。
- [选择页首批证据](chooser-after/) 来自 `8d1f2f251caa6d0899310df45a441761a035fb16`。最终版量测环境为 macOS Flutter 3.47.9 headless widget renderer、1× 像素比、Arial Unicode 和内置图标／终端字体。测试模拟 Linux 控件渲染。AppKit 安全字段另行验证，见下文。

## 可点击性和回归

- 实际按下三档侧栏展开／收起、选择页的四个导航和返回入口。测试还覆盖目标页返回选择页、Tab 从地址切到用户名和端口、端口最多五个数字与超范围禁用、确认前隐藏凭据、核对显示完整 SHA256、取消后需重探、私钥未完整时禁用连接，以及从认证页到设置再回到终端入口后的凭据清空。
- [Widget 用例](checks/regression.log) 47 项通过、4 项按条件跳过，含 320／390 安全区和指纹换钥锚点、三宽 SSH 返回、跨宽度原会话、双标签焦点、连接退役和 macOS secure field 的 Dart bridge。桌面保留旧信任的回环用例观察到零认证，真实加密 PEM 和口令回环观察到 [一次公钥认证和一个 PTY](checks/encrypted-peer.log)。
- [本机 AppKit 探针](checks/appkit-probe.json) 37 项通过，覆盖真实 `NSSecureTextField` 编辑器、焦点与 Flutter 方法编解码。Widget bridge 使用模拟平台通道。本机仅安装 Command Line Tools，窗口级 XCUITest 和系统辅助功能树留待托管 Xcode 验证。
- [基线键盘测项](checks/base-keyboard.log) 的独立失败同样出现在本批首次回归。该用例只注入了 shell，未注入 transport/socket，却要求本机已断开成功。它不计入上述 47 项，保留基线日志供单独修复。
- 本批覆盖到认证流程和已有返回路径。冻结稿中的桌面活动终端、连接中看板／网络／设置和在线侧栏状态另行验收。

## 从干净检出复跑

从仓库根目录使用 Flutter 3.47.9、Node ≥20 和 macOS 系统 Arial Unicode 字体。脚本准备独立临时工程和一次性回环服务。

```sh
evidence="$PWD/docs/evidence/flutter-ordinary-entry-layout-20261120"
work="$(mktemp -d)"
python3 validation/flutter/tool/ci.py prepare --destination "$work/app"
(cd "$work/app" && flutter pub get)
node design/penpot/direct-ssh-desktop.mjs "$work/desktop.svg" "$work/design"
python3 -m venv "$work/venv"
"$work/venv/bin/python" -m pip install 'paramiko==4.0.0'
"$work/venv/bin/python" "$evidence/run-evidence.py" "$work/app" "$work/design/geometry.json" "$work/pixels" \
  --verify choose,target,target-focused,trust,password,private-key
(cd "$evidence" && shasum -a 256 -c SHA256SUMS)
```

截图命令应报告 `AUTH=0, PTY=0, PNG=18`，量测以 `ANCHOR` 开头。要只量测已有实现的差距，省略 `--verify`。本机 AppKit 可单独复跑。

```sh
python3 validation/flutter/native/apple/tests/run_secure_credential_probe.py \
  --flutter-sdk "$(dirname "$(dirname "$(command -v flutter)")")"
```
