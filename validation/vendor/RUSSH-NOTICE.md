# russh 0.65.0 local-close candidate

This directory contains the complete 90-file official crates.io `russh 0.65.0` package, plus a narrowly scoped local modification in `src/client/mod.rs`. The original package declares `Apache-2.0`; its source copyright headers remain intact. The archive omitted a standalone license file, so the complete canonical Apache License 2.0 is supplied alongside it as `russh-0.65.0-LICENSE-APACHE`.

Official source archive: `https://static.crates.io/crates/russh/russh-0.65.0.crate`.
SHA-256: `3bb77a4b259312b2abbc541bca1c13cb4e9b61c560a7fd894068c3b92e0c9dc3`.
The archive records upstream repository `https://github.com/warp-tech/russh`, commit `183a22e8f8f490fa09b6eb7bd044ef99d8c4414f`, path `russh`.

Modification: after the client processes a local channel Close request, retire the matching client sender index. The original encrypted channel close removes its protocol-table entry; the later peer Close is then rejected by the established-channel check before the separate sender index can be removed. Retiring that local index lets the channel reader reach local EOF and prevents repeated observation pause/resume from retaining unused sender entries.

If the encrypted channel still has queued data, the candidate returns `Error::Disconnect` for that SSH instead of retiring only its sender index and leaving encrypted pending state. This is deliberately conservative: a queued or submitted write is not replayed, and the application preserves its unknown-result marker. Other independent SSH connections are unaffected. Two added in-memory unit tests describe the empty-queue and pending-queue branches; their execution is separate from application loopback evidence.

The pending-data guard applies when Close is dispatched. Upstream's driver can stop polling the ordinary outbound queue while a channel is window-blocked, so Close may remain queued before reaching that guard. The controlled observer therefore also bounds local-close processing to five seconds, cancels that entire owned SSH on failure, and waits for its real I/O to drop before completing. Zero-window application evidence verifies this timeout/abort path; it does not claim that the defensive dispatch guard ran.

This is a project validation candidate, not an upstream release or a change to SSH authentication, host-key verification, PTY, signals, encryption or input replay. A successful local retirement means the local observer/input epoch is closed and the Close request was processed. It does **not** prove that the peer received Close or that a remote process exited. No SIGTERM is sent.

`russh-0.65.0-local-close.patch` records the entire source modification. `russh-0.65.0-upstream-files.json` records every file hash from the verified archive. `verify-russh.py` reverses the exact patch in a temporary copy and compares every original file; `--archive PATH` independently verifies the official archive and its members, and `--metadata` verifies that all three consuming Cargo roots resolve exactly one copy of this candidate. The independent `validation/ssh` root retains upstream registry 0.65.0 for comparison.
