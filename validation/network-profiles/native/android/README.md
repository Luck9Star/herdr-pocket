# Android network secret vault prototype

Shared native sources for the Flutter and Tauri Android hosts. Requires Android API 35 or newer. This directory is independent of the SSH device-key directory and aliases. This is a prototype: the JVM fixture does not exercise AndroidKeyStore, Android filesystem durability, lock behavior, app lifecycle, devices, or any network provider.

Apply `network-secrets.gradle` with `herdrNetworkSecretsDir` set to this directory, after the Android plugin. There are no third-party dependencies. Call blocking APIs off the UI thread.

## Android production source boundary (2026-11-08)

`android-production-sources.txt` is the complete shared Java production input
list: 14 top-level files covering the existing EasyTier vault/config, Tailscale
state/config, the ZeroTier device core/envelope/wrapper/metadata service, and
— as of Stage 2 — the reviewed `AndroidZeroTierNative.java` JNI bridge. Gradle
rejects a missing, empty, duplicate or non-basename Java entry, refuses symbolic
links for the manifest and listed Java sources, and checks every
listed file before configuration succeeds. Its `Sync` copies only those inputs
into the generated source root. It executes on each build so a reused build
directory loses obsolete nested sources and unlisted drafts before Kotlin or
Java compilation. Packaging provenance must use this same manifest, not a glob.

The JNI bridge never loads a library itself. Until a vetted host explicitly
loads the ZeroTier provider library and calls `bindNative(Context)` (Stage 4),
the store stays uninstalled, the narrow `IdentityFactory` and `NativeOwner`
capabilities stay inert, and no fallback generates an identity or pretends a
runtime retired. Without installation, the service returns exactly
`available: false` and null device/pending records, and valid mutations fail
with `device store unavailable`. No native library is loaded and no store
directory is created. Publishing this metadata slice needs no ZeroTier upstream
patch or stream draft; enabling a real identity/node later requires host
library, binding and application validation beyond this manifest.

Offline closure regression (use an already available local Gradle distribution):

```sh
python3 validation/network-profiles/native/android/tests/run-production-sources.py \
  --gradle /absolute/local/gradle/bin/gradle --output /private/tmp/new-evidence-dir
```

The runner uses temporary HOME/Gradle directories and `--offline`, exercises the
actual Gradle `Sync` and compile-task dependencies, rejects each missing input
and malformed manifests, rejects manifest/source symlinks before Sync,
excludes invalid top-level drafts and nested tests,
and cleans a deliberately stale generated source tree on an unchanged-input
rerun. It compiles exactly the synced production files with local Android stubs
and verifies the absent JNI class plus unavailable service/five mutations in a
real JVM. The Gradle fixture models only source-set/task interfaces; it is not an
AGP/SDK build or Android device/KeyStore/native-network result. Its local file-lock
socket may require running outside a restrictive sandbox.

`org.herdr.network.AndroidNetworkSecretStore` provides `create(profileId, provider, mode, secret)`, `status(profileId, provider)`, and `delete(profileId, provider, handle)`. The only provider accepted today is `easytier`; profileId must be 32 lowercase hexadecimal characters. A profile has at most one identity. Create generates separate UUIDv4 handle and instanceId; the latter stays stable across status/restart. An explicit `PRIVATE` mode requires 1–1024 valid UTF-8 bytes without NUL; `PUBLIC_NO_SECRET` requires an empty array. Caller owns and clears its input array in a `finally` block. Never log secrets, exception details, or send secret values back over a bridge. Result contains only profileId, provider, handle, instanceId, mode.

Status returns null only when no file exists. Lock, missing/inaccessible key, bad record, authentication failure, and unsupported provider are errors; no operation silently recreates a key. Bridge code should classify failures into safe public codes without exposing original exception messages. After an interrupted or unknown-result create, query status before any further action; never automatically retry a write. Delete verifies the three identifiers and protected record, deletes the key first, then unlinks the record. An unlink failure can leave an unreadable record; missing keys and corrupt records require explicit recovery policy, not silent replacement. Destructive recovery is outside this prototype.

The `withSecret` callback is package-private for a same-package native provider adapter only, and must never be bound to Dart/JS or exposed as a read endpoint. It executes synchronously while holding the storage lock; adapters must not retain/copy/return/log secret data, call back into this store, or use an asynchronous operation that outlives the callback. Temporary arrays owned by this implementation are overwritten best effort; this does not guarantee erasure of VM, framework, provider, or caller copies. Calls are serialized across instances in a process and with a filesystem lock across app processes, assuming all writers use this implementation and the app-private directory remains controlled by the app. Same-UID hostile filesystem modification and rollback protection are not claimed.

The format stores a bounded AES-GCM envelope under app no-backup storage. AAD binds format version, profileId, provider and handle. The Android key alias uses `org.herdr.pocket.network-secret.v1.` and a UUIDv4; key generation is only performed during explicit create, with `setUnlockedDeviceRequired(true)`. Decryption never regenerates aliases. This requires successful keystore access and unlock state; it is not a hardware-backing claim.

Offline test: `validation/network-profiles/native/android/tests/run.sh` compiles only the pure Java core and uses disposable temporary directories and in-memory test keys. It never creates Android keys or touches real SSH/network identities. The test checks restart, explicit public/private mode, wrong profile/provider/handle, tamper, missing alias, locked backend, create failure, symlink/path traversal, concurrent duplicate creation, deletion, size/capacity bounds, and injected metadata access denial. The POSIX permission check reports SKIP when unsupported or when the effective user bypasses permissions.

Android API references: [KeyGenParameterSpec.Builder, API 35 baseline](https://developer.android.com/reference/android/security/keystore/KeyGenParameterSpec.Builder#setUnlockedDeviceRequired(boolean)), [Context.getNoBackupFilesDir](https://developer.android.com/reference/android/content/Context#getNoBackupFilesDir()), [KeyguardManager.isDeviceLocked](https://developer.android.com/reference/android/app/KeyguardManager#isDeviceLocked()). Context7 Android Developers lookup on 2026-11-06 confirmed the unlocked-device restriction; actual API behavior remains unverified on a device.

## JNI-only EasyTier configuration

`AndroidEasyTierConfig.bindNative(Context)` is implemented by the host's Rust native library and must be called by the host plugin with the application context after loading that library; this class does not define `JNI_OnLoad` or load a native library. `AndroidEasyTierConfig.load(Context, profileId, expectedHandle, networkName, peers)` is a native-caller-only Java entry point, never a Dart/JS/platform command. The returned UTF-8 byte array contains the network secret: the JNI/native caller must avoid logging, retain it only as long as necessary, and overwrite the Java and native mutable buffers after use. VM, JNI, cryptographic-provider, and TOML-parser copies cannot be guaranteed erased.

The vault checks the profile and expected handle and decrypts the instance UUID, mode, and secret once under its storage lock; it never uses a separate status-then-load sequence. The fixed builder emits only instance_id, DHCP, empty listeners, network_identity, peers and no_tun. It enforces the public network name and peer limits, valid UTF-8 secret, TOML string escaping, and a 64 KiB output ceiling. Java URI host parsing is conservative; some unusual host forms accepted by a GUI parser may be rejected here. An explicit `PUBLIC_NO_SECRET` record fails with `public_network_secret_unsupported` because the current pinned outbound-only native policy requires a non-empty secret. No synthetic password or modified policy is used. This is a config-construction and JVM fixture result, not Android SDK, JNI, actual native-parser, device, lifecycle, connectivity, or network-join verification.

## Android Tailscale StateStore source candidate

`AndroidTailscaleStateStore` is a separate API 35+ source candidate with its own no-backup namespace and AndroidKeyStore AES-256-GCM alias prefix. It does not change the EasyTier vault. Its public lifecycle surface is `create(profileId)`, `status(profileId)`, and `delete(profileId, handle)`; a result contains only the profile ID, provider label, UUIDv4 handle, and separate UUIDv4 instance ID. An explicit create generates an empty encrypted table and a new key. A missing record alone yields null status; locked device, missing key, corrupt record, unsafe path, and I/O errors do not. After an uncertain create, inspect status rather than retrying blindly. Previously observed identity files that disappear are rejected within the same process; an externally removed file before a later process starts cannot be distinguished from an identity that never existed.

Deletion first authenticates the original record and durably writes a bounded intent containing its profile, exact handle, and ciphertext SHA-256. It then removes the key and original record. If deletion fails or the process stops, all ordinary operations fail closed until an explicit `delete` with the same handle resumes that intent. A changed record or handle is rejected before touching either key; corrupt or unsafe intents are never treated as absent. Pending intents count toward the profile limit. At most 32 orphaned atomic-write temporary files are tolerated; exceeding that bound fails rather than silently deleting files. A failed sync or interrupted operation remains an unknown result and needs explicit status/recovery; it is not automatically retried. If the final intent unlink succeeds but its directory sync fails, an in-process finishing marker retains the original handle and allows a same-handle sync retry. After process restart, if both intent and record are absent the store can observe only the current absence; it cannot reconstruct that prior sync result.

The package-private `readState(profileId, handle, stateKey)`, `writeState(profileId, handle, stateKey, value)`, and `runtimeDirectory(profileId, handle)` methods are for a JNI/native adapter, never a Flutter/Tauri GUI channel. A missing state key throws the distinct `StateKeyNotFoundException`; a present zero-length byte array is returned as such. A null write removes a key; an empty byte array writes an empty value. Keys are UTF-8 names, including empty strings and `/`, never paths; invalid Unicode is rejected. Values and returned plaintext buffers must remain within the native bridge and be cleared by their owner. No node is started, no authentication token is read from the environment, and no GUI receives StateStore contents.

The limit is 32 active profile records, 256 keys per profile, 1024 UTF-8 bytes per key, 262144 bytes per value, and 4 MiB per serialized plaintext table, including serialization overhead. A process lock plus file lock serializes cooperating app processes. Each update decrypts and validates the entire map, checks the original record again, encrypts with a new random GCM nonce and AAD binding format/provider/profile/handle, then performs a same-directory atomic replacement and file/directory sync. No unsupported atomic-move fallback exists. A failure after replacement can mean the new value was installed: the error is not proof of rollback and the caller must not replay automatically. The locks and compare check do not claim rollback protection or defense against a hostile same-UID process that ignores the lock.

`runtimeDirectory` constructs an app-private directory from the verified handle; it never accepts a GUI-supplied path and must be re-derived after app storage moves. A successful identity deletion removes its empty runtime directory only; nonempty historical directories are retained instead of recursively deleting unknown tsnet files. At most 32 runtime entries are allowed, including retained ones; reaching the bound fails explicitly. The caller must ensure a future tsnet integration actually uses this StateStore and does not persist sensitive state unencrypted in that runtime directory. Runtime directory cleanup, JNI binding, process lifecycle, and real tsnet behavior remain unverified.

Run `sh validation/network-profiles/native/android/tests/run-tailscale-state.sh` for the isolated JVM fixture. It compiles the real Java core, envelope, and wrapper with minimal Android API stubs, exercises temporary JCE-only keys and temporary files, starts real JVM subprocesses for lock contention, and checks public versus JNI-only method visibility. This is not Android SDK/AndroidKeyStore, JNI execution, hardware-backed key, device-lock, power-loss durability, process integration, network join, or five-platform evidence. Android sources use [AndroidKeyStore AES-GCM](https://developer.android.com/reference/android/security/keystore/KeyGenParameterSpec), [no-backup app storage](https://developer.android.com/reference/android/content/ContextWrapper#getNoBackupFilesDir()), and [atomic move](https://developer.android.com/reference/java/nio/file/Files#move(java.nio.file.Path,java.nio.file.Path,java.nio.file.CopyOption...)); Context7 official Android Developers documentation was queried on 2026-11-06.
