# Penpot 核心交互验证 v0.1

2026-10-30 已保存于独立 herdr-pocket 项目；低／中保真阶段，未根据真机比较定案高保真。

- [可点击原型（START 导航）](https://design.penpot.app/?screen=viewer&file-id=b55064db-d93d-80f9-8008-ddd22e6d398f&page-id=b55064db-d93d-80f9-8008-ddd22e6d3990&section=interactions&frame-id=c1974894-3caf-8067-8008-ddd4b0a14f71)
- [编辑文件](https://design.penpot.app/?screen=workspace&team-id=c514c1fb-1cda-8125-8008-a57c5bd4a25d&project-id=9a0c44dc-8874-81e7-8008-ddd20c193c16&file-id=b55064db-d93d-80f9-8008-ddd22e6d398f&page-id=b55064db-d93d-80f9-8008-ddd22e6d3990)
- [状态与出口覆盖清单](coverage.md)
- [重载后原生对象证据](evidence/penpot-final-after-reload-20261030.json)

链接沿用当前 Penpot 账户／团队权限，未开启公开共享。文件 ID 为 `b55064db-d93d-80f9-8008-ddd22e6d398f`，页面 ID 为 `b55064db-d93d-80f9-8008-ddd22e6d3990`。内容为原生可编辑对象，包含 57 个可见画板（56 状态 + 导航）、205 条点击交互、18 个组件、25 个 tokens、650 个文本对象；另有不参与预览的组件规格板。七个流程起点含 J1/J2/J3、P5/P6、导航及补充导入失败入口。

## 实际验收

编辑器重载并重新连接 MCP 后读取上述数量；预览模式实际点击：

1. START → P1-empty → P2-request → P2-helper → P2-authorized → P2-scan → P2-review → P2-ready → P2-success → P1-loading → P1-dashboard。
2. P1-dashboard → P3-observe → P3-direct → P4-unknown；unknown 只有核实恢复、连接诊断、返回导航，没有重试／补发出口。
3. START → P4-tabs → P4-hidden → P4-b-ready，目标由 A 明确切换为 B。

其余状态通过原生对象／目的地检查，未声称逐个手动点击了 205 条边。原型不执行扫码、SSH、输入、加密、网络或授权文件修改。响应错配与过期共用拒绝状态并分别说明；helper 拒绝／撤销不声称中断已有 SSH。高保真、手机真机输入、读屏与完整键盘导航验收仍待完成。

## 编辑与重现边界

`penpot/` 保存本次原生写入脚本和状态数据；`build-core.js`、`finish-core.js`、`refine-core.js`、`supplement-core.js` 是本次建稿记录，**不是可重复覆盖当前文件的同步命令**。创建脚本限制固定文件 ID 与空页面；补充脚本拒绝重复添加。`screens.json` 已反映补齐后的 56 状态，不能将历史初建与补丁顺序再次盲跑。日常核验可调用只读 `verify.js`。后续改稿应在指定文件、指定对象范围内增量处理，保存后重载再核验。

本轮使用官方 `@penpot/mcp@2.15.4` 的 `execute_code`、`export_shape`，Penpot 应用为 2.19.0，插件明确提示版本不匹配。实际支持的 board/text/component/token/interaction 写入已核验；`createFlow` 参数不兼容，改用自动生成流程的可写 startingBoard/name。后续升级需重新验证，不将这些调用推断为跨版本保证。

来源：[官方 MCP 使用说明](https://help.penpot.app/mcp/)；Context7 先解析 Penpot 再查询 `/penpot/penpot-mcp`，旧仓库文档与实际插件 API 有差异，以本次执行记录为准。未修改用户已有服务配置，未触及其他项目设计。

## 视觉证据

![导航](evidence/START.png)
![完整终端直接输入](evidence/P3-direct.png)
![桌面分屏](evidence/D1-workspace.png)

## 实测反馈

macOS首轮发现 terminal_view 0.5.0 的 ASCII组合重音绘制缺陷，已增量反馈到原文件 P7-font；不扩大画板或锁定框架。工程交接需同时保存原fixture字节、buffer/复制内容与实际绘制结果，修复后按同机/字体/视口重验。Powerlevel10k、Oh My Posh真实主题与手机IME仍未验。

![P7实测反馈](evidence/P7-feedback.png)

独立只读复核同样确认 57 可见画板、205 交互、18 组件、25 tokens、650 文本对象；J1 的10条、J2 的3条和J3 的3条关键连线存在，navigate-to 目的地无悬空；unknown 只有恢复、网络诊断和导航入口。原始结果见[独立复核](evidence/penpot-independent-review-20261030.json)。
