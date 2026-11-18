# libghostty-vt 与两壳终端适配评估

状态：2026-11-15，探索性验证；尚未替换生产终端。官方目标固定为 libghostty-vt `vt-1.0.1`，源码 `108cacb17ed8990840cd14abfce43d8ed8503ca1`。本页只核查所列代表性适配器，不能据此断言所有第三方 wrapper 均不可用；控件实验使用其自带的不同版本 WASM，不能当作目标 ABI 的通过证据。

## 判断与建议

**值得做受控适配原型，尚不建议替换两壳的生产终端。** libghostty-vt 解决 VT 字节解析、状态和输入编码的一部分；它不是完整的 Flutter 或 WebView 界面，也不能直接替代焦点、IME、选择、屏幕阅读、安全输入门槛和远端会话生命周期。1.x 的 C ABI 稳定不等于第三方绑定或 UI 行为稳定。官方 Ghostty 应用的私有 embedder 与可分发的 libghostty-vt 是不同接口；不能把官方 macOS 应用的 GPU 渲染与界面自动推及五端。固定版本构建、平台与发布方法见[上游同版本打包说明](https://github.com/ghostty-org/ghostty/blob/108cacb17ed8990840cd14abfce43d8ed8503ca1/PACKAGING-LIBGHOSTTY.md)。

| 候选 | 现状与优势 | 未解决的关键问题 |
| --- | --- | --- |
| 保持现有终端 | 两壳现有授权门控、回归及设备证据可继续使用 | 字符、渲染和输入缺陷仍须各自维护 |
| Flutter + `flterm` | 第三方 Widget、控制器、字节输出和 resize 回调，已有触摸、选择、IME 代码 | 该绑定锁定其他上游提交；稳定 1.0.1 兼容、只读隔离、无障碍和五端打包未验证 |
| Tauri + `ghostty-web` | Canvas + WASM，提供部分 xterm 风格 API，可在隔离浏览器画出终端 | 当前包含私有补丁并非稳定 1.0.1 原样替换；只读时仍可产生协议响应，接口和辅助功能须重新核验 |
| 自建 1.0.1 绑定与视图 | 可以把引擎版本与认证、帧序和权限层严格分离 | 两种 UI、文本输入/选择、屏幕阅读、构建及多平台分发成本最高 |

建议先限定 **一个普通 SSH 会话的可切换试验页**，由宿主保持主机密钥校验与认证，单会话持有单引擎实例；继而单独接 herdr 的观察态，先验证写入期间零远端输入，再验证输入租约、帧确认与中断恢复。保留原终端及显式开关作为回滚路径，任何新适配器不能绕过现有门控。是否进入产品迁移待两壳对应平台证据及独立引擎对照后决定。

## 目前两种数据路径

| | Flutter | Tauri |
| --- | --- | --- |
| 控件 | `terminal_view` 0.5.0，候选使用固定 patch 与输入法 shim；`Terminal` / `TerminalView` | `@xterm/xterm` 6.0.0 和 `@xterm/addon-unicode-graphemes` 0.4.0；创建时注册 grapheme provider |
| 普通 SSH | `direct_ssh_page.dart` 的独立 stdout/stderr 经流式 UTF-8 解码后写入终端；输出编码为 UTF-8 发 shell，resize 发 PTY | Rust 通道的原始字节交 `terminal.write(Uint8Array, callback)`，`onData` 编码写回；每次连接创建新实例 |
| herdr | `remote_page.dart` 对已验证的 full 新建终端，再写 `frame.ansi`；delta 延续状态。写入期间 `rendering` 阻断输出回调 | `remote.js` 校验 generation/epoch/seq，full 时重置并应用固定画布，逐帧写字节；回调之后才确认帧 |
| 输入安全 | 选中目标、full 新鲜度、能力、租约、focus、可见性、模式和渲染期共同约束；多行/粘贴走审查 | 单写侧、目标、epoch、焦点、IME、粘贴审查和 unknown 结果锁；被动 frame 不是授权输入 |

本仓具体入口：[Flutter 普通 SSH](../validation/flutter/lib/direct_ssh_page.dart)、[Flutter herdr](../validation/flutter/lib/remote_page.dart)、[Tauri 普通 SSH](../validation/tauri/src/direct-ssh-ui.js)、[Tauri herdr](../validation/tauri/src/remote.js)、[真实标签](../validation/tauri/src/tab-workspace.js)。herdr full/delta 是协议帧和确定的远端画布，不是普通 SSH 的任意输出流；隐藏/恢复后必须取得新 full，不能为了本地视图或分屏重排悄悄改变共享 PTY。输出生成的终端应答与用户按键均须按具体路径和授权策略处理，不能仅靠控件的只读开关。

## 第三方界面与实际隔离试验

- [`flterm` / `libghostty`](https://github.com/elias8/libghostty/tree/2ca76cffabd7d35699ad24bcb79002bdf190eb0a) 当时 pub 版本分别为 0.0.6 / 0.0.13，项目许可证 MIT；版本声明覆盖 Android、iOS、Linux、macOS、Windows 和 Web，是上游声明而非本项目平台实测。实取并核对 pub `libghostty` 0.0.13 包（SHA256 `f42a0975553fe405f3d3c33cf634af3de529b41bd939dbc478ae2f8acb52dc80`）内的 `ghostty.version` 为 `e3ac62001ef2a6c9c4b4bb4231535c1c3c3e4ae3`，不同于 `108cacb`；所查仓库主线 `2ca76cff` 的[版本文件](https://github.com/elias8/libghostty/blob/2ca76cffabd7d35699ad24bcb79002bdf190eb0a/packages/libghostty/ghostty.version)又是 `6d9577708a211b0e6c5e6c6886f3cfb7efc47555`，不能把主线和已发布包混为一谈。 独立检查对 pub 0.0.13 的 FFI 直接调用集合（81 个符号，并非全部 ABI）与官方 1.0.1 macOS arm64 导出交叉核对，发现 `ghostty_mouse_encoder_setopt`、`ghostty_mouse_encoder_setopt_from_terminal` 和 `ghostty_terminal_vt_write_until_ground` 三个调用符号缺失；这支持评估移植绑定，但不支持将正式包原样换库并宣称全功能兼容。控制器公开字节 `write` / `onOutput`、`onResize`、选择及粘贴；一个控制器同时只能挂一个视图。其输入法实现使用 Flutter 文本输入客户端，但屏幕阅读与本仓权限行为未验收。包本身和其依赖、预编译二进制的来源/许可须在落包前按实际版本审查。
- 独立临时工程使用固定 Flutter 3.47.9、pub `flterm` 0.0.6 / `libghostty` 0.0.13 真实 Widget 测试 1/1：挂载 `TerminalView`，分片 UTF-8 写入 `中😀!`，全选读取匹配；`controller.sendText('ok')` 的 `onOutput` 字节匹配，卸载后释放。向 `controller.write` 输入 DSR 也会同步生成 `onOutput` 应答；因此 Flutter 的渲染期与输入租约拦截同样不可省。[测试源码](evidence/libghostty-vt-20261115/flterm_probe_test.dart)和下方命令可复现。这里的输入来自控制器 API，不是物理键盘、IME、真实 SSH 或本仓页面，也不是官方 1.0.1 核心；临时测试未进入产品。
- [`ghostty-web` 0.4.0](https://github.com/coder/ghostty-web/tree/9e4e126d89ac3537d2b2ebec075849851566de9f) 项目许可证 MIT，使用 xterm 风格 `Terminal`、`write`、`onData`、`resize`、`dispose` 等接口；其固定 Ghostty 子模块为 `5714ed07a1012573261b7b7e3ed2add9c1504496`，并在[构建时应用私有 WASM 补丁](https://github.com/coder/ghostty-web/blob/9e4e126d89ac3537d2b2ebec075849851566de9f/scripts/build-wasm.sh)。它并非 Ghostty 官方维护的 1.0.1 UI 绑定。
- 隔离临时页面使用 npm `ghostty-web@0.4.0`、本地 HTTP 和独立 Chromium 会话，实际创建 Canvas 和输入 textarea，以 `Uint8Array` 写入后 buffer 读回 `ONE` 和 `中😀!`，resize 为 50×10，dispose 后 Canvas 已移除；这只是控件 API 的一次实验，没有 SSH、herdr、物理键盘或设备验收。**`disableStdin: true` 时写入 `ESC [ 6 n` 仍触发 `onData` 的 `ESC [ 2 ; 6 R`**：这是终端协议应答，说明禁用键盘并不能保证观察态零输出。尤其迁移时应针对同步/异步的解析输出加明确拒绝及旧 epoch 检查，避免应答被误作用户输入；该实验不表示现有产品已发生此问题。另用当前 `@xterm/xterm` 6.0.0 在 Node 中对照：输入 `ab` 与 DSR 时，`disableStdin: true` 的 `onData` 为 0 次，false 时返回 `1b5b313b3352`；这是解析接口对照而非 DOM 或设备测试，现有 herdr 路径还受模式、焦点与 epoch 门控。其 `write` 回调安排在下一次 `requestAnimationFrame`，与现有 herdr 帧确认语义是否等价及销毁后迟到回调须单独验证。
- 同一界面通过该库的 `Ghostty.load` 显式加载官方 1.0.1 ReleaseFast WASM（SHA256 `2ee8434a58866aa3ce43cebbbf284d684f5f5b64c4f6040fa031cfe789e11646`）时，打开失败，缺少 `ghostty_wasm_alloc_u8_array`；默认包的自带模块 423,045 字节，和官方模块 1,243,719 字节分别有 77 / 217 个导出。该结果只证明这个绑定与该官方二进制组合不能直接互换，不证明官方 VT 核心不可用。[静态页面源码](evidence/libghostty-vt-20261115/ghostty-web-probe.html)和下方命令可复现；依赖与二进制不进入产品。

### 在隔离目录复现界面探针

在仓库根目录，使用已安装的 Flutter 3.47.9 / Dart 3.13.7（检查 `flutter --version`）；以下生成独立工程，不改现有依赖：

```sh
repo_dir="$PWD"
probe_dir="$(mktemp -d)"
flutter create --empty --no-pub --platforms=macos --project-name flterm_probe "$probe_dir/app"
cd "$probe_dir/app"
flutter pub add flterm:0.0.6 libghostty:0.0.13
mkdir -p test
cp "$repo_dir/docs/evidence/libghostty-vt-20261115/flterm_probe_test.dart" test/
flutter test test/flterm_probe_test.dart --reporter expanded
```

浏览器测试使用 Node/npm、Python 和 Chromium；另开终端在仓库根目录运行：

```sh
repo_dir="$PWD"
probe_dir="$(mktemp -d)"
npm install --prefix "$probe_dir" --no-save --no-package-lock ghostty-web@0.4.0
cp "$repo_dir/docs/evidence/libghostty-vt-20261115/ghostty-web-probe.html" "$probe_dir/index.html"
curl -fsSL https://release.files.ghostty.org/libghostty-vt/1.0.1/ghostty-vt-1.0.1.wasm -o "$probe_dir/official-1.0.1.wasm"
printf '%s  %s\n' 2ee8434a58866aa3ce43cebbbf284d684f5f5b64c4f6040fa031cfe789e11646 "$probe_dir/official-1.0.1.wasm" | shasum -a 256 -c
python3 -m http.server 18753 --bind 127.0.0.1 --directory "$probe_dir"
```

浏览器打开 `http://127.0.0.1:18753/` 运行内置 WASM，结果包含屏幕文本和只读状态下的 DSR 应答；打开 `http://127.0.0.1:18753/?official` 显式使用官方 1.0.1，预期显示缺失 `ghostty_wasm_alloc_u8_array`。用完停止本地服务器。固定哈希与签名验证用于确认来源，不能由包安装成功推断产品可用。

## 会话隔离与行为门槛

官方 1.0.1 的独立核心对照已完成：[macOS arm64 native 结果](../validation/ghostty-vt/results/native-macos-arm64-20261115.json)中 19 项必过检查通过，另有两项 reset-only 假设观察均为 `supported: false`；20 次独立进程结果一致。[Node 22.22.2 / 官方 ReleaseSmall WASM 结果](../validation/ghostty-vt/results/wasm-node-20261115.json)中 9 项必过检查通过、同两项 reset 观察为否定。默认每会话新建实例策略下两者退出 0；启用 `--require-reset` 后两者退出 1，保留反例。native 覆盖组合字符、mode 2027 家庭 ZWJ、SGR、DSR 本地捕获/只读丢弃和 Up 键编码；WASM 覆盖 Unicode 分块、备用屏和 resize，未覆盖回调或键编码。完整命令和验收边界见[核心探针说明](../validation/ghostty-vt/README.md)。没有打开远端传输，也不证明 UI、性能、真实键盘或设备。

独立对官方 1.0.1 ReleaseSmall WASM 的 Node 24.22.2 检查显示：逐字节 `a中😀é!`、备用屏进入/退出及 resize 后原屏保持可用；但前一会话末尾 `f0 9f` 经 `ghostty_terminal_reset`，下个会话 `98 80 5a` 仍可拼为 `😀Z`。销毁后新建 handle 则显示 `��Z`。两者对孤立无效字节的具体显示不同，关键是不能延续旧会话的 UTF-8 状态；因此断开/重连必须释放旧实例，而不是依赖 reset。该试验不是产品 UI 实测。

迁移验收至少覆盖：UTF-8 跨块、CJK/emoji/组合字符及重连半字符；full 重建与 delta 顺序、画布和确认时序；屏幕阅读内容与输入节点、屏幕选择与复制；IME 组合、软键盘、辅助键、焦点和粘贴确认；不可见/观察/渲染期、旧目标、失败未知结果、异步回调和 session 重建下零误发；后台、取消、断开、重连和真实 PTY resize。Canvas 存在、`role=textbox` 或 Widget 语义本身均不能证明屏幕阅读器能读取终端内容。实际 GPU 路径、滚动性能、功耗和屏幕阅读须逐平台测量；不能由 VT 库或包名推断。

既有竞品的 [Heeler 架构记录](https://github.com/ZingerLittleBee/Heeler/blob/bd837c7ede634ba86a3ba247c2d9198ed20dbf77/docs/adr/0004-libghostty-terminal.md)采用第三方 `libghostty-spm` 的 UIKit `UITerminalView` / Metal；该原生 iOS 方案说明可有不同嵌入层，不能当作公共 VT C 库已经提供五端 Widget。

## 分发与五端范围

官方 [1.0.1 发布文件](https://lib.ghostty.org/vt/installing.html)包含 Apple XCFramework、Windows GNU DLL/static、WASM 和源代码；独立核验发行 `SHA256SUMS` 的 minisign，manifest SHA256 `bb7a3cf9d6de0f9cb278a94006a96586375de5d56d4df74e03ea59dac035a069`。已下载文件测得：普通 WASM 1,243,719 B、小版 845,526 B；XCFramework ZIP 16,451,728 B，其切片为 iOS 真机 arm64、iOS 模拟器 arm64、macOS arm64/x86_64；Windows x86_64 DLL 2,588,672 B、arm64 DLL 2,088,448 B。这些是文件大小，不是最终应用增量。

| 平台 | Flutter 路线待做 | Tauri 路线待做 |
| --- | --- | --- |
| macOS | XCFramework/FFI 与 Flutter 渲染、原生语义/输入；核验 arm64/x86_64 打包 | WebView WASM 与输入/无障碍、或自建本地桥；非自动获得官方 Ghostty 原生 UI |
| iOS | XCFramework 真机/模拟器链接、签名、键盘和 VoiceOver；发行包模拟器无 x86_64 切片 | WKWebView WASM 和桥接、真机签名与触控；非由桌面 Web 通过外推 |
| Android | 自编 NDK ABI 库、FFI 加载、IME 与 TalkBack | WebView WASM、资源装载、键盘与无障碍；需测 WebView 版本 |
| Linux | 从固定源码构建并打包共享库、FFI 与桌面辅助技术 | WebKitGTK 的 WASM/Canvas、键盘和辅助技术 |
| Windows | GNU DLL 的分发/ABI 装载与 FFI、输入和屏幕阅读 | WebView2 WASM、输入与辅助技术 |

官方稳定发布清单未列 Android AAR/so 或 Linux 预编译包，需自行构建；上游 [Android CI](https://github.com/ghostty-org/ghostty/blob/108cacb17ed8990840cd14abfce43d8ed8503ca1/.github/workflows/test.yml#L1309)以 NDK r29 交叉构建 aarch64/x86_64/armv7；[上游运行 43094066360](https://github.com/ghostty-org/ghostty/actions/runs/43094066360)三目标均成功，不能算本项目实机验证。上游 Ghostty 代码遵循其[固定版本许可证](https://github.com/ghostty-org/ghostty/blob/108cacb17ed8990840cd14abfce43d8ed8503ca1/LICENSE)；二进制的依赖与字体许可、静态链接义务须按最终构建清单复核。

## 2026-11-18 R20 三项迁移条件核查

基线 `f378e9a`（`main`）按门禁逐项核对。**结论：条件一、二不满足；条件三回退方式已明确，隔离原型分支待创建，暂未验证；维持不迁移。**

### 条件一：关键能力优于现实现（同条件实测）

同一批用例分别运行官方 libghostty-vt 1.0.1（固定 tag `vt-1.0.1` / commit `108cacb`；用 2026-11-15 已核验哈希的 XCFramework 静态库以仓库 `probe.c` 重编译执行，19 项必过全过、两项 reset 观察否定；ReleaseSmall WASM 由 `probe-wasm.mjs` 现场下载过固定 SHA256 后复跑，9 项全过）与生产 Tauri 壳同款 `@xterm/xterm` 6.0.0 + `@xterm/addon-unicode-graphemes` 0.4.0（Node 24.22.2，无 DOM；读数均在 `write` 回调排空后取 buffer）。

| 用例 | libghostty-vt 1.0.1 | xterm 6.0.0 | 判定 |
| --- | --- | --- | --- |
| `a中😀é!` 全切点逐块跨写 | 通过（`utf8_every_two_chunk_boundary`、`utf8_one_byte_chunks` 等） | 全部切点还原 | 平手 |
| 组合重音 `e`+U+0301 | 1 列 `é` | cursorX=1，`é` | 平手 |
| ZWJ 家庭 emoji+`!`（mode 2027） | 2 列+1，cursor 3 | cursor 3，cell0 完整 | 平手 |
| 备用屏 1049 进入/退出 | `ALT`/`MAIN` | `ALT`/`MAIN` | 平手 |
| 半截 UTF-8 + reset + 尾字节 | `😀Z`（reset 不隔离） | `😀Z`（同为 U+1F600+`Z`） | 平手（同缺陷） |
| 孤立尾字节 `98 80 5a` 新实例 | `??Z` | `Z` | 显示策略差异，非产品优势判定项 |
| resize 6×3 `abcdefg`→4×4（光标行内悬挂，`probe.c` 同款） | `abcdefg` | 默认 `abcd`/`g`（光标行 reflow 丢 `ef`）；`reflowCursorLine:true` 时 `abcd`/`efg` | 见下 |
| 同输入后接 `\n`（光标移出行）再 resize | 无对应官方用例 | 默认配置即 `abcd`/`efg` | 见下 |

resize 差异限定在**光标所在悬挂行**：xterm 6.0.0 公开布尔选项 `reflowCursorLine`（typings 注明默认 false、"shells usually handle this themselves"）设为 `true` 后，6×3→4×4 与 8×3→4×4（`abcdefgh`）均保留全部字符；光标移出测试行后默认配置也不丢字。生产 Tauri 壳未设置该选项（`validation/tauri/src/` 全量无 `reflowCursorLine`），但远端观察路径 full 帧重建时先 `reset()` 再按帧尺寸重建（`remote.js`），不存在“已写内容上直接缩列”的裸探针场景。即该差异是默认配置对光标行的策略，可用公开选项或 shell 自行重绘消除，不构成核心能力差距，也不外推为生产缺陷。孤立无效字节两核策略不同（libghostty 显示替换符、xterm 丢弃）；本对照无 DOM/renderer，屏幕上最终呈现未测，不作优势定性。**判定：未测得构成迁移依据的关键能力优势。**

xterm 侧对照脚本（完整可执行，Node ≥22）：

```sh
npm install --prefix /tmp/r20cmp --no-save --no-package-lock \
  @xterm/xterm@6.0.0 @xterm/addon-unicode-graphemes@0.4.0
```

```js
// /tmp/r20cmp/cmp.mjs — node cmp.mjs
import {createRequire} from 'node:module';
const R = createRequire(import.meta.url);
const D = '/tmp/r20cmp/node_modules';
const {Terminal} = R(D + '/@xterm/xterm/lib/xterm.js');
const {UnicodeGraphemesAddon} = R(D + '/@xterm/addon-unicode-graphemes/lib/addon-unicode-graphemes.js');
const enc = new TextEncoder();
const mk = o => {const t = new Terminal({cols:80, rows:24, allowProposedApi:true, ...o});
  t.loadAddon(new UnicodeGraphemesAddon()); return t;};
const rows = t => {const b = t.buffer.active, a = [];
  for (let r = 0; r < b.length; r++) a.push(b.getLine(r).translateToString(true).replace(/\s+$/, ''));
  return a;};
// 1) UTF-8 全切点
const bytes = enc.encode('a中😀é!'); const bad = [];
for (let s = 0; s <= bytes.length; s++) await new Promise(res => {
  const t = mk(); t.write(bytes.slice(0, s));
  t.write(bytes.slice(s), () => { if (rows(t).join('') !== 'a中😀é!') bad.push(s); res(); });
});
console.log('utf8_all_splits:', bad.length ? 'FAIL ' + bad : 'PASS');
// 2) 组合 / ZWJ
const c = mk(); await new Promise(r => c.write('e\u0301', r));
console.log('combining:', c.buffer.active.cursorX, rows(c)[0]);
const z = mk(); await new Promise(r => z.write('👨‍👩‍👧‍👦!', r));
console.log('zwj:', z.buffer.active.cursorX, z.buffer.active.getLine(0).getCell(0).getChars());
// 3) 半截 UTF-8 + reset() + 尾字节（生产 full 重建路径同款 reset）
const h = mk({cols:20, rows:5});
await new Promise(r => h.write(new Uint8Array([0xf0, 0x9f]), r));
h.reset();
await new Promise(r => h.write(new Uint8Array([0x98, 0x80, 0x5a]), r));
console.log('half_reset_tail:', [...rows(h).join('')].map(x => x.codePointAt(0).toString(16)).join(' '));
// 4) 孤立尾字节新实例
const n = mk({cols:20, rows:5});
await new Promise(r => n.write(new Uint8Array([0x98, 0x80, 0x5a]), r));
console.log('isolated_tail:', [...rows(n).join('')].map(x => x.codePointAt(0).toString(16)).join(' '));
// 5) resize：光标行内悬挂 vs reflowCursorLine:true vs 光标已移出
for (const [label, opts, input] of [
  ['cursor_inline_default', {cols:6, rows:3, scrollback:1000}, 'abcdefg'],
  ['cursor_inline_reflowTrue', {cols:6, rows:3, scrollback:1000, reflowCursorLine:true}, 'abcdefg'],
  ['cursor_moved_default', {cols:6, rows:3, scrollback:1000}, 'abcdefg\n']]) {
  const t = new Terminal(opts);
  await new Promise(r => t.write(input, r));
  t.resize(4, 4);
  console.log('resize_6to4_' + label + ':', JSON.stringify(rows(t)));
}
```

libghostty 侧复跑即仓库既有命令：`python3 validation/ghostty-vt/run_native.py --cache <dir> --output <json>`（固定哈希校验、19 项必过）与 `node validation/ghostty-vt/probe-wasm.mjs`。

### 条件二：双壳中文输入/Unicode/resize/滚动/五端构建分发

**判定：不满足。** 现有证据止步于 VT 核心对照与两壳授权门控回归：

- 中文输入：两壳真机 IME 均未验证（Flutter 壳有输入法 shim 与候选 IME 观察补丁，README 明确真机未验；Tauri 壳逐键/IME 仅本地隔离测试）。libghostty-vt 不提供 IME。
- Unicode：核心层平手（上表）；Flutter 壳组合重音渲染缺陷的修复是候选补丁，默认依赖未切换。
- resize：两壳远端观察均不发远端 PTY resize（Tauri 80×24 固定、Flutter 布局收窄不发）；核心层 reflow 差异能否进入两壳取决于桥接与远端尺寸协商，均未实现。
- 滚动：已核实的 herdr 远端观察路径不保留滚动历史（Flutter 观察入口不累计 scrollback；Tauri full 恢复销毁重建实例，`scrollback:0`）；普通 SSH 会话的用户滚动行为本页未测，不外推。libghostty-vt 1.0.1 的 scrollback 语义本页未评估。
- 五端构建分发：官方制品无 Android AAR/Linux 预编译（见上节表）；libghostty 路线的五端绑定、打包、签名均未开展，两壳现有五端构建证据只覆盖 xterm/terminal_view 路线。

### 条件三：隔离分支与可操作回退

**判定：回退方式已明确，隔离原型分支待创建，暂未验证。** 当前尚无 libghostty 迁移原型分支。对未来原型的回滚方式明确：原型在独立分支开发，不触碰生产依赖与主干；未合入时回退即丢弃该分支/工作树或回到既有提交（基线 `f378e9a`/`main`）；若已合入，回退即 revert 该合入提交。原要求为“隔离分支 + 明确回滚方式”，未含实装开关或回退演练；隔离分支的隔离效果在原型分支创建前未经实际验证。

### 门禁结论

条件一未测得关键能力优势（Unicode 类全平手、resize 差异可用公开选项消除、无效字节为显示策略差异），条件二缺口横跨 IME/resize/滚动/五端分发，条件三回退方式已明确但隔离原型分支待创建、暂未验证。**不迁移。** 若继续：先在 Tauri 受控试验页接官方 1.0.1 WASM 复核浏览器内有 DOM 场景，再评估 Flutter FFI 与 IME/绘制门槛；原型一律独立分支。
