#!/usr/bin/env bash
# Build and run the real system AndroidKeyStore verification of the production
# ZeroTier device identity store. No JCE provider is registered: the platform
# provider must resolve "AndroidKeyStore" on its own, exactly as inside a
# shipped app. Needs a connected API 35+ device or emulator.
#
# The emulator runs a software KeyMint. This script proves the provider path
# only; it never establishes a TEE, StrongBox or hardware-isolation claim.
set -euo pipefail

here=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
sdk=${ANDROID_HOME:-}
serial=${ANDROID_SERIAL:-emulator-5554}
output=
package=org.herdr.network.zerotierkeystore.test
runner=org.herdr.network.ZeroTierAndroidKeyStoreInstrumentation

usage() {
    cat <<'EOF'
Usage: run-zerotier-keystore-instrumented.sh [--sdk DIR] [--serial SERIAL] [--output DIR]

  --sdk DIR      Android SDK root (default: $ANDROID_HOME)
  --serial ID    adb device serial (default: $ANDROID_SERIAL or emulator-5554)
  --output DIR   directory for the evidence JSON and the raw instrument output
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --sdk) sdk=$2; shift 2 ;;
        --serial) serial=$2; shift 2 ;;
        --output) output=$2; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done
[ -n "$sdk" ] || { echo 'no Android SDK: pass --sdk or set ANDROID_HOME' >&2; exit 1; }
[ -n "$output" ] || { echo 'no output directory: pass --output' >&2; exit 1; }
mkdir -p "$output"
output=$(CDPATH= cd -- "$output" && pwd)

for tool in javac java keytool python3 zip; do
    command -v "$tool" >/dev/null 2>&1 || { echo "missing tool: $tool" >&2; exit 1; }
done

jar="$sdk/platforms/android-35/android.jar"
[ -f "$jar" ] || { echo "missing API 35 platform: $jar" >&2; exit 1; }
build_tools=$(ls -1d "$sdk"/build-tools/* 2>/dev/null | sort -V | tail -1 || true)
[ -n "$build_tools" ] || { echo "no build-tools under $sdk" >&2; exit 1; }
for tool in d8 aapt2 zipalign apksigner; do
    [ -x "$build_tools/$tool" ] || { echo "missing build tool: $build_tools/$tool" >&2; exit 1; }
done

manifest="$here/android-production-sources.txt"
# Exactly the manifest-listed production files this instrumented run exercises.
sources=(ZeroTierDeviceStoreCore.java AndroidZeroTierEnvelope.java AndroidZeroTierDeviceStore.java)
for name in "${sources[@]}"; do
    grep -qx "$name" "$manifest" || { echo "not in production manifest: $name" >&2; exit 1; }
done

tmp=$(mktemp -d "${TMPDIR:-/tmp}/zerotier-keystore.XXXXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

# 1. Production slice, then the instrumented sources against the real android.jar.
mkdir -p "$tmp/classes"
javac -nowarn -source 11 -target 11 -Xlint:-options -classpath "$jar" -d "$tmp/classes" \
    "${sources[@]/#/$here/}" || { echo 'production slice failed to compile' >&2; exit 1; }
javac -Xlint:all,-options -Werror -source 11 -target 11 -classpath "$jar:$tmp/classes" \
    -d "$tmp/classes" \
    "$here/tests/instrumented/src/org/herdr/network/ZeroTierAndroidKeyStoreTest.java" \
    "$here/tests/instrumented/src/org/herdr/network/ZeroTierAndroidKeyStoreInstrumentation.java" \
    || { echo 'instrumented sources failed to compile' >&2; exit 1; }

# 2. Package a self-targeting instrumented APK without Gradle.
java -cp "$build_tools/lib/d8.jar" com.android.tools.r8.D8 --lib "$jar" --min-api 35 \
    --output "$tmp/dex" "$tmp/classes" || { echo 'dexing failed' >&2; exit 1; }
"$build_tools/aapt2" link -o "$tmp/base.apk" -I "$jar" \
    --manifest "$here/tests/instrumented/AndroidManifest.xml" \
    --min-sdk-version 35 --target-sdk-version 35 || { echo 'aapt2 link failed' >&2; exit 1; }
(cd "$tmp/dex" && zip -q -X "$tmp/base.apk" classes.dex) || { echo 'dex packaging failed' >&2; exit 1; }
"$build_tools/zipalign" -p -f 4 "$tmp/base.apk" "$tmp/aligned.apk" || { echo 'zipalign failed' >&2; exit 1; }
password=herdr-keystore-test
keytool -genkeypair -keystore "$tmp/debug.p12" -storetype PKCS12 -storepass "$password" \
    -keypass "$password" -alias herdr-keystore -keyalg RSA -keysize 2048 -validity 10000 \
    -dname 'CN=herdr keystore instrumented test' -noprompt >/dev/null 2>&1 \
    || { echo 'debug keystore generation failed' >&2; exit 1; }
"$build_tools/apksigner" sign --ks "$tmp/debug.p12" --ks-pass "pass:$password" \
    --key-pass "pass:$password" --ks-key-alias herdr-keystore --out "$tmp/app.apk" "$tmp/aligned.apk" \
    || { echo 'apksigner failed' >&2; exit 1; }
"$build_tools/apksigner" verify --verbose "$tmp/app.apk" > "$output/apksigner-verify.txt" 2>&1 \
    || { echo 'apksigner verify failed' >&2; exit 1; }

# 3. Install on the owned device and run the instrumentation.
adb -s "$serial" wait-for-device
sdk_level=$(adb -s "$serial" shell getprop ro.build.version.sdk | tr -d '\r')
[ "$sdk_level" -ge 35 ] || { echo "device API $sdk_level is below the required 35" >&2; exit 1; }
instrument_status=0
run_instrumentation() {
    local mode=$1
    # A rerun must start from a clean app: the store refuses a second identity.
    adb -s "$serial" uninstall "$package" >/dev/null 2>&1 || true
    adb -s "$serial" install -r -t "$tmp/app.apk" > "$output/adb-install.txt" 2>&1 || return 1
    set +e
    adb -s "$serial" shell am instrument -w $mode "$package/$runner" > "$output/instrumentation-output.txt" 2>&1
    instrument_status=$?
    set -e
    grep -q 'HERDR_KEYSTORE_RESULT' "$output/instrumentation-output.txt"
}
# Raw output is the protocol verbatim; the default rendering is the fallback.
run_instrumentation -r || run_instrumentation ''
if ! grep -q 'HERDR_KEYSTORE_RESULT PASS' "$output/instrumentation-output.txt"; then
    echo 'instrumented system KeyStore verification did not pass' >&2
    tail -40 "$output/instrumentation-output.txt" >&2
    exit 1
fi
[ "$instrument_status" -eq 0 ] || echo "note: am instrument exit status $instrument_status with a PASS marker" >&2
adb -s "$serial" uninstall "$package" >/dev/null 2>&1 || true

python3 - "$output" "$serial" "$sdk_level" "$here" "$manifest" <<'PY'
import hashlib, json, pathlib, sys

output, serial, sdk_level, here, manifest = sys.argv[1:6]
output = pathlib.Path(output)
text = (output / 'instrumentation-output.txt').read_text()
device = None
marker = 'HERDR_KEYSTORE_EVIDENCE '
if marker in text:
    payload = text[text.index(marker) + len(marker):]
    device = json.loads(payload[payload.index('{'):payload.rindex('}') + 1])
if not device:
    raise SystemExit('no evidence payload in the instrumentation output')
here = pathlib.Path(here)
manifest = pathlib.Path(manifest)
listed = [line for line in manifest.read_text().splitlines() if line.strip()]
report = {
    'passed': bool(device.get('passed')),
    'scope': 'instrumented run on the platform AndroidKeyStore; no registered test provider',
    'androidAbi': device['androidAbi'],
    'androidSdkInt': int(sdk_level),
    'fakeAndroidKeyStore': False,
    'keyStoreProviderClass': device['keyStoreProviderClass'],
    'encryptedAtRest': device['encryptedAtRest'],
    'nonExportableKey': device['nonExportableKey'],
    'hardwareBacked': device['hardwareBacked'],
    'hardwareIsolationClaimed': False,
    'freshReaderMatched': device['freshReaderMatched'],
    'identityDigestMatched': device['identityDigestMatched'],
    'wrongAadRejected': device['wrongAadRejected'],
    'tamperRejected': device['tamperRejected'],
    'wrongInstanceRejected': device['wrongInstanceRejected'],
    'explicitlyRemoved': device['explicitlyRemoved'],
    'keyStoreEmpty': device['keyStoreEmpty'],
    'checks': device['checks'],
    'deviceSerial': serial,
    'instrumentation': 'org.herdr.network.zerotierkeystore.test/org.herdr.network.ZeroTierAndroidKeyStoreInstrumentation',
    'productionManifest': manifest.name,
    'productionSources': {
        name: hashlib.sha256((here / name).read_bytes()).hexdigest()
        for name in listed if name in ('ZeroTierDeviceStoreCore.java',
                                       'AndroidZeroTierEnvelope.java',
                                       'AndroidZeroTierDeviceStore.java')
    },
    'boundary': ('An emulator runs a software KeyMint: this run proves the platform provider path, '
                 'not hardware isolation, TEE or StrongBox backing, and not lockscreen or '
                 'process-restart behaviour of a physical device.'),
}
(output / 'zerotier-android-keystore.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
PY
