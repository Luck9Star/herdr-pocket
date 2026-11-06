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
wrapper has not been wired into either GUI or a build manifest.
