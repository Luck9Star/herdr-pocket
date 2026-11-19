# GitHub 公开反馈表单验收

2026-11-20，在已登录的 Chrome，从公开仓库的 Issues 列表点击 `New issue`，打开默认分支 `main` 的「报告故障」和「提出功能建议」。本轮检查以 `8a8311dbb46cca293ff038d7a5af1326181c0e74` 为源码基线。[Issues 列表](https://github.com/Luck9Star/herdr-pocket/issues) · [基线](https://github.com/Luck9Star/herdr-pocket/commit/8a8311dbb46cca293ff038d7a5af1326181c0e74) · [模板选择器原图](chooser.jpg)

| 实际打开的表单 | 空白选填项 |
| --- | --- |
| 报告故障 | 「可公开的诊断结论」的初始字符数为 0，字段可留空并通过字段校验。 |
| 提出功能建议 | 「相关平台」的初始字符数为 0，字段可留空并通过字段校验。该表单没有诊断字段。 |

两个表单均提示读者将凭据、终端正文等敏感资料留在本机。逐个点击 `Cancel` 返回列表，未发布 Issue，也未提交附件。这里核对的是打开表单时的字段行为。[故障表单原图](fault.jpg) · [建议表单原图](feature.jpg)

原图保留选择器和两份表单的上部。下方选填项的公开标签、必填属性、初始长度与有效性来自实际页面的[脱敏观察记录](observed.json)，并与基线的[故障模板](../../../.github/ISSUE_TEMPLATE/bug-report.yml)和[建议模板](../../../.github/ISSUE_TEMPLATE/feature-request.yml)核对一致。三个 2560×1138 JPEG 与观察记录均保留原字节，校验值见 [SHA256SUMS](SHA256SUMS)。

```sh
shasum -a 256 -c SHA256SUMS
```
