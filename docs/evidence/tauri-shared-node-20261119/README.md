# Tauri 同一配置下的双主机工作台

2026-11-19。Tauri 生产前端在 Chromium 148.0.7778.96 和 WebKit 26.4 中完成八组对照。两台合成主机共用一份 EasyTier 配置及其模拟来宾节点。浏览器操作实际页面，IPC 测试替身提供连接编号、终端帧和节点状态。M2-02 仍待真实共享网络验收。[路线图](../../04-roadmap.md) · [网络配置](../../18-mobile-network-profiles.md)

## 观察到的行为

| 操作 | 窄屏 390 × 851 | 宽屏 1440 × 1200 |
| --- | --- | --- |
| 关闭活动 A 标签 | 只保留未选中的 B 标签。选回 B 后，旧画面保持暂停。点击「恢复观察」后，原模拟连接才收到新的全量帧。 | 原先已可见的 B 保持只读和可见。B 在原模拟连接与原观察代次接收后续增量帧，无新增恢复或建立连接请求。 |
| 向 B 输入 | 两种布局都先证明输入关闭。显式启用草稿并在确认框核对目的主机、窗格和终端后，向原 B 的模拟连接交付一次 9 字节草稿。 | 同左。 |
| 释放与停节点 | 两种布局都只依次关闭 A 和 B 的模拟连接。关闭最后一个标签后，网络页仍显示本机引擎已启动。用户显式确认后才向原配置和节点绑定发出一次停止请求。 | 同左。 |

B 先连接，在报告中为连接 1。A 为连接 2。报告中的认证、连接和回显记录来自模拟 IPC。浏览器没有拨号 SSH、启动真实 EasyTier 节点或连接物理网络，也没有覆盖设备安装、手机系统输入法和跨 provider 组合。

## 八份原始报告

| 生产源码 | Chromium 窄屏 | Chromium 宽屏 | WebKit 窄屏 | WebKit 宽屏 |
| --- | --- | --- | --- | --- |
| 主线 `0c3ef4817234f8519c4d9f8559cd0bd188ee89d5` | [报告](main/chromium-narrow/report.json) | [报告](main/chromium-wide/report.json) | [报告](main/webkit-narrow/report.json) | [报告](main/webkit-wide/report.json) |
| PR #13 `a1fe2517f56e15b7d169b34163d250e4759aee81` | [报告](pr13/chromium-narrow/report.json) | [报告](pr13/chromium-wide/report.json) | [报告](pr13/webkit-narrow/report.json) | [报告](pr13/webkit-wide/report.json) |

## 代表性原图

这四张 Chromium 原图来自同一 PR #13 源码。第二列先在关 A 后取图，第三列再在 B 出现新帧后取图。两张新帧图都早于启用草稿输入。

| 布局 | 关闭 A 后 | B 出现新帧后 |
| --- | --- | --- |
| 窄屏 | [B 标签保留，未选中](pr13/chromium-narrow/after-closing-A.png) | [手动选回并恢复后的全量帧](pr13/chromium-narrow/B-new-frame.png) |
| 宽屏 | [B 保持可见和只读](pr13/chromium-wide/after-closing-A.png) | [同一次观察的新 `fixture-B-after-close-delta` 行](pr13/chromium-wide/B-new-frame.png) |

在本目录运行 `shasum -a 256 -c SHA256SUMS` 可核对归档文件，原始八份报告的摘要也保存在汇总中。[汇总 JSON](summary.json) · [校验和](SHA256SUMS)

## 重跑

从仓库根目录执行。需要两个固定提交、Node.js 22.12 或更新版本和 npm。原测试使用 Node.js 24.22.2。构建命令依据各提交自己的锁文件安装依赖，所有输出写入临时目录。

```sh
repo="$(pwd)"
evidence="$repo/docs/evidence/tauri-shared-node-20261119"
scratch="$(mktemp -d)"

for entry in \
  main:0c3ef4817234f8519c4d9f8559cd0bd188ee89d5 \
  pr13:a1fe2517f56e15b7d169b34163d250e4759aee81
do
  variant="${entry%%:*}"
  sha="${entry#*:}"
  mkdir "$scratch/$variant"
  git archive "$sha" validation/tauri validation/shared validation/vendor |
    tar -xf - -C "$scratch/$variant"
  printf '%s\n' "$sha" > "$scratch/$variant/SOURCE_COMMIT"
  (cd "$scratch/$variant/validation/tauri" && npm ci && npm run build) || exit 1
done

mkdir "$scratch/pw"
npm --prefix "$scratch/pw" install --no-save playwright-core@1.60.0
"$scratch/pw/node_modules/.bin/playwright-core" install chromium webkit
export HERDR_M2_PLAYWRIGHT_MODULE="$scratch/pw/node_modules/playwright-core/index.mjs"

for variant in main pr13; do
  for engine in chromium webkit; do
    for layout in narrow wide; do
      node "$evidence/probe.mjs" "$scratch" "$variant" "$engine" "$layout" || exit 1
    done
  done
done
```

每案应以 `checked: true` 结束。宽屏的 `m2VisibleAfterClose` 为 `true`，窄屏为 `false`。运行时的模拟标签标识和截图时钟会变化，复跑结果按断言核对。若已有受控的浏览器安装，可在单次调用中用 `HERDR_M2_BROWSER_EXECUTABLE` 指定它的可执行文件，并以生成报告的版本字段为准。

原始探针 SHA256 为 `d0ea03c06c8300576974d1767693f334b7738e12f44d124270ad8185711661ce`。归档的可复跑版本将工作目录、Playwright 模块和浏览器位置改为参数，并核对输入的固定源码 SHA。交互顺序、模拟 IPC 及断言沿用原探针。[可复跑脚本](probe.mjs)
