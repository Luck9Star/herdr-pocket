# libghostty-vt 1.0.1 真实 core 对照

2026-11-15：仅验证终端 core，不修改 Flutter/Tauri 产品。官方 Apple 静态库已在本机 macOS arm64 链接并执行；不是交叉编译、iOS 设备或窗口渲染结果。

## 复现

需要 macOS arm64、Python 3、Apple Command Line Tools 的 `cc`。不需要 Xcode GUI、Zig、凭据或真实远端。

```sh
python3 validation/ghostty-vt/run_native.py \
  --cache /tmp/herdr-ghostty-vt-1.0.1 \
  --output /tmp/herdr-ghostty-vt-1.0.1/result.json
```

**默认预期退出码为 0**：19 项必过检查验证每次连接创建新实例的策略；另有两项 `observations` 明确保留 reset-only 假设的否定结果（`supported:false`）。这不表示 reset 能隔离会话。其他检查失败、C API/构建异常仍退出非零。

若单独要求 reset-only 也能隔离输入流，增加 `--require-reset`；1.0.1 的这次实测预期退出 1，报告保留 `😀Z` 和 `Z` 两条反例。脚本只在 `/tmp` 下载、解包、编译并输出结果；源码目录不存放发布二进制。

构建核心命令为 `cc -std=c11 -O2 -Wall -Wextra -Werror -arch arm64 -I…/Headers probe.c …/libghostty-vt.a -o …/probe-arm64`。完整命令、编译器、源码 SHA256 与系统信息写入本地结果。已归档的紧凑结果见 [native-macos-arm64-20261115.json](results/native-macos-arm64-20261115.json)。

Node/WASM 不需要 Apple 平台、编译器或 npm 依赖，使用 Node 22 或更新版：

```sh
node validation/ghostty-vt/probe-wasm.mjs
# 或使用别人已下载的官方小型 WASM 包，脚本仍会核对固定 SHA256：
node validation/ghostty-vt/probe-wasm.mjs /tmp/ghostty-vt-1.0.1-small.wasm /tmp/wasm-result.json
# 独立否定 reset-only 假设，预期退出 1：
node validation/ghostty-vt/probe-wasm.mjs /tmp/ghostty-vt-1.0.1-small.wasm /tmp/reset-result.json --require-reset
```

不传路径时下载到系统临时目录；指定文件不存在时也只从下述官方 URL 下载，哈希不符即停止。WASM 实跑 9 项必过检查、相同两项 reset 观察；[结果](results/wasm-node-20261115.json) 与 native 分开保存。它调用官方 C ABI，没有使用 npm 的 `ghostty-web`、自建 Zig 产物或浏览器适配包；不将 Node 结果称为浏览器绘制验收。

## 固定来源与校验范围

- [官方标签 vt-1.0.1](https://github.com/ghostty-org/ghostty/tree/vt-1.0.1)：tag object `e9dc690b08bde7e2ec9c7aff8a18a85c9cade46d`，release commit `108cacb17ed8990840cd14abfce43d8ed8503ca1`。native Python 脚本逐次核对 GitHub API 的这两层绑定，并记录 GitHub 返回的签名验证状态；这不是本脚本独立执行 GPG 验签。Node 脚本核对的是固定官方包哈希，不单独查询标签 API。
- [官方 SHA256SUMS](https://release.files.ghostty.org/libghostty-vt/1.0.1/SHA256SUMS)：SHA256 `bb7a3cf9d6de0f9cb278a94006a96586375de5d56d4df74e03ea59dac035a069`。
- [官方 xcframework](https://release.files.ghostty.org/libghostty-vt/1.0.1/ghostty-vt-1.0.1.xcframework.zip)：SHA256 `c0f9631277f726154c8f521954d17cdc41aac4626fc0df8cf925a19ee58e829b`。脚本同时核对固定哈希与固定清单中的条目，每次从已验证压缩包重新提取头文件及库。
- [官方 small WASM](https://release.files.ghostty.org/libghostty-vt/1.0.1/ghostty-vt-1.0.1-small.wasm)：SHA256 `e226900d2126faab515668e5400b69fc78ba3d99aaf9525b325f79707b29bf01`。Node 脚本核对该固定哈希，并确认 module 没有 host imports。
- HTTP 请求显式携带 `User-Agent: herdr-pocket-prototype-validation`；裸请求曾遇到 403。脚本未实现 minisign 验签，不将单纯“取到清单”称为独立签名验证。

使用该包的 `macos-arm64_x86_64` slice，产物实际为 Mach-O arm64，仅链接 `libSystem`；运行时 `ghostty_version()` 返回 `1.0.1`。发布包内其余平台 slice 没有在本探针运行。官方 [`vt.h`](https://github.com/ghostty-org/ghostty/blob/108cacb17ed8990840cd14abfce43d8ed8503ca1/include/ghostty/vt.h) 声明 C ABI 从 1.0 起稳定；探针使用的是发布包内 1.0.1 头文件，而非 tip 文档猜测接口。

## 真实结果

| 检查 | 本机实际结果 |
| --- | --- |
| `a中😀é!` 的每一种两段切分、逐字节输入 | 文本相同；光标列为 7，覆盖 CJK/emoji 宽度 |
| `e` + combining acute；mode 2027 的家庭 ZWJ emoji | 文本保留；分别占 1、2 列 |
| SGR bold/red 与 reset；ANSI/Unicode 全部逐字节 | 样式状态及文字通过 |
| 1049 alternate screen、CUP、退出恢复主屏 | `ALT` / `MAIN` 通过；切换屏幕本身没有被当作隐含 CUP |
| 本地 6×3 → 4×4 resize | dimensions 更新，reflow 后内容仍为 `abcdefg`；未连接远端 PTY |
| 同实例半截 UTF-8 后续写 | `f0 9f` + `98 80 5a` 正确成为 `😀Z`，证明输入流会跨 write 保留半截码点 |
| 半截 UTF-8 → `ghostty_terminal_reset()` → 尾字节 | **仍为 `😀Z`**，不能作为跨 SSH 会话的流隔离 |
| 半截 CSI `ESC[31` → reset → `mZ` | **得到 `Z`**，此前解析状态仍消费 `m`；新实例对应字面 `mZ` |
| 释放旧实例、创建新实例后写入 UTF-8 尾字节 | `��Z`；没有拼出旧会话的 emoji。替代字符是新流自身孤立 continuation bytes 的处理，不能等同于串会话 |
| DSR 回调、只读丢弃策略 | 可在本地捕获 `ESC[1;1R`；移除 `WRITE_PTY` 回调后 DSR/DA 不再触发该回调；新实例不继承回调 |
| Up 键编码 | 普通模式 `ESC[A`，application 模式 `ESCOA`；只编码到内存，没有发往远端 |

native 的 20 次独立进程重跑报告完全一致，包括两项 reset 隔离否定结果。此处没有吞掉异常、固定 sleep 或真实 SSH。DSR 回调只复制到内存；C 探针没有 socket、PTY 或远端写入路径。Node/WASM 的回调与键编码不在这份小探针范围，由 native 结果单独覆盖。

## 对两壳迁移的含义

可考虑共用的层是 VT 字节流解析、Unicode/宽度与终端状态、SGR/alternate screen、导出文本和键编码。真实 core 检查支持做适配原型；稳定 C ABI 可减少两套状态机的差异。**每次连接应分配新 core**，并沿用现有 session/generation 绑定，不能因为有 `reset()` 就复用输入流。

迁移仍需 Flutter FFI/Tauri WASM 或原生桥、绘制及字体、选择/滚动、输入法、无障碍、帧消费 ACK 和实例生命周期的适配。本探针没有证明这些 UI 行为、性能、资源释放压力、手机触控或五平台运行。它也没有验证单元格像素、复杂脚本塑形、所有 emoji 或终端兼容性全覆盖。

只读观察端必须把终端产生的 PTY reply 与用户授权输入分开：本地解析 DSR/DA 不等于获准回写远端。本次明确验证了移除回调的丢弃策略；键编码结果也只留在内存。现有 SSH、pin、凭据保护、输入守卫和远端 PTY resize 政策仍由产品适配层负责，core 不提供这些验收结论。
