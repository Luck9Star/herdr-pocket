#!/usr/bin/env bash
# M1-05 Tauri 迟到撤权探针：git-archive staging 复跑（不切 checkout、不在 checkout 内 npm ci）。
# 用法（在任意 herdr-pocket checkout 内执行均可，无需切到源提交）：
#   HERDR_D2_PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs \
#   bash docs/evidence/config-import-retained-tabs-20261120/tauri/replay/late-probe-replay.sh
# 前提：Node >=22.12.0（ad0d70e package.json engines）；Playwright（webkit）可解析且浏览器可启动；
#       npm 可用（仅在独立 staging 内安装依赖）。
# 行为：强制 HERDR_D2_BROWSER=webkit（外部 chromium 环境不得让输出目录漂移）；
#       成功前校验输出 report.json 存在且 passed=true、sourceSHA=ad0d70e，否则按失败退出。
# 产物：/tmp/herdr-late-probe-out-XXXXXX/report.json 与 shots/*.png（失败时目录保留供诊断）。
set -euo pipefail

EXPECT_SHA='ad0d70e384be5877b191840530cc179271ec210c'
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
PROBE="$SCRIPT_DIR/late-probe.mjs"

PW="${HERDR_D2_PLAYWRIGHT_MODULE:-}"
if [ -z "$PW" ]; then
  echo 'FAIL: 需要设置 HERDR_D2_PLAYWRIGHT_MODULE 指向 playwright/index.mjs' >&2
  exit 1
fi
command -v node >/dev/null 2>&1 || { echo 'FAIL: node not found' >&2; exit 1; }
command -v npm  >/dev/null 2>&1 || { echo 'FAIL: npm not found'  >&2; exit 1; }
node -e 'const [M,m]=process.versions.node.split(".").map(Number);if(!(M>22||(M===22&&m>=12)))process.exit(1)' \
  || { echo 'FAIL: 需要 Node >=22.12.0（ad0d70e package.json engines）' >&2; exit 1; }

# 1) 源提交须存在于本仓库对象库；用 git archive 在 staging 解出，不切换/不污染 checkout。
git -C "$ROOT" cat-file -e "$EXPECT_SHA^{commit}" || {
  echo "FAIL: 源提交 $EXPECT_SHA 不在本仓库对象库" >&2; exit 1; }

STAGE="$(mktemp -d /tmp/herdr-late-probe-XXXXXX)"
OUT="$(mktemp -d /tmp/herdr-late-probe-out-XXXXXX)"
cleanup() { rm -rf "$STAGE"; }
trap cleanup EXIT

mkdir -p "$STAGE/current"
git -C "$ROOT" archive "$EXPECT_SHA" validation/tauri validation/shared validation/vendor | tar -x -C "$STAGE/current"

# 2) 在 staging 内安装依赖并构建 dist；产物位于 current/validation/tauri/dist。
cd "$STAGE/current/validation/tauri"
npm ci --no-audit --no-fund
npm run build
test -d dist || { echo 'FAIL: dist 未生成' >&2; exit 1; }

# 3) 探针按其约定解析 ./current/validation/tauri/dist；复制到 staging 根运行。
#    强制 webkit：报告目录固定为 current-webkit-390x844，外部 HERDR_D2_BROWSER 不影响输出位置。
cp "$PROBE" "$STAGE/probe.mjs"
cd "$STAGE"
if HERDR_D2_PLAYWRIGHT_MODULE="$PW" HERDR_D2_BROWSER=webkit node probe.mjs current; then
  RC=0
else
  RC=$?
fi

# 4) report.json 与 shots 复制到独立 OUT，并校验通过条件后才宣告成功。
if [ -d "$STAGE/current-webkit-390x844" ]; then
  cp -R "$STAGE/current-webkit-390x844/." "$OUT/"
else
  echo "WARN: 未找到 current-webkit-390x844（probe rc=$RC）" >&2
fi
if [ "$RC" -eq 0 ]; then
  node -e '
    const fs = require("fs");
    const report = process.argv[1], expect = process.argv[2];
    if (!fs.existsSync(report)) { console.error("FAIL: 输出缺少 report.json: " + report); process.exit(1); }
    const r = JSON.parse(fs.readFileSync(report, "utf8"));
    if (r.passed !== true) { console.error("FAIL: report.passed != true"); process.exit(1); }
    if (r.sourceSHA !== expect) { console.error("FAIL: report.sourceSHA=" + r.sourceSHA + " != " + expect); process.exit(1); }
  ' "$OUT/report.json" "$EXPECT_SHA" || { echo "FAIL: 报告校验未通过（$OUT）" >&2; exit 1; }
  echo "DONE rc=0 out=$OUT source=$EXPECT_SHA report passed, sourceSHA verified"
fi
exit $RC
