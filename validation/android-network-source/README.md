# Android vault to native node configuration

2026-11-06. Shared Rust `SecureConfigSource` for an Android host. This is native integration source, not Android runtime or real-network evidence. `jni = 0.21.1` and `zeroize = 1.9.1` are pinned; the standalone lock file fixes transitive dependencies. Both versions already occur in the Tauri dependency set.

The host exports `Java_org_herdr_network_AndroidEasyTierConfig_bindNative` and forwards its `JNIEnv`, originating `JClass`, and `Context` to `bind`. Java calls the method after the host library is loaded. The implementation retains only the application Context, JavaVM and a GlobalRef to that class, rejects a changed binding and defines no JNI_OnLoad. App-class lookup never occurs from a Rust-created thread.

Construct an `AndroidSecureConfigSource` for each explicit start using the reviewed public profile ID, persisted revision, network name, identity handle and peers. `load` checks the same immutable fields in `NodeSpec`; its process-local attempt number is not a persisted configuration revision. The lifecycle worker attaches to Java with a scoped guard and a bounded local frame. The [Java builder](../network-profiles/native/android/README.md) checks the protected record and produces fixed, bounded TOML. It does not accept arbitrary TOML or expose a Dart/JS command. No secret-bearing configuration is persisted or returned through frontend IPC.

The Rust source copies the returned array into `SecretConfig`, clears the Java array, and clears owned temporary bytes on failure. Java exceptions are cleared without describing/logging their contents. Best-effort clearing cannot erase VM/framework or engine copies. The application Context/class live until process exit. Missing initialization, unreadable vault, mismatched binding and invalid output refuse startup; there is no plaintext or system-network fallback. The fixed native engine currently rejects empty network secrets, so a stored `PUBLIC_NO_SECRET` identity cannot start this candidate.

Validation commands from the repository root:

```sh
cargo test --locked --offline --manifest-path validation/android-network-source/Cargo.toml
cargo clippy --locked --offline --manifest-path validation/android-network-source/Cargo.toml --all-targets -- -D warnings
sh validation/android-network-source/tests/run-jvm.sh
```

The last command builds a temporary desktop cdylib with the explicit `jvm-fixture` feature and compiles self-created Java classes, then runs Java with `-Xcheck:jni`. It checks missing/changed application binding, exact revision, worker attachment, Java exceptions, bad/oversize/null buffers, clearing, and repeated local frames. Its classes replace Android Context and vault access and cannot prove AndroidKeyStore, Gradle packaging, device lifecycle or EasyTier connectivity. Never enable `jvm-fixture` in an application; it is not a missing-library fallback. The temporary JVM exits and its build directory is removed on completion.

Context7 library→docs was queried on 2026-11-06. Its general docs.rs result showed newer API examples; implementation was instead checked against the downloaded, fixed `jni 0.21.1` source and [0.21.1 JavaVM documentation](https://docs.rs/jni/0.21.1/jni/struct.JavaVM.html). This avoids mixing API generations.

## Tailscale native state source

`bind_tailscale` is independent of the EasyTier binding and retains the exact
application context and originating class. The Android host must export
`Java_org_herdr_network_AndroidTailscaleConfig_bindNative` and forward its JNI
arguments to `bind_tailscale` after loading its native library; this source does
not change either host or add `JNI_OnLoad`. Construct one
`AndroidTailscaleSource` per authorized start using the profile ID, profile
revision, network, identity, hostname and reviewed control URL. The runtime
assigns the attempt later. The first load matching the public binding and a
nonzero attempt atomically freezes its complete `NodeSpec`; other attempts are
rejected before vault access, while the same spec may be loaded again. A new
attempt requires a new source. A mismatching public binding cannot claim it.

The Java bridge obtains the handle-specific runtime directory from the native
store and checks the framework no-backup directory using `lstat` and owner UID, then
checks each app-owned component for the same owner and mode 0700. The store
creates its directories with an atomic 0700 mode and rejects unsafe existing
directories without changing their permissions. State keys remain arbitrary bytes
(up to 1024), with no UTF-8 conversion. Null value deletes; an empty array is a
present empty value. Only the dedicated missing-key exception maps to Missing;
all other errors refuse operation. JNI workers attach to the cached VM, retain
the cached class and context, and best-effort clear temporary Java arrays and
failed Rust value copies. This cannot erase all VM or engine copies.

```sh
sh validation/android-network-source/tests/run-tailscale-jvm.sh
```

This is a desktop JVM `-Xcheck:jni` fixture using the production Java bridge,
synthetic Android APIs and a synthetic vault; it covers worker callbacks,
binding, bounds, binary keys, exceptions, zeroing and unsafe directory metadata.
The separate StateStore JCE fixture exercises the real storage core. Neither
proves AndroidKeyStore, Android filesystem metadata, app packaging, a device or
network operation. The app host binding above is still required.
