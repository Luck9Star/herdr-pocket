package org.herdr.network;

import java.util.Arrays;

/** Test-only JNI factory. Not a product binding or a native-owner implementation. */
final class IdentityBridge implements AndroidZeroTierDeviceStore.IdentityFactory {
    static { System.load(System.getProperty("hp.identity.library")); }
    private static native byte[] create();
    private static native boolean validateBytes(byte[] value);
    private byte[] lastGenerated;
    int creates, validations;
    public byte[] generate() {
        creates++;
        lastGenerated = create();
        return lastGenerated;
    }
    public boolean validate(byte[] value) {
        if (value != null && value.length == 270) validations++;
        return validateBytes(value);
    }
    boolean generatedBufferCleared() {
        if (lastGenerated == null || lastGenerated.length != 270) return false;
        for (byte value : lastGenerated) if (value != 0) return false;
        return true;
    }
    void clear() { if (lastGenerated != null) Arrays.fill(lastGenerated,(byte)0); }
}
