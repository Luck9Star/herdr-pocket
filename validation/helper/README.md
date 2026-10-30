# 一次性 helper 的 fixture 验证

这是 **fixture-only 安全语义实验**，不是可用于主机真实授权的 helper。CLI 不接受 home、账号、路径、公钥或请求文件；只在自行创建的 private 临时目录处理 `authorization.fixture`，使用没有对应私钥的合成公开测试字节。不会读取或写入任何真实 SSH 授权文件，没有 sudo、listener、SSH、网络或二维码生成器。

```sh
python3 -m unittest discover -s validation/helper -v
python3 validation/helper/fixture_helper.py --demo
python3 validation/helper/fixture_helper.py --demo --confirm-fixture 'AUTHORIZE FIXTURE'
```

默认演示不变更文件。显式确认后，演示一次追加和一次撤销再退出，临时目录销毁。撤销也是程序内部测试情景，不是用户设备授权操作。15 项测试覆盖单行 key/禁止 options 与控制字符、schema 与期限、响应绑定/重复标记、确认、幂等、保留既有同 key、不删除其他记录、伪造 receipt、原子 replace 失败、symlink/hardlink/权限、旧快照和长度上限。只在 POSIX 运行；Windows 主机 helper 未验证。

当前 wire-shape 检查不是成熟 SSH 库的公钥语义校验；合成 key 不能用于真实身份验证。临时 store 内存 receipt 不跨进程保存，不具备真实主机一次性消费、断电恢复、并发写入协调或持久撤销能力。响应匹配仅验证结构与绑定，不证明可信来源或 QR 防篡改。生产实现前必须选择 SSH 库、审查真实账号/home/UID、锁定与 crash recovery，并做明确授权的隔离主机集成测试。产品授权流程不构成本轮真实主机写入授权。

来源：Context7 于 2026-10-30 `library Python` 后查询 `/python/cpython`，核查 `tempfile`、`os.open` / O_NOFOLLOW / dir_fd、`os.replace` 与 fsync。[CPython tempfile 源码](https://github.com/python/cpython/blob/main/Lib/tempfile.py)、[原子写入示例](https://github.com/python/cpython/blob/main/Lib/importlib/_bootstrap_external.py)。这里采用标准库，不新增外部运行依赖。
