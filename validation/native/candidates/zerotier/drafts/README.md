# ZeroTier 候选补丁草稿归档

2026-11-08。此前暂存的 `0008-streams-in-progress.patch` 草稿（网络流与边界绑定）已完成缺陷修复（阶段 A 并发/生命周期修复 + IPv6 DAD 即时 PREFERRED 与 IPv4 对称 re-add），并通过全量回归验证（62 TU 编译 + 118 boundary 测试 + 8 tap-reconfig 原生无注入测试 + 15 gate 测试）。

该补丁现已正式转正为 `candidates/zerotier/patches/0008-streams-and-hp-boundary.patch` 并录入 `zerotier-candidate.json`。

当前 `drafts/` 目录下无未完成的活动草稿。

