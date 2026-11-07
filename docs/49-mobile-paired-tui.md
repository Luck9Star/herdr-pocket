# 配对手机操作远端 TUI

最新 APK、Tauri 模拟器十步实测及 Flutter 的单独复测见[Android 设备验证](50-android-paired-tui-validation.md)。

2026-11-08。手机配对完成后，在同一主机上选择终端。从全帧进入逐键模式，后续输出更新时仍显示实际输入状态。草稿、观察和发送结果未知各有独立提示。局部测试覆盖了正在输入时收到增量、同一目标重绘全帧、停止观察与重新核验。配对、撤销和应用清理沿用原有流程。[配对与设备密钥验收](46-android-pairing-handoff-validation.md) · [功能键与宿主模式](48-mobile-terminal-function-keys.md)

## 怎样证明按键生效

在 API 35 云模拟器的受保护输入用例中，隔离 sshd 需确认认证公钥与该手机经 helper 审查的公钥一致。手机先发送单个 `k`、恢复隐藏标签，再明确发送草稿 `Pocket测`。主机核对收到这十个字节，独立查询同一 pane 与稳定 terminal，才会在原 PTY 启动一次 curses。

| 手机操作 | 可观察的程序效果 |
| --- | --- |
| 下移、Tab、Backspace、Shift+Tab | 选中 Review，进入详情，删除末尾字符，焦点返回列表 |
| Insert、Delete | 出现选中的 New 行，随后移除，重新选中 Review |
| F1、F1、F5 | 打开帮助，返回列表，刷新次数增至 1 |
| F10 | 主机程序退出，动作顺序和最终状态符合约定，终端属性恢复 |

手机检查新全帧、当前画面和十笔不同的受理回执。主机独立检查程序最终状态，并在退出后短时读取内核 PTY 中可见的尾随字节。完整记录包含前两笔及 TUI 十笔共十二个不同请求 ID，始终绑定同一目标。某一阶段超时或写入结果未知时，驱动不会补发按键。布局变化时独立对共享 PTY 取样。[主机与 GUI 证据合同](../validation/remote-harness/README.md#配对手机操作同一远端-tui)

## 当前实测范围

- Mac 独立 PTY 已走通原十字节、真实 curses 十个动作和恢复。中途停止时程序退出，终端属性恢复。
- Mac Chrome 手机视口已用真实 xterm DOM 匹配十个画面状态。检查采用当前可视区域的整行文字，涵盖了非换行空格和软键盘操作后终端滚出页面的情况。原生通道使用测试替身。
- 两套生产编码器分别在新建 PTY 完成同一程序。Tauri 前端独立源码快照 396 项通过，Vite 构建通过。Flutter Android 主机驱动 75 项、远端驱动和夹具 83 项、Flutter 构建工具 15 项通过。Dart 语法检查无法确认 Flutter 引擎的绘制、焦点或系统 IME。

云端已构建候选宿主，并确认四次仅改变模式的更新都到达观察流。普通 herdr 的手机场景继续验收远端零输入，带输入的场景在同一会话运行上述程序。每条路线的设备结果及下载见[本批 Android 验收](50-android-paired-tui-validation.md)，上次两壳的配对与观察实测见[历史基线](46-android-pairing-handoff-validation.md)。

新版 Penpot 已保存手机配对、看板、终端和观察画布，查看器可打开 [S52 配对交接](https://design.penpot.app/?screen=viewer&file-id=b55064db-d93d-80f9-8008-ddd22e6d398f&page-id=7a22df08-251d-8016-8008-de03541c11da&section=interactions&frame-id=ff7bd149-6597-80a5-8008-e8e75ef79937) 与 [S56 观察画布](https://design.penpot.app/?screen=viewer&file-id=b55064db-d93d-80f9-8008-ddd22e6d398f&page-id=7a22df08-251d-8016-8008-de03541c11da&section=interactions&frame-id=25c76497-7d68-803e-8008-e8fdaa687c09)。新增功能键的四个状态仍是草稿。插件连接未恢复，尚无对应的线上画板；本地形状模拟仅检查按键、导航和拒绝覆盖条件。[草稿源码](../design/penpot/mobile-tui-controls-20261108.js) · [连接与核验记录](../design/evidence/v2-mobile-tui-controls-20261108.json)
