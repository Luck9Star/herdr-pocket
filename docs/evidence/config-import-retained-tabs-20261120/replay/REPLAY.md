# Flutter M1-05 本机验收复跑

`replay_flutter_m105.py` 使用 Flutter 的正式设置入口和可选 S06 验收用例。两个服务端各用临时身份、独立的监听端口和 herdr 命名会话。脚本在独立 OpenSSH 日志中按认证公钥指纹和客户端端口核对同一条连接。临时私钥、原始服务端日志和原始输入数据在退出时清理，工件只保存固定检查项、输入字节数、Flutter 测试日志与截图。

需要 Flutter 3.47.9、Python 3 及仓库配对测试依赖、`ssh-keygen`、macOS 本机 `/usr/sbin/sshd`。传入 Flutter 采样工程和 herdr 0.9.5 路径，输出目录必须全新。先从待测提交的根目录生成 Flutter 采样工程，再运行脚本。

```sh
fixture_root="$(mktemp -d)"
fixture_repo="$(pwd -P)"
python3 validation/flutter/tool/ci.py prepare --destination "$fixture_root/app"
(cd "$fixture_root/app" && flutter pub get --enforce-lockfile)
python3 /path/to/replay_flutter_m105.py \
  --repo "$fixture_repo" \
  --project "$fixture_root/app" \
  --output "$fixture_root/stock" \
  --herdr /path/to/herdr-0.9.5
```

复跑 guarded 时须使用同一仓库 guard patch 哈希对应的 Linux x86_64 共享 fixture 二进制及 manifest。使用附带的 Dockerfile 生成本地一次性镜像，脚本不会拉取镜像或改动已部署的 SSH 实例。可选 `--cjk-font` 加载本地字体，只影响保存的 Widget 画面。

```sh
docker build --platform linux/amd64 -t codex-s06-import-fixture - < /path/to/Dockerfile.s06-m105
python3 /path/to/replay_flutter_m105.py \
  --repo "$fixture_repo" \
  --project "$fixture_root/app" \
  --output "$fixture_root/guarded" \
  --herdr /path/to/shared-fixture/herdr \
  --docker-image codex-s06-import-fixture \
  --guarded-manifest /path/to/shared-fixture/manifest.json
```

390×844 证据由同一 Flutter 代码的桌面 Widget 引擎渲染，使用内存适配器和合成终端帧。在采样工程内执行以下命令。指定的输出目录要先创建。

```sh
mkdir "$fixture_root/mobile"
HERDR_M105_MOBILE_EVIDENCE="$fixture_root/mobile" \
HERDR_S06_CJK_FONT="/path/to/cjk-font.ttc" \
flutter test --no-pub test/config_transfer_widget_test.dart --plain-name '390px settings import'
```

双对端测试走实际 SSH 和 herdr。设备 signer、目录、输入 journal 与系统文件选择桥使用注入的测试实现。此次验证范围为桌面 Flutter Widget 和回环网络。原生文件选择、真机、三网、系统钥匙串和系统输入法未验证。
