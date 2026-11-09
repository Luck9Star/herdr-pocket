# ZeroTier Android device vault candidate

`AndroidZeroTierDeviceStore` wraps the single-device core in an AndroidKeyStore
AES-256-GCM key, scoped to the core's ZeroTier alias and authenticated data. The
encrypted record lives under the application's `noBackupFilesDir`. Operations
require API 35 and run on a worker, not the UI thread. A missing identity is
reported by `status()` returning null; locked device, missing key, corrupt
record, unsupported API and I/O errors throw instead of generating an identity.
Do not send exception internals, aliases, private identities, lease IDs or
review capabilities to a GUI, log, export or method channel.
The key configuration follows Android's [KeyGenParameterSpec API](https://developer.android.com/reference/android/security/keystore/KeyGenParameterSpec).

The native manager must supply an `IdentityFactory` backed by the pinned native
identity ABI and a `NativeOwner` backed by the same process-global device-node
owner. This source does not load a library or supply a Java identity fallback.
Keep a single store instance strongly held for the application lifetime. Its
unreadable-identity review only trusts handles authenticated by that instance;
after process restart, if authentication is already impossible, recovery is
blocked until an independently trusted reference mechanism exists.

Explicit create durably persists before it returns the handle and instance ID.
Acquire the device `RuntimeLease` before native device construction. Its
one-shot initializer receives private bytes only during a synchronous callback;
the store clears its Java buffer after return or exception. This is best-effort
clearing, not a guarantee that every platform or native copy was erased. An
initialization error, timeout, unknown result or one network leaving does not
release the lease. Only the original native owner may confirm the exact lease
after stop, quiescence and draining all callbacks and streams. NODE_DOWN alone
is not a retirement proof. No finalizer or activity destruction releases it.

Pending creation and deletion require the explicit exact-handle recovery calls.
Unreadable discard is a separate two-step review and confirmation, bound to the
same instance and exact record; it is not automatic key-loss recovery. Never
register the opaque review object itself on a GUI channel.

`tests/run-zerotier-android.sh` compiles the real wrapper and core against local
Android stubs and a synthetic JVM provider. These tests do not exercise Android
KeyStore, hardware isolation, JNI, an Android device or a ZeroTier node. The
wrapper's runtime activation still requires a reviewed native bundle and binding.

## Shared mobile metadata service (2026-11-07)

`AndroidZeroTierDeviceService` now supplies the Flutter channel and Tauri host
commands with public metadata and explicit device mutations. It is an in-process
facade, not an Android background Service. The original native binding installs
the same store once; the GUI cannot install one, load libraries, acquire runtime
leases or export identity bytes. Until that binding is enabled, `status` returns
`available: false` with three null records. An installed store failure throws and
is never reported as an absent identity.

The shared Android production manifest deliberately includes this service and
its store/core/envelope dependencies, and — as of Stage 2 — the reviewed
`AndroidZeroTierNative.java` JNI bridge. The bridge never loads a library
itself: until a vetted host loads the provider library and calls
`bindNative(Context)`, the store stays uninstalled and the default unbound
capability remains unavailable. The metadata-only slice does not activate the
unfinished native stream draft.

`statusSnapshot` selects authenticated device, pending creation or pending
deletion under one core data lock. `forgetExact(handle, instanceId)` authenticates
the instance inside the owner/data lock and refuses pending deletion instead of
silently resuming it. Hosts separately lock and validate the complete reviewed
catalog for each mutation. The service rejects concurrent calls instead of
waiting behind an unresolved operation. Close, background and unknown results
never replay a write.

`write(action, handle, instanceId, expectedPhase)` requires the exact reviewed
phase for pending operations. Creation recovery accepts `record-present` or
`finishing`; discard accepts `record-pending` or `finishing`. The core checks
record presence under the same owner/data lock, so `finishing` does not grant
permission to discard an installed identity. Deletion recovery accepts
`record-present`, `record-removed` or `finishing` and refuses a missing intent;
it never falls back to first-time removal of a normal device.

`sh validation/network-profiles/native/android/tests/run-zerotier-service.sh`
passes 128 checks in four isolated JVM modes, including exact-instance removal,
runtime-lease exclusion, pending phase recovery and concurrent rejection. Synthetic
identities and the existing fake JCE provider remain explicit. The Flutter
channel and Tauri plugin also run against this Java service and store in
isolated desktop JVMs. See the [mobile integration results and rerun commands](../../../../docs/55-mobile-shared-network-device.md)
for the Android runtime and network checks that remain open.
