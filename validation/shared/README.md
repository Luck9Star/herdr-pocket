# 同规格终端 fixture

两条验证壳只能复制本目录，不自行变更字体或内容。修改 fixture 后须更新 `SHA256SUMS`，重跑两条路线。当前 `herdr-terminal-v1` 为合成 ANSI：不声称已录制/运行真实 Powerlevel10k、Oh My Posh 或 herdr。

- 终端：80 × 24，14 logical px，2,000 行 scrollback；手机 390 × 844，小手机 360 × 740，桌面 1440 × 900，窄桌面 720 × 900。比较时同一设备、系统缩放、视口、键盘和模式。
- 字体：Nerd Fonts v3.4.0 的 JetBrainsMono Nerd Font Mono Regular，SHA-256 见清单；原始字体 OFL 与 Nerd Fonts 图标/修改许可一并附带。CJK/emoji 使用平台 fallback，必须在相同设备比较并记录系统版本，不能把不同系统fallback当作同字体实验。
- 负载：`load-chunk.txt` 精确 4,096 UTF-8 bytes × 256 = 1 MiB；最多 65,536 在途 bytes。消费回调/信用额度推进，`intervalMs: 0` 表示无额外人工延迟，不表示跳过背压。每次输入上限 4,096 UTF-8 bytes。
- 内容：ANSI 属性、定位、清屏、备用屏幕，Nerd/Powerline/CJK/emoji/组合字符；合成字符集不等于主题兼容性结论。

## 同设备操作顺序

`remote-frame-geometry-v1.json` 给 Flutter、Tauri 和 Rust 共用，覆盖 22 组连续帧，含尺寸越界、改变尺寸的全帧及必须拒绝的增量。手机观察画布默认 80×24，也可选 120×40 或 160×50。在新帧、自身视口和共享 PTY 之间区分尺寸的约定见 [远端协议](remote-contract.json)。

1. 保存产物 SHA、源 SHA、fixture/font SHA、系统/WebView、设备型号、横竖屏、缩放、键盘/IME版本到 `result-template.json` 的副本。
2. 打开两壳，默认观察不产生输入。进入逐键，依次输入 `inputCases`：中文拼音组合期间不应捕获字节，提交后只出现一次；回车为 `0d`，Ctrl+C 为 `03`，方向键序列按应用模式实测。
3. 中文组合未提交时切标签/焦点，再提交；旧组合不能进入新目标。返回旧标签同样不能补发旧内容。
4. 草稿与多行粘贴检查发送预览；字节与预览一致，不自动加回车。已发结果未知不回填草稿。复制、软键盘展开/收起、触控选择滚动逐项记录。
5. 播放 ANSI full/delta/备用屏幕；记录截图、光标列与属性，不凭图标可见判 cell 正确。真实 TUI 需后续隔离 SSH/herdr 录制，不由备用屏幕 fixture 代替。
6. 在持续负载中切标签、分屏、窄化、后台/恢复、注入断线和迟到帧；恢复要求新 full 并回到观察。任何布局变化都不调用远端 resize。
7. 正确性通过后才记录整 App 输入反馈延迟分位数、帧时间与峰值内存；Tauri 包括 WebView。壳内单次处理耗时不是性能胜负。

`result-template.json` 不预填通过；CI 构建记录与设备记录分开。三网 15 格以及 TS+ET、TS+ZT、ET+ZT、TS+ET+ZT 并发单独填 `platform-matrix.json`，普通TCP或fixture不能改变这些格。

`mobile-tabs-v1.json` 定义两条路线共同的手机多标签生命周期：独立目标、前台隐藏保留 SSH、显式恢复新 full、迟到 epoch、关闭与配置影响隔离、后台关闭和含清理中资源的容量上限。它只有虚构公开元数据；12 个用例是验收要求，不能因为文件已随包复制就填通过。各路线分别记录模型、隔离传输、真实 GUI 和设备执行结果；单条全局未知输入记录的限制须继续披露。

`session-watch-v1.json` 固定 herdr 0.9.5 / protocol 22 的订阅请求、确认、生命周期事件、逐 pane 状态和丢失消息，以及两路线共同的持续看板验收条件。事件只使旧快照失效；界面内容必须由后续权威快照更新，不能把事件 payload 直接应用为行状态。看板 freshness 与终端 full 分离，目标按 pane 和稳定 terminal 联合核验；隐藏后退休订阅，恢复仍须显式操作。文件及合成测试不代替真实 herdr、手机或 overlay 结果。

`target-input-journal-v1.json` 定义 IJ01–IJ12：按持久远端目标隔离未知输入，原子迁移旧单条记录，按活动请求租约和原始记录精确清理。上限为 32 个目标、每条 8192 字节、整个存储 262144 字节，超限不淘汰未决记录；磁盘只存公开目标与 request ID，不存输入正文。两路线的历史字段边界单独列出，缺失字段不能用当前主机补齐。用例与示例表均为合成资料，执行证据另行记录。

`tailscale-managed-v1.json` 定义 TS01–TS12：显式授权、完整二进制 StateStore、不可换绑的节点、迟到回调退休、Close 失败恢复、Android 私有目录、跨 provider 隔离及真实手机闭环。共享合同不改变字体或终端负载；隔离 native/JNI 检查不代表两套 GUI、设备或真实三网通过，15 格和 20 格矩阵仍需独立证据。

`tailscale-settings-v1.json` 固定公开配置的默认值、精确字节 SHA-256 绑定（4 个正向向量）及 21 个拒绝向量。Rust 和 Dart 保存／导入／启动对齐；授权 URL 与公开 control URL 的上限分别为 4096／2048 bytes。它不含任何真实身份或授权链接，也不改变终端公平比较 fixture。
