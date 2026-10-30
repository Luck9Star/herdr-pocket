# Mobile observe delivery checks

Current job and artifact matrix: [delivery-checks.json](delivery-checks.json). It records source SHAs, job IDs, artifact IDs, and the verification boundary for each run.

## Current app build matrix

| Source and workflow | Android | iOS | macOS | Windows | Linux | Run state |
| --- | --- | --- | --- | --- | --- | --- |
| Tauri `d459919` | [12980657085](https://github.com/Luck9Star/herdr-pocket/actions/runs/41062065682/artifacts/12980657085) success, SHA checked | [12978843825](https://github.com/Luck9Star/herdr-pocket/actions/runs/41062065682/artifacts/12978843825) success | [12980576230](https://github.com/Luck9Star/herdr-pocket/actions/runs/41062065682/artifacts/12980576230) success, SHA checked | [12981802286](https://github.com/Luck9Star/herdr-pocket/actions/runs/41062065682/artifacts/12981802286) success | [12981335575](https://github.com/Luck9Star/herdr-pocket/actions/runs/41062065682/artifacts/12981335575) success | [run 41062065682](https://github.com/Luck9Star/herdr-pocket/actions/runs/41062065682), success |
| Flutter experimental candidate `c276c95` | [12979242829](https://github.com/Luck9Star/herdr-pocket/actions/runs/41061177588/artifacts/12979242829) success, SHA checked | [12978943348](https://github.com/Luck9Star/herdr-pocket/actions/runs/41061177588/artifacts/12978943348) success | [12980005671](https://github.com/Luck9Star/herdr-pocket/actions/runs/41061177588/artifacts/12980005671) success, SHA checked | [12979013262](https://github.com/Luck9Star/herdr-pocket/actions/runs/41061177588/artifacts/12979013262) success | [12979940766](https://github.com/Luck9Star/herdr-pocket/actions/runs/41061177588/artifacts/12979940766) success | [run 41061177588](https://github.com/Luck9Star/herdr-pocket/actions/runs/41061177588), success |

Flutter app artifacts above are distinct from its candidate renderer evidence artifacts `12979142270` and `12979565966`. Those are logs/render characterization, not app packages.

The Tauri d459 Android and macOS archives are under `/tmp/herdr-mobile-observe-d459/`; the Flutter candidate Android and macOS archives are under `/tmp/herdr-mobile-observe-c276/`. Package hashes and paths are recorded in the platform metadata JSON files in this directory. The two current macOS package records point to the later limited GUI smoke record at `../macos/verification.json`; `packageWasRun: false` records their earlier artifact verification stage. None of these checks establishes mobile device behavior.

## Test and transport runs

- [Remote read-only adapters](https://github.com/Luck9Star/herdr-pocket/actions/runs/41060251076), source `73ce2f8`: 18/18 cases passed across Rust and Dart adapters; remote input was 0 bytes. The safe, two-layer-checksummed artifact is archived under [run 41060251076](../41060251076/README.md).
- [Pairing and device-key validation](https://github.com/Luck9Star/herdr-pocket/actions/runs/41061177628), source `c276c95`: macOS and Ubuntu each passed 21 pairing contract and 15 helper tests; Android passed API 35 bridge compilation. The artifacts and limitations are recorded under [run 41061177628](../41061177628/README.md).
- [Flutter validation shells](https://github.com/Luck9Star/herdr-pocket/actions/runs/41061177552), source `c276c95`: lock-and-test and all five app build jobs succeeded. The overall workflow is marked failed because the separate `render-characterization` job reproduces the known original `terminal_view 0.5.0` combining-glyph issue.
- The experimental Flutter candidate's `patch-and-test`, macOS renderer check, and five app build jobs all succeeded. Its renderer patch remains a local experiment, not an upstream fix or framework selection.
- First Flutter runs on source `73ce2f8` ([validation shells](https://github.com/Luck9Star/herdr-pocket/actions/runs/41060251057), [experimental candidate](https://github.com/Luck9Star/herdr-pocket/actions/runs/41060251060)) failed a widget test on the lifecycle transition `hidden -> resumed`. The c276 test update passes; it does not change real-device lifecycle evidence.
- The earlier Tauri run [41060251058](https://github.com/Luck9Star/herdr-pocket/actions/runs/41060251058), source `73ce2f8`, was cancelled after the d459 push by the workflow's concurrency policy. Its completed platform jobs and cancellation are retained in `delivery-checks.json`.

All CI builds are test candidates. Real mobile touch, Chinese IME, camera pairing, protected storage, production signing, GUI remote success, and lifecycle recovery remain unverified.
