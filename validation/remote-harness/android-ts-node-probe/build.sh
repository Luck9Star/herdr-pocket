#!/usr/bin/env bash
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
: "${ANDROID_HOME:?}" "${RUNNER_TEMP:?}"
[[ ${GITHUB_ACTIONS:-} = true && ${GITHUB_REF:-} = refs/heads/codex/* ]]
native=${1:?native bundle}; source=${2:?fixed native source}; out=${3:?output APK}
case "$out" in "$RUNNER_TEMP"/*) ;; *) exit 1 ;; esac
jar="$ANDROID_HOME/platforms/android-35/android.jar"
tools="$ANDROID_HOME/build-tools/35.0.0"
tmp=$(mktemp -d "$RUNNER_TEMP/hp-ts-node-build-XXXXXX")
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/classes" "$tmp/dex" "$tmp/apk/lib/x86_64"
for library in libheeler_easytier.so libhp_tailscale.so libherdr_flutter_network_runtime.so; do cp "$native/$library" "$tmp/apk/lib/x86_64/$library"; done
java="$source/validation/network-profiles/native/android"
# Probe-only ABI shim: it drives the same libhp_tailscale.so through the
# plain C ABI, so the Go side is exercised without the Rust/JNI bridge.
ndk="${ANDROID_NDK_HOME:-${ANDROID_NDK_ROOT:-}}"
: "${ndk:?ANDROID_NDK_HOME or ANDROID_NDK_ROOT must be set}"
clang="$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/clang"
[[ -x "$clang" ]] || { echo "ndk clang missing" >&2; exit 1; }
"$clang" --target=x86_64-linux-android35 -shared -fPIC -O2 -std=gnu11 -Wall -Wextra -Werror \
  -I"$source/validation/native/tailscale-runtime" \
  -o "$tmp/apk/lib/x86_64/libabi_shim.so" "$here/abi_shim.c"
javac -source 11 -target 11 -Xlint:-options -classpath "$jar" -d "$tmp/classes" \
  "$here/NetworkRuntimeChannel.java" "$here/DirectoryProbe.java" "$here/ProbeInstrumentation.java" \
  "$here/AbiProbeInstrumentation.java" \
  "$java/AndroidTailscaleConfig.java" "$java/AndroidTailscaleStateStore.java" \
  "$java/AndroidTailscaleEnvelope.java" "$java/TailscaleStateStoreCore.java"
mapfile -t classes < <(find "$tmp/classes" -name '*.class' -type f)
java -cp "$tools/lib/d8.jar" com.android.tools.r8.D8 --lib "$jar" --min-api 35 --output "$tmp/dex" "${classes[@]}"
"$tools/aapt2" link -o "$tmp/base.apk" -I "$jar" --manifest "$here/AndroidManifest.xml" --min-sdk-version 35 --target-sdk-version 35
# Packaged digest of the exact libhp_tailscale.so the ABI leg must load, so
# the probe can prove the mapped symbol came from this artifact.
mkdir -p "$tmp/assets"
sha256sum "$tmp/apk/lib/x86_64/libhp_tailscale.so" | awk '{print $1}' > "$tmp/assets/hp-tailscale.sha256"
(cd "$tmp/dex" && zip -q -X "$tmp/base.apk" classes.dex)
(cd "$tmp/apk" && zip -q -X -r "$tmp/base.apk" lib)
(cd "$tmp/assets" && zip -q -X "$tmp/base.apk" hp-tailscale.sha256)
"$tools/zipalign" -p -f 4 "$tmp/base.apk" "$tmp/aligned.apk"
keytool -genkeypair -keystore "$tmp/debug.p12" -storetype PKCS12 -storepass synthetic-test -keypass synthetic-test \
  -alias probe -keyalg RSA -keysize 2048 -validity 2 -dname 'CN=Disposable TS node probe' -noprompt >/dev/null 2>&1
"$tools/apksigner" sign --ks "$tmp/debug.p12" --ks-pass pass:synthetic-test --key-pass pass:synthetic-test \
  --ks-key-alias probe --out "$out" "$tmp/aligned.apk"
"$tools/apksigner" verify "$out"
