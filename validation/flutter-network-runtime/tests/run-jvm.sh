#!/bin/sh
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/flutter-network-jvm.XXXXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
target=${CARGO_TARGET_DIR:-/private/tmp/herdr-flutter-network-runtime-target}
cargo build --locked --offline --manifest-path "$here/Cargo.toml" --target-dir "$target"
case $(uname -s) in
  Darwin) library="$target/debug/libherdr_flutter_network_runtime.dylib" ;;
  Linux) library="$target/debug/libherdr_flutter_network_runtime.so" ;;
  *) echo 'JVM fixture supports macOS/Linux only' >&2; exit 2 ;;
esac
javac -d "$tmp/classes" "$here/tests/java/dev/herdr/pocket/NetworkRuntimeChannel.java"
java --enable-native-access=ALL-UNNAMED -Xcheck:jni -cp "$tmp/classes" dev.herdr.pocket.NetworkRuntimeChannel "$library"
