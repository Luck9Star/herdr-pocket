# Android 普通 SSH 主机换钥专项

状态：2026-11-17，**Flutter／Tauri Android API 35 模拟器验收均通过，官方工件及独立服务端证据已核验**。本页单独记录普通 SSH 的 S10「主机指纹发生变化」，不更改[上一轮普通 SSH 验收](63-design-parity-and-direct-ssh.md)或[Android 双网验收](67-android-dual-network-startup.md)的来源与结论。

## 已复现的修改前基线

基线源码为 [`f9d5595b45ca8db54d0dde867e082273ff4ace6c`](https://github.com/Luck9Star/herdr-pocket/commit/f9d5595b45ca8db54d0dde867e082273ff4ace6c)。设计参照已核对的 [S10 390×844 手机画面](../design/evidence/v2-S10.png)与[换钥阻止认证、返回审查／取消约定](../design/v2-coverage.md)。画面和本地交互证据均不代替 Android 设备运行。

| 客户端 | 已复现的行为 | 证据范围 |
| --- | --- | --- |
| Flutter | 从首页真实 `Navigator.push` 打开普通 SSH，真实 loopback SSH 对端由 A 换为 B 后进入 S10；凭据已清空，服务端未观察认证。点击实际 AppBar 返回按钮仍能退出到首页。 | Flutter 3.47.9、390×844、Android platform variant 的 Widget 测试；1 项通过。只读复制的页面与基线提交逐字节一致；未测试 Android 系统返回或真机。 |
| Tauri | 320（触摸）／390（鼠标）宽浏览器中，S10 仍可通过全局导航离开；独立控制器测试中，失败重探会丢失旧指纹 A，但仍保持阻止状态。 | 本地浏览器页面导航与直接控制器测试，不计为真实 SSH、Android 模拟器或原生设备通过。不据此推断已发送认证或输入。 |

四份基线观察合并为[本轮脱敏记录](evidence/android-ssh-key-rotation-20261117/baseline-observations.json)，与后续设备工件分开。

前述问题与「错误指纹时本次 SSH 连接已拒绝」是不同检查：本轮另行验证取消、导航及失败重探不会绕过待复核状态或丢失旧信任。

## 同一目标的验收约定

每壳使用独立的临时 SSH 服务。一个案例始终保持相同 host:port、账号与服务进程，服务端预先生成两把独立主机密钥及完整 SHA256 指纹：第一条连接提供 A，后续持续提供 B。客户端确认值须与独立服务端值一致，不能只比对客户端自身两处文本。

| 已完成并关闭的连接 | 客户端动作 | 必须成立的独立服务端证据 |
| --- | --- | --- |
| 1：A | 初次探测并人工核对 A | 仅探测，认证尝试／成功、PTY、shell、输入／输出均为 0。 |
| 2：B | 带已确认 A 发起连接，发现 B 后进入 S10 | 连接拒绝且关闭；认证尝试／成功、PTY、shell、输入／输出仍为 0。 |
| 3：B | 取消后主动发起全新探测，重新核对 B | 独立新连接；确认前仍无认证、PTY、shell 或输入／输出。 |
| 4：B | 明确确认 B 后，重新输入临时密码并主动连接 | B 校验通过，独立记录成功认证、PTY、shell、测试标记及回显，最后主动断开并确认关闭。 |

S10 拒绝页的普通返回与全局导航不能绕过复核／取消选择。明确取消后回到表单，正常导航恢复；留在同一目标时，旧指纹 A 保留，凭据入口、连接与终端输入在 B 明确确认前仍维持关闭。失败或取消的新探测不能替换 A、释放锁或自动重试认证。确认 B 本身也不自动连接或重放旧输入。

共同 fixture 的 `rotation_evidence(2 / 3 / 4)` 分别校验准确连接数、A/B 顺序与每条关闭状态；最终阶段仍逐条复核前三条零认证／PTY／shell／输入输出，避免只看累计成功布尔值。服务端不凭零认证自行推断一条连接是探测还是拒绝；动作意图由客户端检查点及连接顺序共同确定。`authAttempts` 计正常客户端认证检查回调，`outputBytes` 计成功发送的 shell 字节，不代表客户端已显示；界面回显须另行核验。

## 本轮验证状态与边界

两壳统一应用源码为 [`77052412af63cff61392e1fc412e7d2fe35552fd`](https://github.com/Luck9Star/herdr-pocket/commit/77052412af63cff61392e1fc412e7d2fe35552fd)。当前设备运行如下；运行成功与工件来源、逐条证据核验分开记录。

| 客户端 | 设备运行 | 当前结论 |
| --- | --- | --- |
| Flutter | [Actions 43981097578](https://github.com/Luck9Star/herdr-pocket/actions/runs/43981097578) | 官方运行 success；脱敏工件解包、ABBB 各阶段及清理均已核验，通过。 |
| Tauri | [Actions 43981097643](https://github.com/Luck9Star/herdr-pocket/actions/runs/43981097643) | 官方运行 success；脱敏工件解包、ABBB 各阶段及清理均已核验，通过。 |

### Flutter 已核验设备证据

[原字节结果 JSON](evidence/android-ssh-key-rotation-20261117/flutter-43981097578-result.json)记录 `rejected / cancelled / reprobed / complete` 四阶段总连接数 **2／2／3／4**。前三条 A／B／B 的认证尝试与成功、PTY、shell、输入及输出均为 0；第四条 B 认证尝试与成功各 1 次，PTY／shell 各 1 次，**输入 9 字节、输出 60 字节**，测试标记、客户端远端回显及主动关闭均成立。最终四条连接全部关闭，宿主确认发生在驱动退出前；原普通 SSH 场景与受检清理也通过，没有上传原始日志。这些字节数属于 shell 应用数据，不代表 SSH 总流量。

[设备 S10 拒绝页原图（1080×2340）](evidence/android-ssh-key-rotation-20261117/flutter-43981097578-rotation-rejected.png)已目视核对：完整 A／B 指纹、同一目标、重新核对与取消两项动作均可见，没有凭据。此图来自本轮 Android 模拟器工件，与前述 390×844 设计参照及本机 Widget 图分开。

来源为[官方证据工件 14283905471](https://github.com/Luck9Star/herdr-pocket/actions/runs/43981097578/artifacts/14283905471)：ZIP **525,090 字节**，SHA256 `66cc7730e79a3077758539b1d379bd32dcebf0808fa8498f207b888a539634d8`，重算与官方 digest 相等。解包 JSON **11,091 字节**，SHA256 `3519ffd97839612ef973a4aea9e72dddc545bf7a2d16042bb0ea935451f791de`；归档与核验文件逐字节一致。截图 SHA256 为 `6e49859e7debc51782eea45a3d4901aa99ee31ebb887c0f3ddeb415534b96e9a`。工件保留有限；过期后须依据完整源码与固定环境重新运行，不能将重建自动视为原设备结果。

### Tauri 已核验设备证据

[原字节 manifest](evidence/android-ssh-key-rotation-20261117/tauri-43981097643-manifest.json)记录独立阶段 **2／3／4**，取消后复查仍为 2 条连接。前三条 A／B／B 的认证尝试与成功、PTY、shell、输入及输出均为 0；第四条 B 认证尝试与成功各 1 次，PTY／shell 各 1 次，**输入 9 字节、输出 60 字节**，远端回显与主动断开通过，最终四连接全部关闭。原普通密码、加密私钥与受检清理均通过。

[设备 S10 拒绝页原图（1081×2341）](evidence/android-ssh-key-rotation-20261117/tauri-43981097643-rotation-rejected.png)已目视核对：完整 A／B 指纹和同一目标可见，仅有重新核对与取消两项动作，没有凭据。来源为[官方证据工件 14283074728](https://github.com/Luck9Star/herdr-pocket/actions/runs/43981097643/artifacts/14283074728)：ZIP **210,237 字节**，SHA256 `0ab58be8e7a6a371160bed80345bd6960a6ec76d52ca51eb850bf442cd510f08`，与官方元数据及下载字节核对相等。manifest **5,655 字节**，SHA256 `0ee5316b80f798eb94de5ef097007d0c70d8fef54d113bd77cc21c356ff39bf7`；截图 SHA256 `566d75cd81ad42427848c444a4041dfe9e9c0c18d709c7e509b11033dbdd0791`，两份归档均与核验文件逐字节一致。

### 本地回归与范围限制

- 主控独立复验：干净 Flutter 工程完整套 **591 通过／5 跳过**；Tauri 前端 **634／634**、Android driver **20／20**。Flutter 320／390 宽首页入栈回归及 Tauri 两宽浏览器 S10 交互均通过。它们是本地框架／浏览器与脚本证据，不计为 Android 设备通过。
- 本地共同 fixture 与 runner：CI 钉住的 Paramiko 4.0.0 环境，普通 SSH 相关回归 35 项及加密私钥 fixture 1 项通过；含真实 A→B→B→B、四类失败认证、分阶段校验及反例。Flutter 临时候选工程 `flutter analyze lib integration_test` 无问题；本机另以真实 SSH 对端执行新换钥 UI 步骤及后续原普通连接流程，1 项通过。此项使用 Android target platform 的本机测试引擎，不增加设备覆盖，也未验证截图捕获。
- 共享 remote harness 完整回归 **453 项，4 项跳过**；跳过项不计通过，不替代设备运行。

本次通过 Herdr 分工协作：Pi 负责 Flutter 页面与 Widget 回归，Claude 负责 Tauri，Sol 负责共用 SSH 协议夹具及 Flutter 设备驱动；主控独立复验并核对官方工件。

桌面 Widget、浏览器、编译成功及历史普通 SSH 成功均不计为本轮 Android 换钥通过。手机真机、真实软键盘／中文 IME、生产 SSH 主机、三网及五平台不在本轮范围。
