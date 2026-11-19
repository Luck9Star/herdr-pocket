# Flutter 320pt 普通 SSH 远端结束反馈

基线 `2e8c3557e2e51ae62b423f9e25a9f1fc5d72cecf` 与本提交在同一 Flutter 3.47.9 widget renderer、同一 R23 SFNS／PingFang／ProbeNerd 字体条件下运行。真实点击连接、断开和返回首页。每批 320×640、390×844 各两种 SSH 情况，共 4 次真实认证、4 个 PTY 和 4 次服务连接关闭。只有 `remote` 夹具在 stdin EOF 后发送 SSH exit-status。

320pt 收到远端退出报告时，反馈卡由 80pt 调整为设计的 84pt，下面五处实际控件的纵向偏差由 −4pt 归零。320pt 常规关闭和 390pt 两种关闭路径量测一致。完整坐标、原图与回环日志已保存。 [基线原图](before/) · [修复原图](after/) · [逐点记录](comparison.json)

Android／iOS widget 回归另外模拟本机关闭失败，即使曾收到远端退出报告也保持失败提示、原 66pt 卡片及返回入口。对应测试 25 项通过。画面来自 widget renderer。 [关闭回归日志](shutdown-widgets.log)

从仓库根目录复跑定向回归。

```sh
work="$(mktemp -d)"
python3 validation/flutter/tool/ci.py prepare --destination "$work/app"
(cd "$work/app" && flutter pub get && flutter test --no-pub test/direct_ssh_shutdown_test.dart)
```
