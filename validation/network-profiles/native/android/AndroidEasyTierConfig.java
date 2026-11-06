package org.herdr.network;

import android.content.Context;

/** JNI-only entry point. Never register this method with Dart, JS, or another GUI bridge. */
public final class AndroidEasyTierConfig {
    private AndroidEasyTierConfig() {}
    /** Host plugin registers an application Context after loading its native library.
     * The Rust binding owns the JNI implementation; this class does not load a library.
     */
    public static native boolean bindNative(Context context);
    /** The native caller owns this secret-bearing buffer and must clear it promptly. */
    public static byte[] load(Context context, String profileId, String expectedHandle,
                              String networkName, String[] peers) throws Exception {
        return new AndroidNetworkSecretStore(context).easyTierConfig(profileId, expectedHandle, networkName, peers);
    }
}
