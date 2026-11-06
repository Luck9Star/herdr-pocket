#!/bin/sh
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
root=$(CDPATH= cd -- "$here/../.." && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/tailscale-jni.XXXXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
cargo build --locked --offline --manifest-path "$here/Cargo.toml" --features jvm-fixture --target-dir "$tmp/target"
case $(uname -s) in
 Darwin) library="$tmp/target/debug/libherdr_android_network_source.dylib" ;;
 Linux) library="$tmp/target/debug/libherdr_android_network_source.so" ;;
 *) exit 2 ;;
esac
javac -d "$tmp/classes" "$here/tests/java/android/content/Context.java" \
 "$here/tests/java/android/os/Process.java" "$here/tests/java/android/system/StructStat.java" \
 "$here/tests/java/android/system/Os.java" "$here/tests/java/android/system/OsConstants.java" \
 "$here/tests/java/org/herdr/network/AndroidTailscaleStateStore.java" \
 "$root/validation/network-profiles/native/android/AndroidTailscaleConfig.java" \
 "$here/tests/java/org/herdr/network/TailscaleSourceFixture.java"
java -Xcheck:jni -cp "$tmp/classes" org.herdr.network.TailscaleSourceFixture "$library"
