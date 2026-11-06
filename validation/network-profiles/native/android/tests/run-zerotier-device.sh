#!/bin/sh
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/zerotier-device-jvm.XXXXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
javac -d "$tmp/classes" "$here/ZeroTierDeviceStoreCore.java" "$here/tests/ZeroTierDeviceStoreCoreTest.java"
java -cp "$tmp/classes" org.herdr.network.ZeroTierDeviceStoreCoreTest
