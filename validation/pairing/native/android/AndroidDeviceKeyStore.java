package org.herdr.pairing;

import android.content.Context;
import android.app.KeyguardManager;
import android.os.Build;

/** Shared Flutter/Tauri native facade: handles/public data/signatures only. API 35. */
public final class AndroidDeviceKeyStore {
    public static final int MAX_MESSAGE_BYTES = Ed25519Operations.MAX_MESSAGE_BYTES;
    public static final class CreatedKey {
        public final String handle;
        public final String publicKey;
        CreatedKey(String handle, String publicKey) { this.handle = handle; this.publicKey = publicKey; }
    }
    private final DeviceKeyStoreCore core;
    private final KeyguardManager keyguard;
    public AndroidDeviceKeyStore(Context context) throws Exception {
        if (Build.VERSION.SDK_INT < 35) throw new UnsupportedOperationException("Device signing requires API 35");
        if (context == null) throw new IllegalArgumentException("application context required");
        Context application = context.getApplicationContext();
        keyguard = application.getSystemService(KeyguardManager.class);
        if (keyguard == null) throw new IllegalStateException("device lock state unavailable");
        core = new DeviceKeyStoreCore(application.getNoBackupFilesDir().toPath(), new AndroidSeedEnvelope());
    }
    private void requireUnlocked() {
        if (keyguard.isDeviceLocked()) throw new IllegalStateException("device locked; unlock explicitly");
    }
    public CreatedKey create() throws Exception {
        requireUnlocked();
        DeviceKeyStoreCore.Created created = core.create();
        return new CreatedKey(created.handle, created.publicKey);
    }
    public String publicKey(String handle) throws Exception { requireUnlocked(); return core.publicKey(handle); }
    public byte[] sign(String handle, byte[] message) throws Exception { requireUnlocked(); return core.sign(handle, message); }
    public void delete(String handle) throws Exception { core.delete(handle); }
}
