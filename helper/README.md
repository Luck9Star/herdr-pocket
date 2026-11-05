# 手机配对的主机辅助命令

主机用户运行一次命令来审查设备公钥、明确添加授权或撤销本次新增的公钥。适用范围为非 root 的 POSIX 登录账号和 OpenSSH 默认 `~/.ssh/authorized_keys`。需要 Python 3.10+。在 `helper/` 目录创建虚拟环境并安装 `requirements.txt` 的固定依赖。

1. 手机填写目标账号、命名会话和从可信渠道核实的主机 Ed25519 公钥，生成公开请求。通过已有可信渠道把请求 JSON 交给主机用户。
2. 使用 `python -m herdr_pocket_helper preview --host-public-key /etc/ssh/ssh_host_ed25519_key.pub --request request.json` 查看账号、主机指纹、设备指纹和到期时间。预览不会创建授权文件。
3. 独立核对两端显示的账号及指纹，再用同样的参数运行 `authorize`。在控制终端输入显示的完整确认短语。stdout 输出绑定当前请求的 JSON，可复制回手机。传入 `--format svg` 并重定向到新 SVG 文件可生成公开响应二维码。手机仍须另行审查并主动进行 SSH 认证。
4. 撤销时运行 `python -m herdr_pocket_helper revoke --host-public-key /etc/ssh/ssh_host_ed25519_key.pub --request-id <请求ID>` 并在控制终端确认。相同公钥原已存在、授权项被外部编辑或重复时会拒绝自动删除。撤销限制后续认证，当前已建立连接由用户单独处理。

工具在 `.ssh/herdr-pocket-receipts` 保存仅属主可读的收据和锁，按请求 ID 定位确切条目。支持中断后用同一请求核查和收尾。待授权请求到期后不可新增授权，仍可按原 ID 撤销。已有授权文件必须是当前用户所有、不可被组或其他用户写入的普通单链接文件。工具拒绝符号／硬链接和混入陌生选项的相同公钥。修改期间避免另一个不使用本工具锁的进程同时编辑该文件；应用会检查写入前内容，POSIX rename 不提供与其他编辑器的跨进程比较交换。

本仓库的测试全部创建独立临时 home 和合成公钥。已保存资料的主机实际部署、非默认 AuthorizedKeysFile、Windows ACL 与手机实机扫码分别验收。

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
```
