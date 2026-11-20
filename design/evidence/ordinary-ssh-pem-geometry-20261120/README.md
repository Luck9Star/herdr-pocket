# 普通 SSH 私钥区域 Widget 几何核验

2026-11-20，产品基线 `72afe632b35aabc3ca00c697eb61150ef3c1b0b3`，冻结设计 `6fac813ee9e26e560e32a0c5c807757ff358324f`。范围是 Flutter Widget 测试，不是设备、模拟器、原生键盘或网络环境验收。无生产代码修改。

从主机目录正常点击普通 SSH，向临时回环夹具探测并确认主机密钥，再进入私钥认证；从列表滚动位置 0 测量。手机使用 iOS 平台主题、390×844 逻辑像素、像素比 1、模拟安全区上 47 / 下 34；桌面使用 Linux 平台主题、980×780 内容窗口、像素比 1。图片使用合成多行文本与本机临时夹具目标，未包含私钥或口令。测试桥加载本机 Hiragino Sans GB、MaterialIcons 和项目 ProbeNerd 用于可读截图，关闭调试横幅，未修改产品字体。

| 区域 | 390 手机实测 x,y,宽,高 | 手机冻结板 | 980 桌面实测及冻结板 |
| --- | --- | --- | --- |
| 编辑框 / 失焦摘要 | 24,352,342,84 | 24,351,342,84 | 264,304,560,84 |
| 粘贴 | 24,446,342,48 | 24,445,342,48 | 264,398,560,48 |
| 口令 | 24,528,342,48 | 24,527,342,48 | 264,480,560,48 |
| 连接 | 24,590,342,48 | 24,589,342,48 | 264,542,560,48 |

空编辑、填入合成内容并聚焦、失焦摘要三态均核对，手机所有 y 比画板大 1pt，桌面完全一致，均在 2pt 容差内。每个控件测中心及四个轴向 90% 位置的 Flutter 命中路径；这是采样，不代表穷举完整边界。连接在示意内容不完整时确实禁用，命中路径采样不代表按钮可执行。点击摘要重新编辑后用等值布尔检查原内容，再单击口令框，确认焦点转移、编辑框移除及摘要显示。

手机附加模拟键盘 bottom inset 291、滚动使口令可见：口令为 24,352,342,48，采样可命中。截图中不存在真实系统键盘；此模拟不证明原生输入法行为。设计的聚焦页为键盘隐藏的画板，故 inset 打开后的滚动位置不与该画板坐标比较。

## 修复前后对照

在同一台机器、同一 Flutter 3.47.9 Widget 测试环境中，对照 `65319ae6c750ce5b60c6cd19ef37557c95f4dd28` 与 `72afe632b35aabc3ca00c697eb61150ef3c1b0b3` 的生产页面，使用相同 390×844、47/34 安全区、键盘隐藏与列表位置 0。两次均从主机目录进入并经临时回环夹具探测、确认，输入非 PEM 的合成示例词，再实际点击口令框。系统端口由各次夹具自动分配，因此目标端口不同；不存在真实凭据。

| 结果 | 修复前 | 修复后 |
| --- | --- | --- |
| 原图 | [失焦后正文仍显示](before-blur.png) | [失焦后显示摘要](after-blur.png) |
| 凭据区域 x,y,宽,高 | 24,352,342,84 | 24,352,342,84 |
| 口令框获得焦点 | 是 | 是 |
| 编辑控件中示例内容可读 | 是 | 否，控件已移除 |
| 辅助功能树中示例内容可读 | 是 | 否 |
| 重编辑摘要存在 | 否 | 是 |

这些是同一测试环境下的 Widget 渲染，不是真机画面。辅助功能检查遍历本测试视图的语义树；未测试真实读屏器。复跑中的两项对照使用[独立测试桥](before-after-test.dart)，不会改动工作树中的生产页面。

## 复跑

在仓库根目录运行以下命令。请先将 Flutter 3.47.9 的 `bin` 放入 `PATH`；命令检查版本、从实际可执行文件推导 SDK，并使用独立临时目录。需要 Python、网络以安装 `paramiko==4.0.0`；字体不存在时可省略对应参数，截图可能缺字。

```sh
set -eu
repo_dir=$(pwd -P)
flutter_bin=$(command -v flutter)
flutter --version --machine | python3 -c 'import json,sys; v=json.load(sys.stdin)["frameworkVersion"]; assert v == "3.47.9", "需要 Flutter 3.47.9，当前 " + v'
flutter_root=$(python3 -c 'import os,sys; print(os.path.dirname(os.path.dirname(os.path.realpath(sys.argv[1]))))' "$flutter_bin")
run_dir=$(mktemp -d -t herdr-pem-geometry.XXXXXX)
python3 validation/flutter/tool/ci.py prepare --destination "$run_dir/probe"
python3 -m venv "$run_dir/venv"
"$run_dir/venv/bin/pip" install 'paramiko==4.0.0'
mkdir -p "$run_dir/images"
export HERDR_FIXTURE_PYTHON="$run_dir/venv/bin/python"
export HERDR_PEM_PIXEL_DIR="$run_dir/images"
export HERDR_PEM_ICON_FONT_PATH="$flutter_root/bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf"
if [ -f '/System/Library/Fonts/Hiragino Sans GB.ttc' ]; then
  export HERDR_PEM_FONT_PATH='/System/Library/Fonts/Hiragino Sans GB.ttc'
fi
cd "$run_dir/probe"
flutter pub get
flutter test --no-pub test/direct_ssh_pem_geometry_test.dart --reporter expanded
cp "$repo_dir/design/evidence/ordinary-ssh-pem-geometry-20261120/before-after-test.dart" test/before-after-test.dart
git -C "$repo_dir" show 65319ae6c750ce5b60c6cd19ef37557c95f4dd28:validation/flutter/lib/direct_ssh_page.dart > lib/direct_ssh_page.dart
HERDR_PEM_BASELINE=before flutter test --no-pub test/before-after-test.dart --reporter expanded
git -C "$repo_dir" show 72afe632b35aabc3ca00c697eb61150ef3c1b0b3:validation/flutter/lib/direct_ssh_page.dart > lib/direct_ssh_page.dart
HERDR_PEM_BASELINE=after flutter test --no-pub test/before-after-test.dart --reporter expanded
printf '证据目录：%s\n' "$run_dir/images"
```

图片每次包含不同临时端口，哈希不要求复跑一致。本次原图 SHA-256：

```text
3cdef106009ebb39a739a0ec7814d6148a3504a988084c8fc80133e1272593a6  before-blur.png
edafb16a30b146e4ad9400fe99c50bb30a330c325edb2eb5bfb6405e2b95e713  after-blur.png
132a2762ed5b54517d1203acbe011a119c8a9e0b0c0e0cf8bbbb81878687ae85  desktop-collapsed.png
6702340a9e6a6c1a11405a9f25a7852e478dfa168860ddc568fca93ea25d7d44  desktop-editor-empty.png
f063fc720c226c6329d936e2427fdf6474798a4489f79baa3acbd5f8969a3852  desktop-editor-focused.png
590a4273ed3e69a8cd78946ae87e5414162a6d460e672d4661adfcf7bc7e7078  mobile-collapsed.png
65de098f1064f2d6aa087d126a2b5ece7b97fd4784339da1ddb0e3f7f8acb47a  mobile-editor-empty.png
901b50c68564302af82e3f1949d72ccc0610e2f8a1b5250675f0d8d3352649c6  mobile-editor-focused.png
2e7699dff044e4a6b23e6defaf82d304ceb94536c9b121774d3c408bab82c4bd  mobile-keyboard-open-scrolled.png
```
