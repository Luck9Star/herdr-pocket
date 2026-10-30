# Pairing workflow evidence

- Source: `c276c95fc3796b6f6de1ce3b6978195b5573a541`
- Run: [41061177628](https://github.com/Luck9Star/herdr-pocket/actions/runs/41061177628)
- All three jobs succeeded; each downloaded artifact's `SHA256SUMS` verified locally.
- macOS contract job: 21 pairing contract tests and 15 helper tests passed. The CryptoKit probe used a memory-only double (`systemKeychainCalls: 0`); no system Keychain or device storage was exercised.
- Ubuntu contract job: 21 pairing contract tests and 15 helper tests passed.
- Android bridge job: Android API 35 compile only. Keystore runtime and device execution were not performed.
- All artifacts identify the same source SHA. The contract manifests mark real authorization and native device storage as not executed.

Artifacts are kept in `contract-macos/`, `contract-ubuntu/`, and `android-bridge/`. These are fixture, memory-double, and compile results; they do not verify real authorization, device storage, or device behavior.
