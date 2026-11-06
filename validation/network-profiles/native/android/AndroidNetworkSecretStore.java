package org.herdr.network;

import android.app.KeyguardManager;
import android.content.Context;
import android.os.Build;

/** Public bridge surface: create, verified status, and delete; no secret export. Blocking IO. */
public final class AndroidNetworkSecretStore {
    public static final int MAX_SECRET_BYTES = NetworkSecretStoreCore.MAX_SECRET_BYTES;
    public enum SecretMode { PRIVATE, PUBLIC_NO_SECRET }
    public static final class Result {
        public final String profileId, provider, handle, instanceId;
        public final SecretMode mode;
        private Result(NetworkSecretStoreCore.Result value) {
            profileId = value.profileId; provider = value.provider; handle = value.handle;
            instanceId = value.instanceId; mode = value.publicNetwork ? SecretMode.PUBLIC_NO_SECRET : SecretMode.PRIVATE;
        }
    }
    private final NetworkSecretStoreCore core;
    private final KeyguardManager keyguard;
    public AndroidNetworkSecretStore(Context context) throws Exception {
        if (Build.VERSION.SDK_INT < 35) throw new UnsupportedOperationException("API 35 required");
        if (context == null) throw new IllegalArgumentException("application context required");
        Context app = context.getApplicationContext();
        keyguard = app.getSystemService(KeyguardManager.class);
        if (keyguard == null) throw new IllegalStateException("device lock state unavailable");
        core = new NetworkSecretStoreCore(app.getNoBackupFilesDir().toPath(), new AndroidNetworkEnvelope());
    }
    private void requireUnlocked() {
        if (keyguard.isDeviceLocked()) throw new IllegalStateException("device locked; unlock explicitly");
    }
    /** The caller owns and must clear the input array after this call. */
    public Result create(String profileId, String provider, SecretMode mode, byte[] secret) throws Exception {
        requireUnlocked();
        if (mode == null) throw new IllegalArgumentException("explicit secret mode required");
        return new Result(core.create(profileId, provider, mode == SecretMode.PUBLIC_NO_SECRET, secret));
    }
    /** Null means no record. Missing keys, corruption and locked state are errors. */
    public Result status(String profileId, String provider) throws Exception {
        requireUnlocked();
        NetworkSecretStoreCore.Result value = core.status(profileId, provider);
        return value == null ? null : new Result(value);
    }
    public void delete(String profileId, String provider, String handle) throws Exception {
        requireUnlocked(); core.delete(profileId, provider, handle);
    }
    // Only same-package native network adapters may call this; never expose it through a GUI bridge.
    interface SecretOperation { void run(byte[] secret) throws Exception; }
    void withSecret(String profileId, String provider, String handle, SecretOperation operation) throws Exception {
        requireUnlocked();
        if (operation == null) throw new IllegalArgumentException("operation required");
        core.withSecret(profileId, provider, handle, operation::run);
    }
}
