# M1b 同目标持续观察实测

源码 `73ce2f8794a65c82975cf014d257ca339a283bdc`；[Actions run 41060251076](https://github.com/Luck9Star/herdr-pocket/actions/runs/41060251076) / job124077898796 成功。

同一Ubuntu24.04临时OpenSSH/herdr目标上，Rust9项、Dart9项，**18/18通过**。新持续观察3项每端分别为3帧2delta、1帧0delta、显式两次连接4帧2delta。所有用例输入计数0；cleanup成功。详见[脱敏manifest](probe/manifest.json)。

下载后已核验外层与probe内层SHA256SUMS；报告只保留字段白名单，没有fixture密钥、真实配置或远端原文。README为下载后追加，不属于原artifact校验条目。实际CLI调用GUI共享adapter，不是GUI点击、手机后台、IME、三网或系统密钥存储证明。`bufferHighWaterBytes`仅指解码单帧峰值，不能比较整进程内存或性能。

`cross-session` 的外层testId是harness场景，内层CLI `case=missing-session` 复用名称绑定拒绝入口；两真实session均存在且有同名pane的先决条件另记在 `crossSessionFixture`，不能把本项看成不存在主机／socket测试。
