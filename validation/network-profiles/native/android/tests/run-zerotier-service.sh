#!/bin/sh
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/zerotier-service-jvm.XXXXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
javac -d "$tmp/classes" \
    "$here/tests/zerotier-stubs/android/app/KeyguardManager.java" \
    "$here/tests/zerotier-stubs/android/content/Context.java" \
    "$here/tests/zerotier-stubs/android/os/Build.java" \
    "$here/tests/zerotier-stubs/android/security/keystore/KeyProperties.java" \
    "$here/tests/zerotier-stubs/android/security/keystore/KeyGenParameterSpec.java" \
    "$here/ZeroTierDeviceStoreCore.java" \
    "$here/AndroidZeroTierEnvelope.java" \
    "$here/AndroidZeroTierDeviceStore.java" \
    "$here/AndroidZeroTierDeviceService.java" \
    "$here/tests/ZeroTierAndroidStoreTest.java" \
    "$here/tests/ZeroTierDeviceServiceTest.java"
java -cp "$tmp/classes" org.herdr.network.ZeroTierDeviceServiceTest uninstalled
java -cp "$tmp/classes" org.herdr.network.ZeroTierDeviceServiceTest installed
java -cp "$tmp/classes" org.herdr.network.ZeroTierDeviceServiceTest pending-recovery
java -cp "$tmp/classes" org.herdr.network.ZeroTierDeviceServiceTest pending-deletion-recovery
