#!/bin/sh
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/tailscale-state-jvm.XXXXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
mkdir -p "$tmp/stub/android/content" "$tmp/stub/android/app" "$tmp/stub/android/os" "$tmp/stub/android/security/keystore" "$tmp/out"
cat > "$tmp/stub/android/content/Context.java" <<'JAVA'
package android.content;
import java.io.File;
public class Context {
    public Context getApplicationContext() { return this; }
    public <T> T getSystemService(Class<T> type) { return null; }
    public File getNoBackupFilesDir() { return null; }
}
JAVA
cat > "$tmp/stub/android/app/KeyguardManager.java" <<'JAVA'
package android.app;
public class KeyguardManager { public boolean isDeviceLocked() { return false; } }
JAVA
cat > "$tmp/stub/android/os/Build.java" <<'JAVA'
package android.os;
public class Build { public static class VERSION { public static int SDK_INT = 35; } }
JAVA
cat > "$tmp/stub/android/security/keystore/KeyProperties.java" <<'JAVA'
package android.security.keystore;
public class KeyProperties {
    public static final String KEY_ALGORITHM_AES="AES", BLOCK_MODE_GCM="GCM", ENCRYPTION_PADDING_NONE="NoPadding";
    public static final int PURPOSE_ENCRYPT=1, PURPOSE_DECRYPT=2;
}
JAVA
cat > "$tmp/stub/android/security/keystore/KeyGenParameterSpec.java" <<'JAVA'
package android.security.keystore;
import java.security.spec.AlgorithmParameterSpec;
public class KeyGenParameterSpec implements AlgorithmParameterSpec {
    public static class Builder {
        public Builder(String alias,int purpose) {}
        public Builder setKeySize(int size) { return this; }
        public Builder setBlockModes(String... value) { return this; }
        public Builder setEncryptionPaddings(String... value) { return this; }
        public Builder setRandomizedEncryptionRequired(boolean value) { return this; }
        public Builder setUnlockedDeviceRequired(boolean value) { return this; }
        public KeyGenParameterSpec build() { return new KeyGenParameterSpec(); }
    }
}
JAVA
javac -d "$tmp/out" \
  "$tmp/stub/android/content/Context.java" "$tmp/stub/android/app/KeyguardManager.java" "$tmp/stub/android/os/Build.java" \
  "$tmp/stub/android/security/keystore/KeyProperties.java" "$tmp/stub/android/security/keystore/KeyGenParameterSpec.java" \
  "$here/../../../android-network-source/tests/java/android/os/Process.java" \
  "$here/../../../android-network-source/tests/java/android/system/StructStat.java" \
  "$here/../../../android-network-source/tests/java/android/system/Os.java" \
  "$here/../../../android-network-source/tests/java/android/system/OsConstants.java" \
  "$here/TailscaleStateStoreCore.java" "$here/AndroidTailscaleEnvelope.java" "$here/AndroidTailscaleStateStore.java" "$here/AndroidTailscaleConfig.java" \
  "$here/tests/TailscaleStateStoreCoreTest.java" "$here/tests/TailscaleStateStoreSurfaceTest.java"
java -cp "$tmp/out" org.herdr.network.TailscaleStateStoreCoreTest
java -cp "$tmp/out" org.herdr.network.TailscaleStateStoreSurfaceTest
