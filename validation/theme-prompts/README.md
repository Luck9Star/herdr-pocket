# 真实主题引擎的字体诊断样例

2026-11-08，在本机 Mac arm64 上生成了两条提示符。共享输入位于
[`theme-prompt-samples-v1.json`](../shared/theme-prompt-samples-v1.json)。它们是固定合成配置下
Powerlevel10k 和 Oh My Posh 引擎产生的实际 ANSI 字节，不是手写的提示符近似图。
这份输入证明引擎来源与可重现性；应用测试和手机实际字形验收应分别记录。

## 固定输入与来源

| 引擎 | 固定来源 | 本轮执行方式 |
| --- | --- | --- |
| Powerlevel10k 1.20.0 | [commit 35833ea](https://github.com/romkatv/powerlevel10k/tree/35833ea15f14b71dbcebc7e54c104d8d56ca5268)；官方 tag archive | 系统 Zsh 5.9，`-dfi` 加载本目录合成配置，调用主题注册的 precmd，然后 `print -rnP -- "$PROMPT"` 展开真实引擎生成的提示符 |
| Oh My Posh 31.9.1 | [commit e6c9eb7](https://github.com/JanDeDobbeleer/oh-my-posh/tree/e6c9eb7796d1c903c7944c4e87a4ea2c3f6b4182)；现有 Homebrew 31.9.1 二进制 | `print primary --config posh.omp.json --shell uni --escape=false --terminal-width 40 --status 0` |

[`sources.json`](sources.json) 固定官方 archive SHA256、commit 和实际执行文件的 SHA256。
P10k 的带注释 tag `ff0311157d6b24fea21aa70699783f362b0f554f` 指向表中 commit；通过 GitHub tag API 读回。
OMP 的 tag 直接指向表中 commit。已下载 OMP archive 并核对其 SHA256 与本机 Homebrew
formula 一致；本轮复用了现装二进制，没有从该源码重新构建，因此没有声称可重现二进制构建。

本轮按 Context7 `library` → `docs` 查询了两引擎的官方资料，随后以固定源码和本机 CLI `--help`
确认实际行为。主要固定参考为 P10k 的
[`internal/p10k.zsh`](https://github.com/romkatv/powerlevel10k/blob/35833ea15f14b71dbcebc7e54c104d8d56ca5268/internal/p10k.zsh)
和 OMP 的
[`configuration/general.mdx`](https://github.com/JanDeDobbeleer/oh-my-posh/blob/e6c9eb7796d1c903c7944c4e87a4ea2c3f6b4182/website/docs/configuration/general.mdx)。

## 隔离与复跑

生成器不下载依赖。先将固定 P10k archive 放在独立缓存位置；例如本轮使用的
`/private/tmp/herdr-powerlevel10k-v1.20.0.tar.gz`。下载链接和摘要见 `sources.json`。
需要网络时由调用者明确执行下载，不在应用内触发。

```sh
python3 validation/theme-prompts/generate.py \
  --p10k-archive /private/tmp/herdr-powerlevel10k-v1.20.0.tar.gz

python3 validation/theme-prompts/generate.py \
  --p10k-archive /private/tmp/herdr-powerlevel10k-v1.20.0.tar.gz \
  --check
```

每次调用都在两个彼此独立的临时目录内运行两引擎，并要求所有输出字节相等。
`--check` 还要求与共享 fixture 文件完全相等。执行前严格验证 archive、OMP 和 Zsh 的 SHA256；
其他平台或其他编译的同版本二进制会被拒绝，需要另立捕获证据，不能直接改锁来宣称本轮通过。

子进程环境由空映射建立，HOME、ZDOTDIR、XDG 配置与缓存都指向临时目录；工作目录的最后一段
固定为 `中文`。没有读用户 shell 配置或真实项目、凭据、网络身份，也未安装系统工具。
`zsh -dfi` 关闭用户和后续全局启动文件；Zsh 固有的系统 `/etc/zshenv` 加载机制仍存在，
不能将它称为完全不读系统文件。P10k 配置向导、instant prompt 和 gitstatus 均关闭；OMP 仅使用
本地 path/text segments。没有初始化 Git 仓库、异步状态或远端连接。

## 字节、坐标与覆盖范围

捕获范围是每个引擎本次写到 stdout 的全部字节。没有截掉前后缀，没有拼 marker，没有改写
颜色、图标、空白或换行，也没有删除未知控制序列。捕获后只做严格 UTF-8 解码和 JSON 序列化。
如有 stderr、执行失败、超过 4096 字节、未知控制字符、越界或两次结果不同，生成器失败。

白名单是可打印字符、`ESC [ [0-9;]* m` 的 SGR 和完整 CRLF。独立 CR/LF、OSC、CSI 光标移动和
其他 C0/C1 控制均拒绝。这两条实际样例没有 CRLF；40 列 × 3 行是固定诊断画布大小。

| 样例 | 去 SGR 后的实际文字（含空格） | 最终光标（列，行，均 0 基） |
| --- | --- | --- |
| Powerlevel10k | `  中文  ❯  ` | `(14, 0)` |
| Oh My Posh | `  中文  ❯  ` | `(15, 0)` |

计算使用中文每字 2 列，PUA 图标与分隔符、`❯` 和空格各 1 列；SGR 0 列。
包含 U+F07B Nerd Font 图标、U+E0B0 Powerline 分隔符、中文宽字符、颜色复位与连续 segment 背景。
此处只有目录和提示符字符段，没有验证 Git 分支/dirty 状态、多行异步 prompt 重绘、emoji 或
不同用户真实主题配置。保留这些未验范围，以两条应用终端内核的独立 cell/游标核对和手机实机结果补足。

本轮生成与 `--check` 均通过，每次内部两次独立 capture 均完全相等；共享 JSON 的 SHA256 为
`1b86567e91ad08dc8c4d74a593b94da9946dd3515f610c0ca9a11976b92f3e6d`。
