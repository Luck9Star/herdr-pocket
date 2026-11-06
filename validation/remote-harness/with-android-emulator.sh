#!/usr/bin/env bash
# One disposable runner-owned AVD. Never select a user's attached device.
set -euo pipefail
[[ ${GITHUB_ACTIONS:-} = true && ${GITHUB_REF:-} = refs/heads/codex/* && $# -gt 0 ]]
: "${RUNNER_TEMP:?}" "${ANDROID_HOME:?}"
avd_evidence=${AVD_EVIDENCE_DIR:-"$RUNNER_TEMP/avd-evidence"}
temp_real=$(python3 -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).resolve())' "$RUNNER_TEMP")
evidence_candidate=$(python3 -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).resolve())' "$avd_evidence")
case "$evidence_candidate" in
  "$temp_real"/*) ;;
  *) echo 'AVD_EVIDENCE_DIR must be inside RUNNER_TEMP' >&2; exit 1 ;;
esac
mkdir -p "$evidence_candidate"
evidence_real=$(python3 -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).resolve())' "$evidence_candidate")
case "$evidence_real" in
  "$temp_real"/*) ;;
  *) echo 'AVD_EVIDENCE_DIR must be inside RUNNER_TEMP' >&2; exit 1 ;;
esac
export PATH="$ANDROID_HOME/emulator:$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
export ANDROID_SERIAL=emulator-5554
export ANDROID_AVD_HOME
ANDROID_AVD_HOME=$(mktemp -d "$RUNNER_TEMP/herdr-avd-XXXXXX")
image='system-images;android-35;google_apis;x86_64'
name='herdr-pocket-test'
# Record only controlled state labels, never attached-device identifiers.
evidence_event() { printf '%s\n' "$*" >> "$evidence_real/lifecycle.txt"; }
evidence_event 'preflight: checking for existing devices'
if ! devices=$(timeout 10 adb devices); then
  evidence_event 'preflight: adb devices failed'
  echo 'Unable to check for existing devices' >&2
  exit 1
fi
if awk 'NR>1 && NF {found=1} END {exit !found}' <<< "$devices"; then
  evidence_event 'preflight: existing device detected; refused'
  echo 'Refusing to run with an existing device' >&2
  exit 1
fi
evidence_event 'preflight: no existing device'
[[ -c /dev/kvm ]]
if [[ ! -w /dev/kvm ]]; then
  sudo setfacl -m "u:$(id -un):rw" /dev/kvm
fi
if [[ ! -x "$ANDROID_HOME/emulator/emulator" || ! -x "$ANDROID_HOME/platform-tools/adb" ||
      ! -f "$ANDROID_HOME/system-images/android-35/google_apis/x86_64/source.properties" ]]; then
  sdkmanager --install 'emulator' 'platform-tools' "$image"
fi
# Save actual tool/image revisions as the SDK registry can update this package.
cp "$ANDROID_HOME/system-images/android-35/google_apis/x86_64/source.properties" "$evidence_real/image.properties"
# The launcher sets its private library path. Check the actual launcher.
emulator -version > "$evidence_real/emulator-version.txt"
printf 'no\n' | avdmanager create avd --name "$name" --package "$image" --device pixel_5
emulator -avd "$name" -port 5554 -accel on -no-window -no-audio -no-boot-anim -no-snapshot -gpu software > "$RUNNER_TEMP/avd.log" 2>&1 &
avd_pid=$!
evidence_event 'startup: launched owned emulator on emulator-5554'
cleanup() {
  local original_status=$? cleanup_status=0 devices attempt
  trap - EXIT INT TERM
  evidence_event "cleanup: beginning; original status $original_status"
  if kill -0 "$avd_pid" 2>/dev/null; then
    timeout 10 adb -s "$ANDROID_SERIAL" emu kill >/dev/null 2>&1 || kill "$avd_pid" 2>/dev/null || true
    for _ in {1..15}; do kill -0 "$avd_pid" 2>/dev/null || break; sleep 1; done
    kill -KILL "$avd_pid" 2>/dev/null || true
  fi
  wait "$avd_pid" 2>/dev/null || true
  # The process can exit before the adb server removes its transport. Never
  # kill an unowned device or restart the shared adb server while waiting.
  for attempt in {1..15}; do
    if ! devices=$(timeout 4 adb devices); then
      evidence_event "cleanup: adb devices failed on attempt $attempt"
      cleanup_status=1
      break
    fi
    if ! awk -v serial="$ANDROID_SERIAL" 'NR>1 && $1 == serial {found=1} END {exit !found}' <<< "$devices"; then
      evidence_event "cleanup: owned serial absent on attempt $attempt"
      break
    fi
    if [[ $attempt = 15 ]]; then
      evidence_event 'cleanup: owned serial remained after bounded wait'
      cleanup_status=1
      break
    fi
    sleep 1
  done
  if (( cleanup_status )); then
    echo 'Failed to confirm removal of owned emulator transport' >&2
    (( original_status != 0 )) || original_status=1
  fi
  exit "$original_status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
ready=false
for _ in {1..240}; do
  kill -0 "$avd_pid" || exit 1
  if [[ $(timeout 4 adb -s "$ANDROID_SERIAL" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r') = 1 ]]; then ready=true; break; fi
  sleep 2
done
evidence_event "startup: boot ready=$ready"
[[ $ready = true && $(adb -s "$ANDROID_SERIAL" shell getprop ro.build.version.sdk | tr -d '\r') = 35 ]]
adb -s "$ANDROID_SERIAL" shell input keyevent KEYCODE_WAKEUP
adb -s "$ANDROID_SERIAL" shell wm dismiss-keyguard
"$@"
