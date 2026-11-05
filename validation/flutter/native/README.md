# Flutter public metadata persistence

`HostCatalogFile` is the app-private public metadata boundary: Android uses
`Context.noBackupFilesDir`, Apple a fixed Application Support directory marked
`isExcludedFromBackup`. Versioned data has at most 16 host profiles and 256 KiB.
The native channel accepts only a revision and complete public JSON; paths are
fixed by native code. File locks, atomic replace, fsync and SHA-256 CAS reject
stale writers. Dart validates field allowlists, duplicate decoded fields, target
and device-public-key bindings before exposing a profile or writing a catalog.

Native seed/key storage remains separate. The catalog holds only public target
fields, opaque local key handles, public requests and pairing state. No PEM,
seed, command body, overlay credentials, review checkbox or live connection is
stored. Reopening a profile checks its original handle/public key and requires
manual review before connecting. Locked/missing/changed keys stop; no replacement
identity is generated. Restoring a previously paired state only restores an
explicit-reconnect state. A waiting request reopened from disk becomes cancelled;
its matching reviewed revocation may still resolve unknown host authorization.

Before calling native key creation, a pending-creation intent is saved. A crash
before the handle is durably recorded therefore blocks new creation rather than
assuming the old call did nothing. A known incomplete handle can be explicitly
deleted. An unknown handle needs manual investigation; this implementation does
not silently clear that marker. Host-profile deletion first persists disabled,
then deletes the original local identity, then removes the profile. Neither
profile disable/delete nor local-key deletion revokes the host authorization.

`herdr.pocket/input_journal` uses a different fixed directory and a conservative
single pending marker: `read() -> String?`, `prepare({record:String}) -> void`,
`clear({record:String}) -> void`. Only the 12 public target/request fields are
accepted, at most 8192 UTF-8 bytes; duplicates, controls and extra fields fail.
Prepare requires an empty slot; clear requires the exact original complete JSON
and uses CAS. Its file never contains terminal input or command content. This
slot prevents any second input write while an unresolved write exists, including
a write for another host. The adapter decides when reconciliation permits clear.

Local lightweight checks (macOS, temporary fixtures only):

```sh
swiftc -module-cache-path /tmp/herdr-swift-cache \
  validation/flutter/native/apple/tests/FlutterChannelStubs.swift \
  validation/pairing/native/apple/DeviceKeys.swift \
  validation/flutter/native/apple/HostCatalogFile.swift \
  validation/flutter/native/apple/tests/HostCatalogProbe.swift \
  -o /tmp/herdr-catalog-probe
/tmp/herdr-catalog-probe

swiftc -module-cache-path /tmp/herdr-swift-cache \
  validation/flutter/native/apple/tests/FlutterChannelStubs.swift \
  validation/pairing/native/apple/DeviceKeys.swift \
  validation/flutter/native/apple/HostCatalogFile.swift \
  validation/flutter/native/apple/InputJournalFile.swift \
  validation/flutter/native/apple/tests/InputJournalProbe.swift \
  -o /tmp/herdr-journal-probe
/tmp/herdr-journal-probe
```

The first probe passed 10 file-mechanism checks; the second passed 11 public-marker
checks. Swift channel typechecking uses explicit Flutter stubs. No Keychain or
Keystore operation is invoked by these probes. Flutter/Dart tests, Android
compilation, app restart, file protection, device backup exclusion and phone
runtime were not run locally. Calling the backup-exclusion API is not backup
behavior evidence; the temporary-directory probe does not claim that behavior.
