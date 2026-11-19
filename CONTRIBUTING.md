# 参与贡献

先[查看是否已有同类问题](https://github.com/Luck9Star/herdr-pocket/issues)，再登录 GitHub [报告故障或提出建议](https://github.com/Luck9Star/herdr-pocket/issues/new/choose)。

## 报告故障

1. 写出最短的复现步骤，说明预期与实际结果。偶发问题可以写触发条件和重现频率。
2. 只填写愿意公开的附加信息，例如 Flutter 或 Tauri、应用版本或源码提交、平台和系统版本。诊断只需手选相关的阶段、状态或固定错误码。未知的项目可以留空。[如何阅读连接诊断](docs/53-mobile-connection-diagnostics.md#公开反馈)
3. 分别说明运行环境和网络。运行环境可以是本机代码检查、Widget 测试、模拟器或实体设备，网络可以是回环、隔离夹具或实际跨网。例如「iOS 模拟器 + 受控回环」只说明该组合的结果。[五端支持矩阵与验收口径](docs/05-product-design.md#8-五端支持与开源发布)

Issues 是公开的。提交前删去凭据、配对资料、原始指纹、主机名、地址、账号、设备或网络标识和终端正文。日志、截图及配置文件请留在本机。应用诊断不会随表单自动附带。

## 提交改动

按[验证入口](validation/README.md)选择对应模块的检查，提交前运行 `git diff --check`。在拉取请求中说明改动原因、复现或验证步骤、实测结果和待验证范围。用合成测试资料重现问题。
