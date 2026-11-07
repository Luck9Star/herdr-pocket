# herdr 0.9.5 pocket input candidate

This source patch is an experimental CI-only candidate against herdr release commit `2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01`. It is not an upstream release, does not modify an installed server, and is not a production deployment. Ordinary 0.9.5 has no `pocket.input.capabilities`; clients must remain read-only unless capability discovery succeeds over the same authenticated connection.

The capability is `pocket.input.capabilities`, version 1, protocol 22, `atomic_terminal_guard=true`, `raw_bytes=true`, `max_input_bytes=4096`. `pocket.input.send` takes the current public `pane_id`, `expected_terminal_id`, and canonical padded `bytes_base64` in one JSON request with a fresh lowercase 32-hex RPC id. The app event handler compares the current pane-to-terminal binding and enqueues exactly one 1–4096-byte payload without attach, resize, takeover, shell or retries. An accepted reply echoes the request id, pane, terminal and byte count; it means **accepted into the input queue**, not PTY delivery or command execution. `pocket_input_rejected` is the only matching-id definitive pre-enqueue rejection; any other response or transport loss has an unknown outcome. Request IDs correlate replies and do not imply deduplication.

Apply only in a disposable checkout of that exact commit and build/test the patched binary as an explicitly labelled candidate. Review the diff and negative cases before running any fixture. Never apply it to an installed or running host. A source patch, its compilation and isolated tests do not establish upstream adoption, mobile runtime or production safety.

```sh
git -C "$HERDR_TEMP_CHECKOUT" rev-parse HEAD
git -C "$HERDR_TEMP_CHECKOUT" apply --check "$POCKET_REPO/validation/herdr-input-extension/herdr-0.9.5-pocket-input.patch"
```

The Linux fixture build verifies the fixed Rust 1.96.0 environment and the upstream-required Zig 0.16.0 compiler before compiling the vendored Ghostty VT library. The runner checks the Linux x86_64 archive against the [official digest](https://ziglang.org/download/index.json). No local SDK is installed by this workflow.

The candidate server uses Cargo's dev profile with **debug assertions disabled for the `herdr` binary only**; this is not an upstream release binary. In the pinned upstream source, `src/config/io.rs` chooses `herdr-dev` when debug assertions are enabled and `herdr` otherwise, while `src/session.rs` places named-session sockets beneath that config directory. The isolated harness expects `XDG_CONFIG_HOME/herdr/sessions/<session>/herdr.sock`, the same directory convention as the stock release. A prior candidate built with ordinary debug assertions instead listened under `herdr-dev`, so the harness timed out while polling the other path.

Before publishing the candidate artifact, the workflow starts that exact binary with fresh temporary XDG directories, verifies a `session.snapshot` with version 0.9.5 and protocol 22 at the expected socket, and checks the read-only extension capability response. It stops the owned process group and removes the temporary data; it sends no terminal input. The artifact manifest records the profile, assertion setting and this smoke result. These checks are scoped to the isolated fixture and do not imply a successful GUI input round trip or production validation.

## Independent release-profile candidate tool

`candidate.py` adds an offline preparation and local preflight path alongside the existing CI-only **dev-profile** fixture. It does not install or upgrade herdr, replace a running server, change `PATH`, create SSH authorization, or alter the existing workflows. Its output remains an experimental host candidate, not a production release or an upstream release.

Requirements: Python 3.10+, a POSIX Linux or macOS host, an existing checkout whose HEAD is exactly the commit above, Cargo/Rust 1.96.0, Zig exactly 0.16.0, and a complete offline dependency cache. The tool does not clone sources, download dependencies, install SDKs, or install toolchains. A Linux binary cannot be preflighted on macOS; the manifest's OS/architecture must match the executing host. Neither cross-compilation nor Windows host support is provided.

Use an explicit dependency cache that contains no `config`, `config.toml`, `credentials`, or `credentials.toml`. Do not pass your normal credential-bearing Cargo home. Cargo may acquire cache locks; source/configuration and build output are otherwise isolated. Missing offline dependencies fail the build rather than trigger a fetch.

From this repository, supply absolute paths:

```sh
python3 validation/herdr-input-extension/candidate.py build \
  --source /absolute/path/to/pinned-herdr-checkout \
  --cargo-cache /absolute/path/to/prepopulated-offline-cargo-cache \
  --output /absolute/path/to/new-candidate-directory
```

The output's parent must already exist without symlink components; the output directory itself must not exist. The source checkout is only read: its fixed committed tree is archived into a new temporary directory, so unrelated worktree changes are not included or modified. Git replacement objects and global Git configuration are disabled. The existing fixed patch is checked and applied only to that temporary tree.

Both the existing atomic-input guard test and the binary build run with `--offline --locked --release`. Exactly one passing guard test must be observed; Cargo's successful zero-test exit is rejected. The binary explicitly disables debug assertions. A successful output contains:

- `herdr-pocket-input-candidate`: a separately named binary, never copied over an installed `herdr`;
- the unchanged source patch and upstream `LICENSE`;
- `manifest.json`: experimental scope, upstream commit, patch SHA-256, release profile, binary assertion setting, compiler versions, host OS/architecture, binary SHA-256, producer script SHA-256, license hash, fixed upstream source URL, and temporary cleanup result.

A failed build records a failed manifest when output creation has already begun and does not publish a usable candidate binary. Early source/tool/cache refusals create no output. Hashes detect mismatches and corruption; they are not publisher signatures or reproducible-build attestations.

Preflight that candidate on the same host OS/architecture:

```sh
python3 validation/herdr-input-extension/candidate.py preflight \
  --candidate /absolute/path/to/new-candidate-directory \
  --output /absolute/path/to/new-preflight-directory
```

Preflight validates manifest and artifact hashes before execution. It creates its own short temporary path, fresh `HOME`/XDG directories and named session, with `/bin/sh` and no inherited SSH agent, herdr settings or shell startup hooks. It starts only the candidate server and connects only to its newly owned Unix socket; it starts no SSH server and reads no user authorization files.

The checks are deliberately limited:

1. Check binary version and a 0.9.5/protocol-22 snapshot at the newly created named-session socket; reject the `herdr-dev` directory convention.
2. Check the exact side-effect-free capability response, including JSON value types.
3. Create a temporary workspace using the same fixed CLI setup as the existing harness. Read its current pane and terminal identity, require definitive rejection of a different terminal, then submit the literal byte `x` once to the correct temporary target. No newline is sent, and input requests are never retried.
4. Require the correlated one-byte queue receipt, stop the owned server process group, and remove the owned temporary data. `preflight.json` preserves failed stages and cleanup results, without raw process output or terminal text. If process cleanup is unconfirmed, the owned temporary directory is retained and its path reported; the result is failed.

The snapshot has **no server-reported session or boot identity**. A successful `namedSocketIsolationChecked` therefore proves only the newly owned process/argument/socket-path setup; `serverReportedSessionIdentity` remains false. The input receipt proves queue acceptance, not PTY delivery or command execution (`ptyDeliveryVerified=false`). This preflight does not validate SSH/device authorization, GUI/full-frame rendering, live installation, upgrade/rollback, old-session migration, runtime permissions or production safety. It does not add a second client input transport.

## Local checks and current evidence

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s validation/herdr-input-extension -p 'test_*.py' -v
```

The tests use temporary files, a synthetic Unix-socket peer, and explicitly mocked build commands; they never run an installed herdr. An environment that prohibits Unix socket binding or signalling an owned process group must run these tests with the appropriate local execution permission. The tests cover wrong source/profile/platform/hash, credential-cache refusal, archive traversal, bounded manifests, zero matching tests, isolated environment, correlated receipts, timeout, and confirmed/unconfirmed cleanup.

On 2026-11-07, 16 tests passed on macOS arm64. Cargo and Rust 1.96.0 were available, but Zig was absent; no toolchain was installed, no upstream release-profile binary was built, and no real-herdr preflight ran. The synthetic peer's successful preflight is **test coverage only**. See `local-validation.json` for exact script/test/patch hashes and execution boundaries. Existing dev-fixture/Android GUI evidence remains separate.

## Optional cloud evidence lane (not yet executed)

The existing reusable workflow keeps its default dev fixture. Its new `workflow_call` boolean `release_candidate` defaults to `false`; setting it to `true` selects a separate release-profile mode, which additionally requires a `codex/network-batch/with-emulators-input-host-*` branch. The ordinary network-batch trigger and current dev/GUI routes are unchanged.

`android-network-experiment.yml` invokes this mode as the independent `input-host-candidate` job only on that explicit branch prefix. Its existing `input-fixture` call still uses the default dev mode. The two calls can run in parallel; Android pairing, Flutter checks and Apps have no dependency on the host-candidate call. A release candidate failure remains a failure in its own job and the overall batch, while it does not gate GUI jobs.

On a future qualifying batch the new lane will:

1. Reuse the existing fixed pocket/upstream checkouts, Rust 1.96.0 and Zig 0.16.0 archive/digest. Put Zig on the job's `GITHUB_PATH` so the candidate tool resolves the pinned compiler.
2. Create a dedicated `RUNNER_TEMP` Cargo cache with no configuration or credentials. Explicitly run `cargo fetch --locked` for the fixed source, then invoke the tool's offline release build with `--pocket-source-sha "$GITHUB_SHA"`. Build concurrency is limited to two Cargo jobs. No shared credentials/cache directory is imported or uploaded.
3. Run the real candidate in the tool's isolated named-session preflight. It does not use a GUI target, an installed server, SSH keys or a real user authorization file.
4. Use `candidate.py evidence` to publish only `summary.json`, named `input-host-release-evidence-<pocket SHA>`. It links the pocket commit, upstream commit, patch, Zig archive, compiler versions, producer script, candidate binary hash, actual tool-test counters, release guard result and preflight/cleanup status. Unknown fields, raw logs, terminal contents and retained local paths are excluded. Missing or mismatched evidence cannot report success.

**The candidate binary, dependency cache and raw build logs are not uploaded by this lane.** Dependency distribution review is recorded as pending. The pre-existing dev fixture artifact remains available to the existing GUI checks; the independent release lane never substitutes its binary into those checks.

Local verification of this cloud wiring: 19 tool tests passed, both workflow files parsed with Ruby/Psych, all shell blocks passed `bash -n`, and branch/boolean/dependency checks passed for the ordinary `with-emulators-input-recheck-*` path and the explicit `with-emulators-input-host-*` path. `local-validation.json` remains the historical initial 16-test tool record; its hashes do not describe this later wiring revision. No Actions run was started for this addition, and neither a real release-profile build nor real-herdr preflight has yet run in the new lane.
