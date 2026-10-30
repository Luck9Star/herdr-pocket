# 两项阻断修复与独立验收

2026-10-30。实验候选已取得Ubuntu与macOS绘制回归通过证据，EasyTier候选Linux、macOS、Windows已通过检查、嵌入离线测试、链接与加载。两项阻断均有经验证的实验修复；GUI接线与真实组网仍未验证。官方`terminal_view 0.5.0`原归档与旧baseline包仍有已记录缺陷；本项目补丁不是官方发布，也不构成UI框架定案。修复工作以已保存的失败证据为起点，不重置原始设计或工作区。当前环境为云端与本机 Mac，本轮独立审阅不打开应用、不重启 Penpot/MCP、不安装 SDK，也不接触真实授权文件或网络身份。

## 失败基线

| 阻断 | 固定来源和已证实范围 | 不能推导的结论 |
| --- | --- | --- |
| 组合重音没有画出 | `terminal_view 0.5.0`，herdr-pocket `ed35d840` 的真实 TerminalPainter 诊断；buffer/getText 保留 `e+0301 A+030A n+0303`，cursorX=5，base/marked PNG相同且都有138非透明像素。[原证据](evidence/flutter/combining-ed35d84/combining-render.json) | 不是输入或存储丢失；不等于Flutter整体不可用，也不证明其他Unicode/IME正确 |
| EasyTier Linux/Windows桥编译失败 | Heeler native `6a2817fc02aeb552df251d9478753c22fd4738bb`、EasyTier `728ba94b5029240add6204eed591f22e4e039e6b`、Rust1.95.0；Linux无`SO_NOSIGPIPE`，Windows无UnixStream/RawFd及socket常量，存在fd类型不兼容。[三桌面结果](../validation/native/evidence/2026-10-30-desktop-matrix.json) | 是这份固定桥接代码的移植阻断，不是EasyTier协议本身不可跨平台，也不代表macOS已经入网 |

[前阶段汇总](09-prototype-validation.md)保留原始失败记录。新补丁须保留固定来源、补丁hash、许可、应用步骤和失败回归；不能用浮动版本替代本轮对照。

## 修复验收条件

1. **组合字形画对，而不只是发生像素变化。** 固定字体、尺寸、位置和光栅化环境，用独立参考绘制或受控预组合字符作对照，确认重音位于相应基字符上方，没有覆盖邻格或替换基字符。base与marked不同仅为必要条件；空白、tofu、颜色改变或错位也可能造成不同。
2. **终端语义保持。** 原始码点、getText、列宽、光标和相邻字符位置保持；覆盖ASCII连续段前后、非ASCII/CJK宽字符、多个组合符、行边界、SGR颜色/样式及光标绘制。所有未覆盖项明确列为未验证，不因一个样例通过便称完整Unicode支持。
3. **Linux平台修复保留关闭行为。** 只在适用平台设置Apple socket选项，不能靠忽略所有错误掩盖问题；必须检查对端关闭后写入的错误及进程存活，避免在嵌入宿主时依赖测试runner偶然的SIGPIPE配置。
4. **Windows句柄与生命周期明确。** SOCKET不能截成i32或当作Unix文件描述符；C ABI若返回i64，应明确值域、错误哨兵、有效对象和配套关闭函数。失败、取消、半关闭、双关、迟到任务及资源回收必须有单一所有者。若采用loopback TCP配对，监听仅限loopback且应核实端点，避免错误本地连接被配对到流。
5. **按实际层级判定。** cargo check、链接、加载、本地双向字节流、overlay入网、GUI→SSH/herdr闭环分别报告。平台测试结果逐格记录，编译通过不改变15格单网或20格并发运行矩阵；本地loopback也不等于真正EasyTier入网。

## 独立审阅记录

补丁作者分工：Flutter候选绘制补丁由Flutter验证代理负责；EasyTier平台桥由Tauri/原生验证代理负责。审阅者仅修改本页及`docs/evidence/repair-review/`，补丁和测试由各自作者修改，主代理统一窄提交。

| 对象 | 代码审阅 | 运行证据 | 当前裁定 |
| --- | --- | --- | --- |
| terminal_view补丁 | `2d0fb1d…`静态审阅与前后SHA核验通过 | e216eb1 Ubuntu/macOS原诊断及各9回归测试通过，两端各10组PNG逐一匹配参考 | 仅候选固定字体已测场景通过；旧baseline与官方0.5.0仍有缺陷 |
| EasyTier Linux guard | Apple-only cfg及Unix旧API边界已审 | d60b8d0固定Rust1.95.0检查、嵌入9测试、链接、加载通过 | 此固定来源编译阻断已解除；Linux旧fd仍须调用方MSG_NOSIGNAL |
| EasyTier Windows桥 | 新opaque u64 ABI、生命周期/取消/预算及Runtime guard静态通过 | d60b8d0 Windows检查、嵌入8测试、链接、加载通过 | 新ABI实验修复通过；旧fd仍不支持Windows，真实overlay/GUI未验 |

Flutter初审见[补丁核验记录](evidence/repair-review/flutter-static-review.json)：采用现有组合单cell绘制路径，ASCII批处理在组合cell前截断；选区及无overlay的光标重绘传入相同combined，parser与宽度表未改。依赖通过CI生成目录的显式path override注入，pub缓存不改；原归档、补丁及修改文件前后均有hash，其他依赖lock块要求完全一致。

EasyTier初审与额外本机结果见[独立记录](evidence/repair-review/native-static-and-macos.json)。32个配额包含pending，ID溢出拒绝且不复用；`spawn_dial`在生命周期锁内启动并登记，修正了先spawn后登记可能漏等迟到任务的窗口。close先撤销handle，再发取消并等待dial/pump，不等待读写锁。FFI先检查已有Tokio runtime并返回错误，未使用嵌套block_on；同一函数使用者必须在专用工作线程运行。

新增ABI不传递OS句柄，内部每方向64KiB duplex另加copy pump的有界8KiB缓冲。读写正数是本地进度，写入超时/取消/错误保守返回UNKNOWN且禁止自动重放。Unix旧fd入口仍保留，Windows显式不支持旧入口，Linux旧入口的普通POSIX write仍可能SIGPIPE；新便携路径的本机子进程试验包含默认SIGPIPE的raw-send阳性对照与安全路径对端关闭。该测试使用已有Rust1.96.0，仅补充Mac core证据，不能替代固定Rust1.95.0云结果。

Flutter的4项candidate工具隔离/hash/lock guard已由审阅者独立执行通过；9项绘制回归代码已审阅，采用同字体NFC和独立TextPainter作像素参考，包含原码点/列宽、SGR、宽邻接、追加组合符后的行缓存、实际TerminalView块光标与选区覆画。多组合符复杂脚本、上游下划线策略、真人IME与原生clipboard仍不在这9项结果内。

Runner审阅：候选工作流仅codex分支、contents只读，使用全新RUNNER_TEMP目录；逐项核对reference、原文件、补丁、修改后文件与复制模块hash。真实Heeler仅选择名称包含pocket的离线测试；共享库加载只解析5个符号并调用无效handle的close，不启动node。Windows本仓库的补丁与模块已用native `.gitattributes`固定字节，避免CRLF破坏来源hash。独立补丁核验见[来源校验](evidence/repair-review/native-patch-hashes.json)。当时静态审阅放行实验CI；随后实际结果按下文逐平台记录。

## Flutter实验候选：Ubuntu实际验收

[run40993758160 / job123861998310](https://github.com/Luck9Star/herdr-pocket/actions/runs/40993758160/job/123861998310)，源码`e216eb1db83e562cbff5c128cc9eedcc293203cf`，补丁SHA256 `2d0fb1d7283b034eb8161651f5c1cee0343df2877ebd6863e6639782ad8e5833`。独立读取GitHub job确认完成且成功；对下载后的30份证据文件重算hash，manifest与固定归档/补丁一致。

原失败fixture现为base138、marked169非透明像素，码点和cursorX=5保持。9项回归产生的10组实际／参考PNG已独立逐一核对相同，包含NFC、独立TextPainter、SGR、宽邻接、缓存、块光标、选区；另人工查看重音、ASCII邻接与两种覆画图，确认有非空、位置合理的字形。这超出了“图片变了”的弱判据。结果仅限Flutter test engine的这些固定字体场景，未替代原生IME、clipboard、真实主题或修复包设备验收。

原始证据在[Ubuntu候选目录](evidence/flutter/repair-e216eb1/ubuntu/verification.json)，审阅结果在[独立复核](evidence/repair-review/flutter-ubuntu-ci-review.json)。原ed35d840失败图与日志保留，不覆盖原包结论。

依赖核对：除terminal_view改为显式path外，所有其他**package依赖块**相同。SDK最小约束元数据另从`flutter >=3.19.0`变为`>=3.18.0-18.0.pre.54`，实际固定工具链仍为Flutter3.47.9；因此不能称“整个lock只有terminal_view变更”。候选lock SHA为`8061fdb6e4fb277952fe6b987de4740fac7bc9db7532e6feeba78e6e08eb9ba0`，该差异已单独记录。

## Flutter实验候选：macOS实际验收

同一source、patch和candidate lock的[macOS job123862387789](https://github.com/Luck9Star/herdr-pocket/actions/runs/40993758160/job/123862387789)已独立读取确认为success。原诊断base155、marked193非透明像素，码点与cursorX=5保持；9项测试的10组PNG同样与同平台参考完全一致。审阅者重算27份下载文件hash并人工查看重音、红色SGR与块光标图；详见[Mac独立记录](evidence/repair-review/flutter-macos-ci-review.json)。

这是macOS runner中的Flutter test engine，不是本机原生App复测。本轮没有打开GUI。CJK邻接样本可见fallback方块，所以该项只证明组合字形没有改变相邻宽字符的占位和参考布局，不能称中文字体显示通过。两个系统之间的像素数量不同不作为性能或正确性差异，逐平台与各自同字体参考比较。

## EasyTier实验候选：三桌面实际验收

[run40993901952](https://github.com/Luck9Star/herdr-pocket/actions/runs/40993901952)，源码`d60b8d0a5def48a4af27b6544c48baea1bbf810f`，补丁SHA256 `c6cf73a5e26bab665c226f37c81d55671f801e84d67d340bd18dc670529b06a4`。独立读取三个job均success；每平台31份artifact文件通过SHA256SUMS重算，candidate provenance与固定manifest完全一致，实际使用的Heeler Cargo.lock与原固定提交逐字相同，Rust日志为1.95.0。

| 层级 | Linux x86_64 | macOS arm64 | Windows |
| --- | --- | --- | --- |
| 真实patched Heeler cargo check | 通过 | 通过 | 通过 |
| 嵌入便携流与FFI离线测试 | 9通过 | 9通过 | 8通过（不计Unix专用SIGPIPE测试） |
| cdylib最终链接 | 通过 | 通过 | 通过 |
| 新ABI加载 | 5符号解析；invalid close=-6 | 5符号解析；invalid close=-6 | 5符号解析；invalid close=-6 |
| 默认SIGPIPE子进程与安全关闭 | 通过 | 通过 | 不以Unix测试外推 |
| EasyTier入网／overlay拨号 | 未验证 | 未验证 | 未验证 |
| GUI、设备与跨网络并发 | 未验证 | 未验证 | 未验证 |

**Linux这份固定桥的编译阻断已解除**；这与旧Unix fd接口的调用责任是两件事。旧接口在Linux使用普通POSIX write仍可能SIGPIPE，调用方必须MSG_NOSIGNAL或等价安全写法；便携handle接口的安全路径通过关闭回归不能替代旧调用方审计。Windows通过的是新增handle ABI，旧Unix fd入口继续显式unsupported，不能按原int-fd调用方式直接替换。

嵌入测试包括pending容量、双向字节/半关、取消、迟到完成释放、不复用handle、连接隔离、UNKNOWN写入与嵌套runtime拒绝。加载只调用无效close，没有启动网络节点。原生库大小与digest由runner记录，证据artifact没有分发该库二进制；尚非可用原生SDK发布。详见[独立Unix CI复核](evidence/repair-review/native-unix-ci-review.json)。

Flutter的Windows首轮候选构建因git apply继承autocrlf而触发修改后hash拒绝；这不是组合字形回归失败。`c27535d`将行尾规则限定在本次git apply命令，并新增回归，审阅者独立运行5项工具测试全部通过。保留原始失败记录，修复后的[Windows job123864766427](https://github.com/Luck9Star/herdr-pocket/actions/runs/40994503435/job/123864766427)已独立查询确认为success，源码`c27535d3ed7174ad7b722d9e086ee59e9db11f5d`；仅为构建通过，Windows设备运行仍未验证。

## 可获取的Mac修复候选包

[macOS arm64实验候选artifact](https://github.com/Luck9Star/herdr-pocket/actions/runs/40993758160/artifacts/12950213273)，源码`e216eb1`，其中`flutter-macos-debug.tar.gz`的SHA256为`c20d9377ea277f16f66ad29467613735ee403853d0ca853e50fdf347ff31c502`。审阅者独立对已下载归档重算hash、核对manifest中的补丁/字体/fixture并确认含App可执行文件，**没有启动该候选App**。[包核验记录](evidence/repair-review/flutter-macos-package-review.json)。

这是包含实验绘制补丁的测试包；前阶段`c8d70abf` baseline包仍没有此补丁。下载需仓库权限，artifact保留14天；先核对源码SHA及校验和，再在有条件时进行原生App验收，不绕过系统安全策略。真实IME、原生clipboard、触控及远端链路继续未验证。

后续`c27535d`只修Windows材料化行尾与manifest对SDK约束差异的表述，绘制补丁SHA保持`2d0fb1d…`。其[最终run40994503435](https://github.com/Luck9Star/herdr-pocket/actions/runs/40994503435)已独立查询为completed/success：Ubuntu gate、macOS headless与五端构建全部成功。所有8个artifact的入口及保留状态见[最终CI台账](evidence/flutter/repair-e216eb1/final-c27535d-ci.json)。本轮没有逐一下载这5份新平台包，不把artifact存在当作本机安装或设备验收。

Windows最终结果来自同一d60b8d0的[job123862454366](https://github.com/Luck9Star/herdr-pocket/actions/runs/40993901952/job/123862454366)，[artifact12950937623](https://github.com/Luck9Star/herdr-pocket/actions/runs/40993901952/artifacts/12950937623)。独立复核8项嵌入测试日志、实际check/link/load命令均exit0；其中嵌套runtime调用返回-10，invalid close返回-6。31个文件重算hash时只为定位文件转换清单中的Windows路径分隔符，原始文件字节未改。证据见[Windows独立复核](evidence/repair-review/native-windows-ci-review.json)。

当前结论是**组合重音有已通过Ubuntu/macOS回归的实验绘制补丁，EasyTier三桌面有已通过编译／本地流／链接／加载的新增ABI候选**。Windows新接口需要GUI端适配专用工作线程和handle生命周期，尚未接入现有GUI。所有真实overlay入网、手机原生桥、15格单网、20格并发及首个远端产品闭环仍待后续执行，不以这些修复代替产品支持声明。
