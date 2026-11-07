# 手机终端键盘与组字

2026-11-07，手机配对与观察闭环跑通后，继续检查刚配对的表单入口和已保存主机的终端标签。本页改动已进入 `a9914fe` 同源云批次；两份 arm64 实验 APK 已生成并复核下载字节，但首轮 Android AVD 四场景中仅 Tauri 普通观察通过，另外三场景失败。[最新测试包、校验和与逐场景结果](36-mobile-paste-and-auxiliary-input.md#同源云验证与可下载测试包)；[上一批观察记录](34-mobile-host-task-summary.md)保留原来的来源与范围。

| 路线 | 原有行为 | 本批改动与验收 |
| --- | --- | --- |
| Tauri 刚配对的表单、已保存主机标签 | xterm 在禁用输入时把 textarea 设为只读。旧标签首次获焦的实测值为 `readOnly=true`，表单还在异步等待后才请求焦点 | 在按“逐键输入”的用户手势内，让可编辑的终端请求键盘。收到原生许可、确认仍在原目标和原焦点后才允许发送。两个入口都通过 Mac 浏览器验证。 |
| Flutter 草稿和逐键模式 | 再点已选中的模式仍会清焦点并替换带有新 epoch 的编辑控件，正在组合的文字会失去原客户端 | 同一模式重复选择保留原编辑控件。新增三个 widget 场景覆盖 320／390 宽草稿及逐键提交；本机只完成 Dart 语法解析；后续同源云端 analyzer、unit／widget 已通过，Android 运行仍有独立失败，见下文。 |

## Mac 验证

Chrome 156、390×844 视口和仓库固定的 xterm.js 6.0.0。表单走应用的配对审查、看板和选 pane 入口；标签走已保存主机的身份审查、看板和选 pane 入口。原生 IPC 返回合成的设备、帧和发送回执。下面的输入数字只计入本地夹具。[原始读数与被测源码哈希](evidence/mobile-pair-gui/mobile-input-focus-20261107.json)

1. 浏览器派发触控点击“逐键输入”。两个入口均记录到受信点击，终端首次 `focusin` 均为 `readOnly=false`、`inputMode=text`。
2. 保持原生许可待定，通过 Chromium 组字接口输入 `jiu`，放行许可后再提交“旧”。两个入口都收到 0 笔。
3. 在已有许可的同一焦点输入 `zhong` 并提交“中”。每个入口都只收到一笔 UTF-8 字节 `E4 B8 AD`。
4. 开始第三次组字，在表单停止观察，或在工作台切到另一标签。两种操作后均没有新增发送，也没有请求改变远端 PTY 尺寸。

从已提交的原型源码叠加本批文件，在隔离副本执行 Tauri 的 `npm test`（159 项通过，0 跳过）和 `npm run build`（通过）。本轮专用浏览器及回环测试服务均已关闭。

## 云端补充与后续设备验收

`a9914fe` 云端 Flutter analyzer 无问题，unit／widget 为 312 项通过、1 项跳过，绘制回归为 10 项通过。Linux 隔离 SSH GUI 收到 9 字节并正常清理。首轮 API 35 AVD 中 Tauri 普通观察通过；Flutter 普通观察止于 `create_not_available`，两套受保护输入分别止于 `guarded_hidden_draft` 和 `android_draft_not_retained`，均不能计为输入验收通过。[来源、失败阶段及设备边界](36-mobile-paste-and-auxiliary-input.md#首轮-android-模拟器结果)

后续只重跑测试的批次单独记录来源和结果。仍须分别确认各路线的软件键盘显示／收起、单次提交字节及切换时输入数。系统中文输入法、候选栏、物理触控和 arm64 安装需要设备证据。两条候选保留到这组正确性结果齐备后再比较。

后续的粘贴审查、辅助键及集中运行记录见[手机粘贴与草稿找回](36-mobile-paste-and-auxiliary-input.md)。

之后两条路线的普通观察和受保护输入均在 x86_64 Android 模拟器走通。该批工作流的 Flutter analyzer 仍有一项导入诊断。[四场景复验与回执](36-mobile-paste-and-auxiliary-input.md#android-定向复验)
