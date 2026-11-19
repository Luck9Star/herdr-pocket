# Linux Flutter 普通 SSH 加密私钥与换钥验收（R5）

2026-11-19，普通案 [run 44591418208](https://github.com/Luck9Star/herdr-pocket/actions/runs/44591418208) 与换钥案 [run 44591417302](https://github.com/Luck9Star/herdr-pocket/actions/runs/44591417302) 的官方工件使用源码 `0c94bdd35e368ce8f33733df729e673a0a6143ec`，在 Ubuntu 24.04、Xvfb 和 Flutter 3.47.9（`c197ca5`）上通过原生 Linux GTK 调试应用的普通 SSH 加密私钥路径；两案均为 `status=passed`、`checkpoint=complete`，`physicalImeVerified=false`。驱动是原生 Flutter `integration_test`，输入经 Flutter 测试接口提交，像素来自未缩放 X11 帧缓冲。两案核对 45 个生产 Dart 文件，候选/集成锁与测试/步骤摘要一致（`1440de01…`、`8177c0b6…`、`e121b094…`、`24d405dc…`）。

[普通案 ZIP 原件](flutter-linux-key-first-r5.zip)完整保留 96,731 字节，SHA256 `6966b745ee4dfe6426b54bab753381a13d6896fb5f772f880d606f90094eefa1`。[换钥案 ZIP 原件](flutter-linux-key-rotation-r5.zip)完整保留 165,753 字节，SHA256 `5c6a19e69ebfd8c0040c023a33da676fd938b9bbb5040ae4211b80425ab6eb94`。

## 认证与信任链

两案错误口令均本机拒绝，各 1 条连接、0 次认证尝试；密码/私钥来回切换时两个方向凭据清空、信任不变，各 1 条连接、0 次认证。指纹均先比对后确认，显示算法 `rsa-sha2-512`，认证方式 `publickey`。

| 普通案连接 | 主机密钥 | 认证尝试 | 认证成功 | PTY | shell | 入／出字节 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 首次探测 | A | 0 | 0 | 0 | 0 | 0／0 |
| 2 核对后会话 | A | 1 | 1 | 1 | 1 | 9／102 |

换钥案共 4 条连接，依次为 A 探测、B 拒绝传输、B 重新探测、B 接受会话；前三条认证/PTY/shell/输入输出全 0，末条 1 次认证成功、1 次 PTY 与 shell、9 字节输入、102 字节输出，`singleMarkerLineExact=true`。拒绝审查帧中旧/新指纹均匹配、旧信任保留、凭据锁定；重新探测后新指纹先比对再确认。

## 原图与 OCR

两案 `ordinary-terminal.png` 均为 1920 × 1080 未缩放 X11 帧缓冲（窗口 1280 × 720），官方 Tesseract 5.3.4 在终端区域识别出回显标记与合成词，`proofSequenceVisible=true`。换钥案另含 `rotation-rejected.png` 拒绝审查帧。断开与返回首页各有原图（`ordinary-disconnect.png`、`ordinary-home.png`）。所有 PNG 已逐字节核验结构完整、尺寸与 result.json 内嵌 SHA256 一致；归档保持原始字节，不重复展开。

## 断开与清理

两案均用户主动断开，服务端末条连接 `peer_eof` 且全部连接关闭，返回首页，凭据字段清空。清理四项通过：Flutter 进程退出、回环监听释放、夹具密码清空、夹具目录删除，另含临时密钥与口令清空。

## 历史 R4 失败边界

同批两个 R4 失败案使用旧源码 `65204b6d55fbb308a73af0b12a2f30a6cd345cf4`，错误码 `flutter_linux_application_ended_early`：

- [换钥失败案](flutter-linux-key-rotation-r4-failed.zip)（run 44589661090，`rotation-rejected` 停止，1 条连接）：仅证明 R4 未能完成换钥审查。
- [普通失败案](flutter-linux-key-first-r4-failed.zip)（run 44589659939，`connected` 停止，1 条连接）：仅证明 R4 未走到断开清理。

两者只界定 R4 失败边界，不作为通过证据。Tauri Linux 与 Windows 两壳的私钥路径仍待验证，见[普通 SSH 矩阵](../../63-design-parity-and-direct-ssh.md#普通-SSH-验收矩阵2026-11-18-汇总)。本归档结论限于加密私钥与独立回环，不覆盖物理键盘、系统中文 IME、真实跨网、部署安装。

## 校验原件

```sh
set -e
shasum -a 256 -c SHA256SUMS
for z in flutter-linux-key-first-r5.zip flutter-linux-key-rotation-r5.zip \
         flutter-linux-key-rotation-r4-failed.zip flutter-linux-key-first-r4-failed.zip; do
  unzip -t "$z" >/dev/null
done
```
