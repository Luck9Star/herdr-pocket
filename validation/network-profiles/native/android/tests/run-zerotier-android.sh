#!/bin/sh
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/zerotier-android-jvm.XXXXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
javac -Xlint:all -Werror -d "$tmp/classes" \
    "$here/tests/zerotier-stubs/android/app/KeyguardManager.java" \
    "$here/tests/zerotier-stubs/android/content/Context.java" \
    "$here/tests/zerotier-stubs/android/os/Build.java" \
    "$here/tests/zerotier-stubs/android/security/keystore/KeyProperties.java" \
    "$here/tests/zerotier-stubs/android/security/keystore/KeyGenParameterSpec.java" \
    "$here/ZeroTierDeviceStoreCore.java" "$here/AndroidZeroTierEnvelope.java" \
    "$here/AndroidZeroTierDeviceStore.java" "$here/tests/ZeroTierAndroidStoreTest.java"
java -cp "$tmp/classes" org.herdr.network.ZeroTierAndroidStoreTest
