#!/usr/bin/env bash
# One disposable runner-owned AVD. Never select a user's attached device.
set -euo pipefail
[[ ${GITHUB_ACTIONS:-} = true && ${GITHUB_REF:-} = refs/heads/codex/* && $# -gt 0 ]]
: "${RUNNER_TEMP:?}" "${ANDROID_HOME:?}"
export PATH="$ANDROID_HOME/emulator:$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
export ANDROID_SERIAL=emulator-5554
export ANDROID_AVD_HOME
ANDROID_AVD_HOME=$(mktemp -d "$RUNNER_TEMP/herdr-avd-XXXXXX")
image='system-images;android-35;google_apis;x86_64'
name='herdr-pocket-test'
if adb devices | awk 'NR>1 && NF {found=1} END {exit !found}'; then
  echo 'Refusing to run with an existing device' >&2
  exit 1
fi
[[ -c /dev/kvm ]]
if [[ ! -w /dev/kvm ]]; then
  sudo setfacl -m "u:$(id -un):rw" /dev/kvm
fi
sdkmanager --install 'emulator' 'platform-tools' "$image"
# Save actual tool/image revisions as the SDK registry can update this package.
mkdir -p "$RUNNER_TEMP/avd-evidence"
cp "$ANDROID_HOME/system-images/android-35/google_apis/x86_64/source.properties" "$RUNNER_TEMP/avd-evidence/image.properties"
emulator -version > "$RUNNER_TEMP/avd-evidence/emulator-version.txt"
printf 'no\n' | avdmanager create avd --name "$name" --package "$image" --device pixel_5
emulator -avd "$name" -port 5554 -accel on -no-window -no-audio -no-boot-anim -no-snapshot -gpu software > "$RUNNER_TEMP/avd.log" 2>&1 &
avd_pid=$!
cleanup() {
  if kill -0 "$avd_pid" 2>/dev/null; then
    timeout 10 adb -s "$ANDROID_SERIAL" emu kill >/dev/null 2>&1 || kill "$avd_pid" 2>/dev/null || true
    for _ in {1..15}; do kill -0 "$avd_pid" 2>/dev/null || break; sleep 1; done
    kill -KILL "$avd_pid" 2>/dev/null || true
  fi
  wait "$avd_pid" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT TERM
ready=false
for _ in {1..240}; do
  kill -0 "$avd_pid" || exit 1
  if [[ $(timeout 4 adb -s "$ANDROID_SERIAL" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r') = 1 ]]; then ready=true; break; fi
  sleep 2
done
[[ $ready = true && $(adb -s "$ANDROID_SERIAL" shell getprop ro.build.version.sdk | tr -d '\r') = 35 ]]
adb -s "$ANDROID_SERIAL" shell input keyevent KEYCODE_WAKEUP
adb -s "$ANDROID_SERIAL" shell wm dismiss-keyguard
"$@"
