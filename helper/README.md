# 手机配对的主机辅助命令

公开连接资料可先由主机当前登录账号生成，供手机扫码或粘贴后审查。以下命令在 `helper/` 下运行，所有目标及路径都须由操作者显式提供；`--host` 是手机可达的目标地址，不自动推断本机或覆盖网络地址。`--port` 是 SSH 端口，`--provider` 仅为连接方式标记，不包含任何覆盖网络凭据。

```sh
python -m herdr_pocket_helper profile \
  --host-public-key /etc/ssh/ssh_host_ed25519_key.pub \
  --host workstation.example --port 22 --provider direct \
  --session phone-1 \
  --socket-path /home/alice/.config/herdr/sessions/phone-1/herdr.sock \
  --herdr-path /usr/local/bin/herdr --format svg > connection-profile.svg
```

改用 `--format json` 可输出同一份扁平 v1 `herdr-connection-profile` JSON（最多 2048 UTF-8 字节）。账号固定取当前非 root POSIX 登录账号，不能用参数指定他人账号。目标为 ASCII DNS 主机名或无方括号、无 zone 的 IPv6；会话必须为非 `default` 的命名会话。socket 与 herdr 路径必须为规范绝对路径，socket 以 `/herdr/sessions/<会话>/herdr.sock` 结尾且此前有非空目录；主机公钥只读取显式 `.pub` 文件，资料不包含私钥。

**连接资料不能授权设备。** `profile` 不创建 `Host`、不读写 `authorized_keys`、不创建 `.ssh` 或授权收据。手机应先审查地址、账号、会话、路径和可信渠道核实的主机指纹；资料本身不证明持有者身份，扫码也不会自动保存主机或发起连接。设备授权仍须走下面的独立人工确认流程。

主机用户运行一次命令来审查设备公钥、明确添加授权或撤销本次新增的公钥。适用范围为非 root 的 POSIX 登录账号和 OpenSSH 默认 `~/.ssh/authorized_keys`。需要 Python 3.10+。在 `helper/` 目录创建虚拟环境并安装 `requirements.txt` 的固定依赖。

1. 手机填写目标账号、命名会话和从可信渠道核实的主机 Ed25519 公钥，生成公开请求。通过已有可信渠道把请求 JSON 交给主机用户。
2. 使用 `python -m herdr_pocket_helper preview --host-public-key /etc/ssh/ssh_host_ed25519_key.pub --request request.json` 查看账号、主机指纹、设备指纹和到期时间。预览不会创建授权文件。
3. 独立核对两端显示的账号及指纹，再用同样的参数运行 `authorize`。在控制终端输入显示的完整确认短语。stdout 输出绑定当前请求的 JSON，可复制回手机。传入 `--format svg` 并重定向到新 SVG 文件可生成公开响应二维码。手机仍须另行审查并主动进行 SSH 认证。
4. 撤销时运行 `python -m herdr_pocket_helper revoke --host-public-key /etc/ssh/ssh_host_ed25519_key.pub --request-id <请求ID>` 并在控制终端确认。相同公钥原已存在、授权项被外部编辑或重复时会拒绝自动删除。撤销限制后续认证，当前已建立连接由用户单独处理。

手机生成的 **v2 配对公开请求** 才能交给 `preview` / `authorize`；前面的 v1 连接资料不能代替授权请求。将手机显示的完整请求 JSON 原样保存为文件，或用 `--request -` 从 stdin 传入。预览时核对 `request_id`、账号、主机和设备指纹，再在原 POSIX 账号下明确运行 `authorize`。保留这个请求 ID 和主机公钥值，便于后续按确切请求核查；工具不会根据设备名称猜测请求或扫描个人目录。

原请求文件或保存路径丢失时，不必重建身份或重新授权。只要仍知道原 `request_id`，就可在**原主机账号**下，用同一主机公钥值只读查看这一条收据：

```sh
python -m herdr_pocket_helper inspect \
  --host-public-key /etc/ssh/ssh_host_ed25519_key.pub \
  --request-id 0123456789abcdef0123456789abcdef
```

输出包含原公开请求、设备指纹、收据阶段 `receipt_phase`、授权文件快照 `observed_entry` 和 `can_revoke`；同时提供已正确引用参数的 `revoke_command`。`inspect` 不创建目录或锁，不写授权或收据，也不把过期请求重新变为有效授权。它只读明确指定 ID 对应的收据及默认授权文件；缺少 ID、收据、原账号或匹配公钥时停止，不回退其他记录。主机公钥已轮换时须提供原公钥值，不能用新公钥假定旧收据属于它。输出是一次只读快照，实际撤销仍会在确认后重新核验文件。

`can_revoke: true` 表示可明确执行给出的撤销命令；终端仍要求完整的 `REVOKE <请求ID>` 确认短语。`false`、重复公钥、外部编辑或不安全文件权限需要人工核查；原已存在的公钥不归本工具删除。`receipt_phase: revoked` 且授权条目仍缺失时，再次明确运行 `revoke` 仅生成新的公开撤销回执，不重写已撤销授权或收据。

撤销回执的有效窗口从此次生成时间开始，最长 600 秒；绑定原请求 ID、原账号、原主机及原设备指纹。手机保留原身份资料时，即使已取消等待或原配对请求已到期，仍可独立审查并接受这份新的匹配撤销回执。过期撤销回执须在主机再次明确确认生成，不自动重放；授权回执不能借此延长原配对请求期限。手机已删除原身份／请求记录时不能用回执恢复它，`inspect` 也不能恢复私钥。需要二维码时为 `revoke` 加 `--format svg` 并将 stdout 保存到新 SVG 文件，扫码后仍须在手机明确审查来源和摘要。

工具在 `.ssh/herdr-pocket-receipts` 保存仅属主可读的收据和锁，按请求 ID 定位确切条目。支持中断后用同一请求核查和收尾。待授权请求到期后不可新增授权，仍可按原 ID 撤销。已有授权文件必须是当前用户所有、不可被组或其他用户写入的普通单链接文件。工具拒绝符号／硬链接和混入陌生选项的相同公钥。修改期间避免另一个不使用本工具锁的进程同时编辑该文件；应用会检查写入前内容，POSIX rename 不提供与其他编辑器的跨进程比较交换。

本仓库的测试全部创建独立临时 home 和合成公钥。已保存资料的主机实际部署、非默认 AuthorizedKeysFile、Windows ACL 与手机实机扫码分别验收。

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
```
