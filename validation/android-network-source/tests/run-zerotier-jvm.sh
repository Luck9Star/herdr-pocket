#!/bin/sh
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
validation=$(CDPATH= cd -- "$here/.." && pwd)
android="$validation/network-profiles/native/android"
tmp=$(mktemp -d "${TMPDIR:-/tmp}/zerotier-jni-jvm.XXXXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
mkdir -p "$tmp/src"
cat > "$tmp/Cargo.toml" <<EOF
[package]
name = "zerotier-jni-fixture"
version = "0.1.0"
edition = "2024"
[lib]
crate-type = ["cdylib"]
[features]
jvm-fixture = []
[dependencies]
jni = "=0.21.1"
zeroize = "=1.9.1"
overlay-runtime = { package = "herdr-overlay-runtime-probe", path = "$validation/overlay-runtime" }
EOF
printf '#[path="%s"]\nmod fixture;\n' "$here/tests/zerotier-fixture/src/lib.rs" > "$tmp/src/lib.rs"
cargo build --offline --features jvm-fixture --manifest-path "$tmp/Cargo.toml" --target-dir "$tmp/target"
case $(uname -s) in
 Darwin) library="$tmp/target/debug/libzerotier_jni_fixture.dylib" ;;
 Linux) library="$tmp/target/debug/libzerotier_jni_fixture.so" ;;
 *) exit 2 ;;
esac
javac -Xlint:all -Werror -d "$tmp/classes" \
 "$android/tests/zerotier-stubs/android/app/KeyguardManager.java" \
 "$android/tests/zerotier-stubs/android/content/Context.java" \
 "$android/tests/zerotier-stubs/android/os/Build.java" \
 "$android/tests/zerotier-stubs/android/security/keystore/KeyProperties.java" \
 "$android/tests/zerotier-stubs/android/security/keystore/KeyGenParameterSpec.java" \
 "$android/ZeroTierDeviceStoreCore.java" "$android/AndroidZeroTierEnvelope.java" \
 "$android/AndroidZeroTierDeviceStore.java" "$android/AndroidZeroTierDeviceService.java" "$android/AndroidZeroTierNative.java" \
 "$android/tests/ZeroTierAndroidStoreTest.java" \
 "$here/tests/zerotier-fixture/java/org/herdr/network/ZeroTierJniProbe.java"
java -Xcheck:jni -cp "$tmp/classes" org.herdr.network.ZeroTierJniProbe "$library"
