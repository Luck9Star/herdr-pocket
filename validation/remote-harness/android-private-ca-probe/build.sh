#!/usr/bin/env bash
# Build a disposable self-targeting API35 x86_64 probe, never a product APK.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
: "${ANDROID_HOME:?}" "${RUNNER_TEMP:?}"
[[ ${GITHUB_ACTIONS:-} = true && ${GITHUB_REF:-} = refs/heads/codex/* ]]
out=${1:?output APK required}
root=$(python3 -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).resolve())' "$RUNNER_TEMP")
out=$(python3 -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).resolve())' "$out")
case "$out" in "$root"/*) ;; *) exit 1 ;; esac
jar="$ANDROID_HOME/platforms/android-35/android.jar"
tools="$ANDROID_HOME/build-tools/35.0.0"
clang="$ANDROID_HOME/ndk/28.2.13676358/toolchains/llvm/prebuilt/linux-x86_64/bin/x86_64-linux-android35-clang"
[[ -f "$jar" && -x "$clang" && -x "$tools/aapt2" && -x "$tools/apksigner" && -x "$tools/zipalign" && -f "$tools/lib/d8.jar" ]]
tmp=$(mktemp -d "$RUNNER_TEMP/hp-tls-build-XXXXXX")
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/classes" "$tmp/dex" "$tmp/apk/lib/x86_64"
GOOS=android GOARCH=amd64 CGO_ENABLED=1 CC="$clang" GO111MODULE=off GOTOOLCHAIN=local \
  go build -buildmode=c-shared -o "$tmp/apk/lib/x86_64/libhptlsprobe.so" "$here/probe.go"
cp "$here/wrap.sh" "$tmp/apk/lib/x86_64/wrap.sh"
chmod 755 "$tmp/apk/lib/x86_64/wrap.sh"
javac -source 11 -target 11 -Xlint:-options -classpath "$jar" -d "$tmp/classes" "$here/ProbeInstrumentation.java"
java -cp "$tools/lib/d8.jar" com.android.tools.r8.D8 --lib "$jar" --min-api 35 --output "$tmp/dex" "$tmp/classes/org/herdr/tlsprobe/ProbeInstrumentation.class"
"$tools/aapt2" link -o "$tmp/base.apk" -I "$jar" --manifest "$here/AndroidManifest.xml" --min-sdk-version 35 --target-sdk-version 35
(cd "$tmp/dex" && zip -q -X "$tmp/base.apk" classes.dex)
(cd "$tmp/apk" && zip -q -X -r "$tmp/base.apk" lib)
"$tools/zipalign" -p -f 4 "$tmp/base.apk" "$tmp/aligned.apk"
keytool -genkeypair -keystore "$tmp/debug.p12" -storetype PKCS12 -storepass synthetic-test -keypass synthetic-test \
  -alias probe -keyalg RSA -keysize 2048 -validity 2 -dname 'CN=Disposable Android TLS probe' -noprompt >/dev/null 2>&1
"$tools/apksigner" sign --ks "$tmp/debug.p12" --ks-pass pass:synthetic-test --key-pass pass:synthetic-test \
  --ks-key-alias probe --out "$out" "$tmp/aligned.apk"
"$tools/apksigner" verify "$out"
