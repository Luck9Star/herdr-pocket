# 验证分支归档

## 2026-11-20 分支整理

整理前盘点了 234 个本地分支、90 个 GitHub 分支和 29 个工作树。保留 `main`、正在使用的工作树、在审分支及仍有独有工作需要继续的分支，包括 [草稿 PR #59](https://github.com/Luck9Star/herdr-pocket/pull/59)。以整理前的 `main` 提交 `b10d8acc` 和各引用原头部为核对依据。

按整理前的原分支统计，本地移除 156 个、保留 78 个，GitHub 移除 79 个、保留 11 个。GitHub 分支一次原子删除后，通过 Git 和 GitHub API 分别复核数量。本地删除前再次核对原提交和工作树占用。

[79 个 GitHub 分支的恢复映射](evidence/branch-archive-20261120/remote-recovery.tsv)记录原分支名、完整提交、根目录树和供 GitHub 拉取的引用。映射使用 12 个公开恢复引用，含 `main`、此前的归档标签和本轮新建的 8 个附注标签。已经从 GitHub 将这些引用取到独立空仓库，以每行所列引用验证旧提交可达、根目录树相同，并运行 `git fsck --full`。

原本的本地、GitHub 引用已分别创建完整的 Git bundle。两份归档均校验 SHA-256、通过 `git bundle verify`，并各自在空仓库恢复，核对全部引用与对象并执行 `git fsck --full`。现有发布标签保留。Git bundle 和归档标签保存 Git 历史，Actions 工件仍按各自的保留期到期。

### 从 GitHub 恢复

从当前仓库根目录运行以下命令。把 `branch` 换成映射表中的任一原分支名。脚本拉取该行的 `fetch_ref`，并在独立的临时目录恢复该行的 `commit` 和 `tree`。`refs/heads/main` 指向持续更新的主线，所以恢复时仍以记录的旧提交为准。

```sh
(
  set -eu
  branch='codex/acceptance-flutter-dual-overlay/ordinary-identity-r3'
  index='docs/evidence/branch-archive-20261120/remote-recovery.tsv'
  row=$(awk -F '\t' -v branch="$branch" '
    NR > 1 && $1 == branch { print $2, $3, $4; found = 1; exit }
    END { if (!found) exit 1 }
  ' "$index")
  read -r commit tree fetch_ref <<EOF
$row
EOF
  case "$fetch_ref" in
    refs/heads/main|refs/tags/archive/*) ;;
    *) echo '恢复引用不在映射范围内' >&2; exit 1 ;;
  esac

  recovery=$(mktemp -d "${TMPDIR:-/tmp}/herdr-pocket-github.XXXXXX")
  git -C "$recovery" init --quiet
  git -C "$recovery" fetch --no-tags https://github.com/Luck9Star/herdr-pocket.git "$fetch_ref"
  git -C "$recovery" merge-base --is-ancestor "$commit" 'FETCH_HEAD^{commit}'
  test "$(git -C "$recovery" rev-parse --verify "$commit^{commit}")" = "$commit"
  test "$(git -C "$recovery" rev-parse --verify "$commit^{tree}")" = "$tree"
  git -C "$recovery" switch -c "$branch" "$commit"
  git -C "$recovery" fsck --full --no-dangling
  printf '恢复目录 %s\n' "$recovery"
)
```

### 从本机 Git 归档恢复

本机专用归档位于仓库共用 Git 目录下的 `branch-archives/20261120-docs-consolidation-_ytf9mw6/`。其中 `local-before.bundle` 和 `remote-before.bundle` 分别保存本地和 GitHub 的整理前引用，`SHA256SUMS` 提供两份归档的摘要。`disposition.tsv` 记录完整盘点和处置，`allowlist.tsv` 记录允许清理的原引用。仅在本地存在的源码与分支清单保存在本机归档中。

在持有这份归档的工作区运行以下命令，把 `branch` 换成要恢复的本地分支。示例从本地 bundle 抽取一条引用，核对旧提交和根目录树后在新目录检出。

```sh
(
  set -eu
  branch='main'
  common_dir=$(git rev-parse --path-format=absolute --git-common-dir)
  archive="$common_dir/branch-archives/20261120-docs-consolidation-_ytf9mw6"
  bundle="$archive/local-before.bundle"
  (cd "$archive" && shasum -a 256 -c SHA256SUMS)
  row=$(awk -F '\t' -v branch="$branch" '
    NR > 1 && $1 == "local" && $2 == branch { print $3, $4; found = 1; exit }
    END { if (!found) exit 1 }
  ' "$archive/disposition.tsv")
  read -r commit tree <<EOF
$row
EOF

  recovery=$(mktemp -d "${TMPDIR:-/tmp}/herdr-pocket-local.XXXXXX")
  git -C "$recovery" init --quiet
  git -C "$recovery" bundle verify --quiet "$bundle"
  git -C "$recovery" fetch --no-tags "$bundle" "refs/heads/$branch"
  test "$(git -C "$recovery" rev-parse --verify 'FETCH_HEAD^{commit}')" = "$commit"
  test "$(git -C "$recovery" rev-parse --verify "$commit^{tree}")" = "$tree"
  git -C "$recovery" switch -c "$branch" "$commit"
  git -C "$recovery" fsck --full --no-dangling
  printf '恢复目录 %s\n' "$recovery"
)
```

## 2026-11-18 首批验收分支归档

2026-11-18 归档了九个 Android、macOS 与普通 SSH 验证分支的源码快照。每个 GitHub 附注标签名均为 `archive/20261118/<完整旧分支名>`。已从 GitHub 向全新仓库仅取这九个标签，逐一核对标签指向的提交、根目录树和原分支一致，`git fsck --full` 通过。历史报告保留实际使用的源码、工件和结果。标签可恢复源码，GitHub Actions 工件仍按各自的保留期到期。

| 原分支 | 原提交 | 主线覆盖与归档用途 |
| --- | --- | --- |
| `codex/acceptance-android-dual-native/m2o-netmon` | [`45ea7dc`](https://github.com/Luck9Star/herdr-pocket/commit/45ea7dc6f9b99b9bc2fba0f2e53f6e31c7a0ccbf) | Android 接口枚举和测试隔离已由原生修复 `a9be92d` 吸收，保留早期构建和隔离实验供回看。 |
| `codex/acceptance-android-ts-node-plain/logdir-fixed-r2` | [`191d85f`](https://github.com/Luck9Star/herdr-pocket/commit/191d85fdcf64e2ff65ff57d8eae6fba9e0306607) | 本轮提取 normal / QA 两变体在 Android 模拟器上真实启动的严格门禁，要求两者均有完整证据。 |
| `codex/acceptance-android-ts-node-plain/round2-fd2` | [`1ef1cac`](https://github.com/Luck9Star/herdr-pocket/commit/1ef1caca77ada51855ed4eeeeba70de6de507e8e) | Go 启动修复已在主线。进程私有 fd2 采集及未完成的对照实验留作历史诊断。 |
| `codex/acceptance-android-ts-node/round2-earlylog-c199b08` | [`2566e82`](https://github.com/Luck9Star/herdr-pocket/commit/2566e8248802740d7d9dd0f7fb758232e507a67c) | 与 `c199b08` 文件树相同，保留以旧原生库重跑早期日志的触发点。 |
| `codex/acceptance/macos-secure-baseline` | [`93ec6e2`](https://github.com/Luck9Star/herdr-pocket/commit/93ec6e2074f924e4a351ad6892917ca1fe413538) | XCUITest 的等价补丁已入主线。旧表单对照源码与原始运行仍可追溯。 |
| `codex/acceptance/tauri-android-dual-overlay-device-r2-foreground-diagnostic` | [`9093dcb`](https://github.com/Luck9Star/herdr-pocket/commit/9093dcb0f117a6337661d4a44af952e8b5186190) | 主线 `8b8b4b9` 已有失败时采样和脱敏。一次性单向前台诊断留作历史。 |
| `codex/android-baseline-20261105` | [`b086299`](https://github.com/Luck9Star/herdr-pocket/commit/b08629980217b483784dde13b3949fa43fd399fc) | 保留两份旧只读看板 APK 的构建来源。主线工作流已有 Android 专用矩阵，旧矩阵缩减补丁留档。 |
| `codex/android-dual-client-acceptance` | [`98fe097`](https://github.com/Luck9Star/herdr-pocket/commit/98fe097aacca32d02a9d704d7b6e211c9127c650) | SSH 拒绝握手时报告实际指纹已由 `8657bc2` 纳入主线。本轮补齐独立 Flutter 双网 APK 的原生制品固定与来源校验，保留该分支的早期诊断。 |
| `codex/ts-easytier-concurrency` | [`c199b08`](https://github.com/Luck9Star/herdr-pocket/commit/c199b08a225cd81d05edf634b2fdfd4330109944) | Go 启动修复已在主线。固定格式的早期 logcat 采集保留用于历史复查。 |

本轮在独立 Flutter 双网 APK 构建和 Android 真实启动验收中，将 normal / QA 的原生输入由 `93ca6cd` 更新为 `547106e`，与 [Android 双网设备验收](67-android-dual-network-startup.md) 使用的源码对齐。构建和启动验收均检查下载摘要、原生来源和包内容。原生工件来自 [构建 43939326685](https://github.com/Luck9Star/herdr-pocket/actions/runs/43939326685)。

两项 CI 均使用源码 `0ad9734` 并通过。

- Android API 35 模拟器上的 normal 和 QA 变体均从 `needs-login` 到 `stopped`。清理通过，SSH 认证、新增授权和注册均为零。[真实启动验收 44290964257](https://github.com/Luck9Star/herdr-pocket/actions/runs/44290964257)
- Flutter 独立构建产出 normal 和 private-ca-qa 两份 x86_64 debug APK。本次验收范围为打包及清单校验，Flutter UI 设备测试另有独立记录。[Flutter APK 验收 44290964970](https://github.com/Luck9Star/herdr-pocket/actions/runs/44290964970)

### 恢复一个历史分支

在有 GitHub 仓库访问权限的终端运行以下命令，将 `b086299` 恢复到新的本地分支。

```sh
git init herdr-pocket-baseline-replay
cd herdr-pocket-baseline-replay
tag='archive/20261118/codex/android-baseline-20261105'
git fetch --no-tags https://github.com/Luck9Star/herdr-pocket.git "refs/tags/${tag}:refs/tags/${tag}"
git switch -c codex/replay-android-baseline-20261105 "${tag}^{commit}"
git rev-parse HEAD HEAD^{tree}
git fsck --full
```

预期提交为 `b08629980217b483784dde13b3949fa43fd399fc`，树为 `aaf7f06f2a4ebb2e251a7096e1f9ad5c4ac45d15`。
