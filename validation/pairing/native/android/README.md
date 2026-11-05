# Android device signer prototype (API 35)

Both Android GUI candidates share these Java sources under `org.herdr.pairing`.
`AndroidDeviceKeyStore(Context)` exposes only:

- `create()` → `CreatedKey.handle` (canonical random UUID v4), `CreatedKey.publicKey` (canonical `ssh-ed25519` public line, no comment/newline).
- `publicKey(handle)` → the same public line, only after protected seed access and public-key verification.
- `sign(handle, byte[])` → exactly 64 raw Ed25519 signature bytes; maximum input 65,536 bytes, including empty messages.
- `delete(handle)` → invalidate the AndroidKeyStore wrapping key, then remove the encrypted record. A missing handle is never recreated by read/sign/delete.

The facade is not a network protocol or authorization policy. GUI bridges must bound input before Base64 decode and only dispatch the expected challenge operation. Handles and public keys may cross Dart/JS; seeds/envelopes must never cross it. The seed exists in native process memory during operations; this is software Ed25519 protected at rest by an AES-GCM AndroidKeyStore key, not hardware Ed25519. Native code clears its seed buffers; neither Java GC nor third-party temporary buffers offer complete memory-erasure guarantees.

## Reuse and dependency

Keep a single source copy. In each Android app's Gradle build, resolve this directory from the repository root and add it to `android.sourceSets.main.java`, excluding `tests/**`. It contains exactly four production Java files; do not copy them into each app. Add:

```groovy
implementation 'org.bouncycastle:bcprov-jdk18on:1.86'
```

Alternatively, after applying the Android app/library plugin, set `ext.herdrDeviceKeysDir` to this directory as an absolute `File`, then `apply from: new File(herdrDeviceKeysDir, 'device-keys.gradle')`. The reusable script adds the shared Java sources, excludes fixture tests, sets Java 17, pins the dependency, and packages the MIT notice as an asset. App builds still set the Android SDK baseline and Maven Central themselves. Do not apply both this script and duplicate copied sources.

Set `compileSdk` and `minSdk` to 35, compile Java 17, and use Maven Central. This intentionally fails unsupported devices rather than weakening protected storage. Bouncy Castle's lightweight `Ed25519` static API is used directly; no JCA provider is registered or replaced. The fixed artifact SHA-256 and fixed release sources are in `../../sources.json`. The MIT notice is retained in [notices/BOUNCY-CASTLE-LICENSE.md](notices/BOUNCY-CASTLE-LICENSE.md), extracted from the verified JAR's `META-INF/LICENSE.md`. The shared Gradle script includes this notice as an APK asset. APK notice presence remains a packaging verification check.

## Storage and failure behavior

Records live only in `Context.getNoBackupFilesDir()/herdr-device-keys-v1`, scoped to each app UID. The Flutter and Tauri apps do not share identities. A record is fixed at 97 bytes: four magic/version bytes, 32 public-key bytes, and the 61-byte AES-GCM envelope (version, random 12-byte IV, encrypted seed plus 16-byte tag). No plaintext seed is persisted. Each UUID selects a distinct AndroidKeyStore AES-256 alias; alias is authenticated as AAD. `setUnlockedDeviceRequired(true)` is mandatory. The facade also rejects create/public/sign while `KeyguardManager.isDeviceLocked()` is true; the Keystore policy covers lock-state races during cryptographic operations. Deletion remains available to invalidate a key while locked.

Creation writes a same-directory temporary file, fsyncs it, atomically renames it, and fsyncs the directory before returning the handle. There is no non-atomic fallback. Exceptions clean up the temporary/final file and wrapping alias; cleanup failures are attached to the error, never returned as success. Process serialization and an app-private file lock protect operations. UUID validation, fixed-length reads, symlink rejection, signature-input bounds, and 128-key capacity limit file/path/resource abuse. The app-private directory is not a defense against a compromised same-UID process.

On process/power interruption, an orphan alias or `.pending-*` record can remain; no read path adopts it or silently replaces a missing key. Orphans count toward the capacity limit and require explicit app-data reset/re-pairing after diagnosis. Power-loss durability and OEM filesystem behavior need device validation. Deletion invalidates the alias first, so a failed unlink cannot permit continued signing. Locked, lost, invalidated, corrupt, or mismatched key material causes a failure requiring explicit recovery/new pairing; there is no seed export, host file access, network fallback, or automatic replacement.

## Evidence and limits

`tests/DeviceKeyStoreCoreTest.java` runs only a memory AES backend and temporary files. The local Java 17-targeted compile/run passed 32 checks: RFC8032 known-answer vector, canonical SSH wire, restart identity, signature verification, size limits, traversal/case rejection, simulated locking/key loss, public/envelope tampering, deletion, partial-create cleanup/seed clearing, and capacity. It does not instantiate `AndroidSeedEnvelope` or any Android API.

The pairing workflow compiles all four production sources against Android API 35 and the pinned/checksummed BC dependency, then runs those pure JVM fixtures. This turn did not execute that cloud workflow or an emulator. No local Android SDK was installed; no real device/AndroidKeyStore, lock-screen state, backup/restore, app upgrade, or physical-device behavior was tested. Those remain acceptance gates.
