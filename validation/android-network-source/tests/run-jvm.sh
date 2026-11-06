#!/bin/sh
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/network-source-jvm.XXXXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
# Build outputs are scoped to this temporary fixture and removed on exit.
cargo build --locked --offline --manifest-path "$here/Cargo.toml" --features jvm-fixture --target-dir "$tmp/target"
case $(uname -s) in
  Darwin) library="$tmp/target/debug/libherdr_android_network_source.dylib" ;;
  Linux) library="$tmp/target/debug/libherdr_android_network_source.so" ;;
  *) echo 'JVM source harness supports macOS/Linux only' >&2; exit 2 ;;
esac
javac -d "$tmp/classes" "$here/tests/java/android/content/Context.java" "$here/tests/java/org/herdr/network/AndroidEasyTierConfig.java" "$here/tests/java/org/herdr/network/NetworkSourceFixture.java"
java -Xcheck:jni -cp "$tmp/classes" org.herdr.network.NetworkSourceFixture "$library"
