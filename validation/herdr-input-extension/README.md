# herdr 0.9.5 pocket input candidate

This source patch is an experimental CI-only candidate against herdr release commit `2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01`. It is not an upstream release, does not modify an installed server, and is not a production deployment. Ordinary 0.9.5 has no `pocket.input.capabilities`; clients must remain read-only unless capability discovery succeeds over the same authenticated connection.

The capability is `pocket.input.capabilities`, version 1, protocol 22, `atomic_terminal_guard=true`, `raw_bytes=true`, `max_input_bytes=4096`. `pocket.input.send` takes the current public `pane_id`, `expected_terminal_id`, and canonical padded `bytes_base64` in one JSON request with a fresh lowercase 32-hex RPC id. The app event handler compares the current pane-to-terminal binding and enqueues exactly one 1–4096-byte payload without attach, resize, takeover, shell or retries. An accepted reply echoes the request id, pane, terminal and byte count; it means **accepted into the input queue**, not PTY delivery or command execution. `pocket_input_rejected` is the only matching-id definitive pre-enqueue rejection; any other response or transport loss has an unknown outcome. Request IDs correlate replies and do not imply deduplication.

Apply only in a disposable checkout of that exact commit and build/test the patched binary as an explicitly labelled candidate. Review the diff and negative cases before running any fixture. Never apply it to an installed or running host. A source patch, its compilation and isolated tests do not establish upstream adoption, mobile runtime or production safety.

```sh
git -C "$HERDR_TEMP_CHECKOUT" rev-parse HEAD
git -C "$HERDR_TEMP_CHECKOUT" apply --check "$POCKET_REPO/validation/herdr-input-extension/herdr-0.9.5-pocket-input.patch"
```

The Linux fixture build verifies the fixed Rust 1.96.0 environment and the upstream-required Zig 0.16.0 compiler before compiling the vendored Ghostty VT library. The runner checks the Linux x86_64 archive against the [official digest](https://ziglang.org/download/index.json). No local SDK is installed by this workflow.
