# Flutter 普通 SSH 自然结束的本机关闭结果

同一 390×844 视口和默认 Widget 测试字形下，远端静默关闭后，修复前留在认证页并显示「远端 shell 已结束（退出码 未知）。」，修复后进入结果页并显示「本机已断开」。两次都观察到一次密码认证、一次 PTY、零终端输入，以及服务端在清理夹具前观察到客户端传输停止。修复版另有五条实际 TCP 回环，以及 390×844 和 980×780 两次独立复检。每张图片均为 Flutter Widget renderer 导出的原始 PNG，设备像素比为 1。证据范围为本地渲染与 SSH 回环。 [结构化证据](observations.json) · [SHA256 清单](SHA256SUMS)

## 同条件修复前后

| 场景 | 修复前 | 修复后 |
| --- | --- | --- |
| Android 布局变体，390×844。服务端关闭会话通道，未发退出状态码或信号 | [结果原图](comparison/before-390-silent-close.png) · 「远端 shell 已结束（退出码 未知）。」 · 预期「本机已断开」的用例失败 | [结果原图](comparison/after-390-silent-close.png) · 「本机已断开」 · 用例通过 |

两张图均有方块字形，文字取自同次运行对实际应用 Text 节点的读回。两份附录图来自更早的 390×844 可读字形探查，工作副本的页面文件与修复前基线同一 Git blob，探查目录缺少不可变的完整运行版本标记。该探查记录了一次认证、一次 PTY、一次 shell 请求及服务端关闭通道。客户端传输停止和零输入计数在当时未采集。 [早期静默关闭](historical/390-silent-close.png) · [早期退出状态码 0](historical/390-exit-status-close.png)

## 修复后的实际回环

| 视口与入口 | peer 发出的结束消息 | 修复前同条件原图 | 修复后结果页 | 用户实点返回后 |
| --- | --- | --- | --- | --- |
| 320×640，Android 布局变体，终端可见 | 无 | | [结果](fixed/320-silent-close.png) | [首页](fixed/320-silent-returned.png) |
| 390×844，Android 布局变体，终端可见 | 无 | | [结果](fixed/390-silent-close.png) | [首页](fixed/390-silent-returned.png) |
| 390×844，Android 布局变体，终端可见 | `exit-status` 0 | | [结果](fixed/390-exit-status-close.png) | [首页](fixed/390-exit-status-returned.png) |
| 390×844，Android 布局变体，先切到看板 | 无 | | [重开普通 SSH 后的结果](fixed/390-dashboard-silent-close.png) | [首页](fixed/390-dashboard-silent-returned.png) |
| 980×780，Linux 布局变体，终端可见 | `exit-signal` TERM | | [结果](fixed/980-exit-signal-close.png) | [首页](fixed/980-exit-signal-returned.png) |

五个用例均从首页实点普通 SSH，独立核对 peer 指纹，完成密码认证并开启 PTY。真实结果页的返回按钮五个采样点均可命中，点击后原首页显示「本机已断开」。静默关闭只显示本机关闭和清凭据。状态码 0 和 TERM 分别由夹具发出，两个场景均增加「远端已报告结束」。看板场景确认关闭时看板未被替换，也没有提前插入结果，重开普通 SSH 后才看到结果页。应用内核对终端退休、输入焦点释放及密码与口令清空。每个用例的服务端计数为一次密码认证、一次 PTY 请求、一次 shell 请求及零终端输入。服务端先关闭会话通道，再在夹具主动清理前观察到客户端传输停止。

独立复检使用同一修复源码和同一尺寸。390 静默与 980 信号复检均通过，返回按钮命中及边界和上表一致。复检图使用默认 Widget 测试字形，和上表可读字形图不做字形或像素差对比。上表字体文件的具体哈希未随原始运行留存。 [390 复检结果](independent-recheck/390-silent-close.png) · [390 复检返回](independent-recheck/390-silent-returned.png) · [980 复检结果](independent-recheck/980-exit-signal-close.png) · [980 复检返回](independent-recheck/980-exit-signal-returned.png)

## 主动断开与本机失败的证据边界

| 场景 | 本批原图 | 核对结果 |
| --- | --- | --- |
| 在应用内主动点「断开」 | | 同一关停回归验证静默和远端报告分支，并覆盖主动关闭后的宽窄切换。历史同尺寸原图见 320×640、390×844 的主动断开归档。 [主动断开原图](../flutter-mobile-remote-close-layout-20261120/README.md) |
| 自然结束后本机关停失败，即使远端已发 `exit-status` 0 | | 390pt 模拟本机关停失败。结果页显示「本机连接关闭失败」，凭据仍清空，返回入口仍可点击。 |
| 旧一轮关闭完成时新一轮已开始 | | Widget 夹具模拟异步回调交错，确认旧一轮结果无法覆盖新的失败结果。 |

## 源码与复核

- 基线为 `a1af87473bcf939664943108761cb215a7bdde42`。较早探查关联的 `c5aa64a0c9703d0494f5694ec0028018f7f2a0b8`、诊断分支基线 `db00510f5122534af809978451d19fa043f64e98` 和这次归档父提交 `f6b62f21958b2060e4104d8b935ef70c13adbe55` 的 `direct_ssh_page.dart` 都与基线同一 Git blob。
- 修复为 `3efed917af321a9c13946d6ff95b88a1fd5fd8a4`，集成为 `3676a43acba31877f9551937b08335017cddd722`。两者 Flutter 生产源码树相同。修复将自然关闭接入既有本机关停路径，按本地关闭确认和退出报告分别展示结果，并将等待返回的通知绑定到该轮关停编号。源码差异和新增回归集中于 `validation/flutter/lib/direct_ssh_page.dart` 与 `validation/flutter/test/direct_ssh_shutdown_test.dart`。
- 归档时将两处临时 app 的页面文件与 Git blob 逐字节比对。最初五个修复后用例的十张结果及返回图均与原采集摘要的哈希吻合。又独立检查十八张 PNG 的尺寸、块 CRC、文本与 EXIF 元数据，并逐张查看可见内容。图中出现的用户名、地址及分配端口均来自隔离回环夹具。归档只保留原图、白名单计数与实际界面读回。
- 修复源码的关停回归运行确认 34 项通过。原执行同时记录标准 Flutter 测试 655 项通过、41 项跳过。跳过项未计入通过数。

在仓库根目录核对文件，再用 Flutter 3.47.9 复跑集成版本的关停回归。生成的项目位于临时目录。

```sh
(cd docs/evidence/flutter-natural-ssh-local-outcome-20261120 && shasum -a 256 -c SHA256SUMS)

work="$(mktemp -d)"
mkdir "$work/source"
git archive 3676a43acba31877f9551937b08335017cddd722 | tar -x -C "$work/source"
(cd "$work/source" && python3 validation/flutter/tool/ci.py prepare --destination "$work/app")
(cd "$work/app" && flutter pub get && flutter test --no-pub test/direct_ssh_shutdown_test.dart)
```
