# Tauri v2 实际云构建

2026-10-30。源码 `224d143f1a545fc64257f6cc46a2ba177c675237` 的 [run 41014249412](https://github.com/Luck9Star/herdr-pocket/actions/runs/41014249412) 已完成并成功，5 个平台 job 全部成功。各 job 的原始日志均确认 18 个 JS 测试、6 个 Rust core 测试及实际打包步骤通过；`run.json` 和 `artifacts.json` 保存 GitHub 实际返回结果。原始 job 日志逐字节保存为 `.log.gz`（保留上游 CRLF、ANSI 与空白），解压后 digest 另记在汇总的 `rawLogDigests`。

| 目标 | Job | 可获取 artifact | 本次设备结论 |
| --- | --- | --- | --- |
| Android arm64 debug | [123926957967](https://github.com/Luck9Star/herdr-pocket/actions/runs/41014249412/job/123926957967) | [12958971702](https://github.com/Luck9Star/herdr-pocket/actions/runs/41014249412/artifacts/12958971702) | 未验证 |
| Windows x64 | [123926958148](https://github.com/Luck9Star/herdr-pocket/actions/runs/41014249412/job/123926958148) | [12958723079](https://github.com/Luck9Star/herdr-pocket/actions/runs/41014249412/artifacts/12958723079) | 未验证 |
| macOS arm64 | [123926958205](https://github.com/Luck9Star/herdr-pocket/actions/runs/41014249412/job/123926958205) | [12958494516](https://github.com/Luck9Star/herdr-pocket/actions/runs/41014249412/artifacts/12958494516) | 本审阅代理未启动；另由主代理验收 |
| iOS arm64 simulator | [123926958214](https://github.com/Luck9Star/herdr-pocket/actions/runs/41014249412/job/123926958214) | [12958861638](https://github.com/Luck9Star/herdr-pocket/actions/runs/41014249412/artifacts/12958861638) | 仅模拟器归档构建，非真机安装 |
| Linux x64 | [123926958270](https://github.com/Luck9Star/herdr-pocket/actions/runs/41014249412/job/123926958270) | [12958693305](https://github.com/Luck9Star/herdr-pocket/actions/runs/41014249412/artifacts/12958693305) | 未验证 |

查询时 5 个 artifact 均未过期，计划 2026-11-13 到期，下载需要仓库权限。除 Mac 外未逐一下载和重算内包 SHA；GitHub artifact digest 不是本机下载验证。构建与测试均为测试渠道，没有正式 Release、商店提交或主分支合并。

Mac artifact 已下载到本机独立 `/tmp` 目录，按 `SHA256SUMS` 对全部 15 个文件逐项重算匹配，并核对清单内文件长度与哈希。font、fixture、design tokens 再与精确 `git show 224d143:...` 字节核对一致；未用后来工作区文件替代来源。内层 `.app.zip` SHA256 为 `ab123527b9f57ca89e9a07aba549af0fc1d40499fc1f7b9f7946108f28625c67`，解包确认 arm64 可执行文件，未启动 App、绕过 Gatekeeper 或安装 SDK。见 [Mac 核验](macos-package-verification.json)。

`45b96d6` 前序 run `41013966910` 已被后续提交取消；不是成功，也不当成源代码失败。`224d143` 包含窄屏隐藏桌面分屏入口的修复。更早浏览器截图与 SHA 保留，未冒充此提交的原生运行证据。

汇总与文件哈希：[verification.json](verification.json)。真实 SSH/herdr、overlay 入网、手机 IME/触控、签名与分发验收仍未因 CI 编译通过而改变。
