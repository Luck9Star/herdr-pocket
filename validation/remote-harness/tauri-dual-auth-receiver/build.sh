#!/usr/bin/env bash
set -euo pipefail
: "${ANDROID_HOME:?}" "${RUNNER_TEMP:?}"
[[ ${GITHUB_ACTIONS:-} = true && ${GITHUB_REF:-} = refs/heads/codex/* ]]
here=$(cd "$(dirname "$0")" && pwd)
out=${1:?output APK required}
case "$out" in "$RUNNER_TEMP"/*) ;; *) exit 1 ;; esac
tmp=$(mktemp -d "$RUNNER_TEMP/hp-auth-build-XXXXXX")
trap 'rm -rf "$tmp"' EXIT
sdk="$ANDROID_HOME/build-tools/35.0.0"
jar="$ANDROID_HOME/platforms/android-35/android.jar"
mkdir -p "$tmp/classes" "$tmp/dex"
javac -source 11 -target 11 -Xlint:-options -classpath "$jar" -d "$tmp/classes" "$here/AuthActivity.java"
java -cp "$sdk/lib/d8.jar" com.android.tools.r8.D8 --lib "$jar" --min-api 35 --output "$tmp/dex" "$tmp/classes/dev/herdrpocket/dualtestauth/AuthActivity.class"
"$sdk/aapt2" link -o "$tmp/base.apk" -I "$jar" --manifest "$here/AndroidManifest.xml" --min-sdk-version 35 --target-sdk-version 35
(cd "$tmp/dex" && zip -q -X "$tmp/base.apk" classes.dex)
"$sdk/zipalign" -f 4 "$tmp/base.apk" "$tmp/aligned.apk"
keytool -genkeypair -keystore "$tmp/debug.p12" -storetype PKCS12 -storepass synthetic-test -keypass synthetic-test -alias test -keyalg RSA -keysize 2048 -validity 2 -dname 'CN=Disposable dual overlay authorization' -noprompt >/dev/null 2>&1
"$sdk/apksigner" sign --ks "$tmp/debug.p12" --ks-pass pass:synthetic-test --key-pass pass:synthetic-test --ks-key-alias test --out "$out" "$tmp/aligned.apk"
"$sdk/apksigner" verify "$out"
