package org.herdr.network;

import android.app.KeyguardManager;
import android.content.Context;
import android.os.Build;

/** Public lifecycle surface exposes only local references. Blocking I/O. */
public final class AndroidTailscaleStateStore {
    public static final class Result {
        public final String profileId, provider = "tailscale", handle, instanceId;
        private Result(TailscaleStateStoreCore.Result result) {
            profileId = result.profileId; handle = result.handle; instanceId = result.instanceId;
        }
    }
    /** Only this exception represents an absent key inside a valid identity. */
    public static final class StateKeyNotFoundException extends Exception {
        private StateKeyNotFoundException() { super("state key not found"); }
    }
    private final TailscaleStateStoreCore core;
    private final KeyguardManager keyguard;
    public AndroidTailscaleStateStore(Context context) throws Exception {
        if (Build.VERSION.SDK_INT < 35) throw new UnsupportedOperationException("API 35 required");
        if (context == null) throw new IllegalArgumentException("application context required");
        Context app = context.getApplicationContext();
        keyguard = app.getSystemService(KeyguardManager.class);
        if (keyguard == null) throw new IllegalStateException("device lock state unavailable");
        core = new TailscaleStateStoreCore(app.getNoBackupFilesDir().toPath(),new AndroidTailscaleEnvelope());
    }
    private void requireUnlocked() {
        if (keyguard.isDeviceLocked()) throw new IllegalStateException("device locked");
    }
    public Result create(String profileId) throws Exception { requireUnlocked(); return new Result(core.create(profileId)); }
    /** Null means no identity; unavailable key, corrupt or unreadable data are errors. */
    public Result status(String profileId) throws Exception {
        requireUnlocked(); TailscaleStateStoreCore.Result result = core.status(profileId);
        return result == null ? null : new Result(result);
    }
    public void delete(String profileId,String handle) throws Exception { requireUnlocked(); core.delete(profileId,handle); }
    // JNI/native-only; never register these methods in a GUI method channel.
    // Native caller owns and must clear any returned byte array.
    byte[] readState(String profileId,String handle,String stateKey) throws Exception {
        requireUnlocked();
        try { return core.readState(profileId,handle,stateKey); }
        catch (TailscaleStateStoreCore.NotFound missing) { throw new StateKeyNotFoundException(); }
    }
    // null removes a key. A zero-length byte array persists as a present value.
    void writeState(String profileId,String handle,String stateKey,byte[] value) throws Exception {
        requireUnlocked(); core.writeState(profileId,handle,stateKey,value);
    }
    // State keys are opaque bytes; JNI caller owns the returned value.
    byte[] readStateBytes(String profileId,String handle,byte[] stateKey) throws Exception {
        requireUnlocked();
        try { return core.readStateBytes(profileId,handle,stateKey); }
        catch (TailscaleStateStoreCore.NotFound missing) { throw new StateKeyNotFoundException(); }
    }
    void writeStateBytes(String profileId,String handle,byte[] stateKey,byte[] value) throws Exception {
        requireUnlocked(); core.writeStateBytes(profileId,handle,stateKey,value);
    }
    String runtimeDirectory(String profileId,String handle) throws Exception {
        requireUnlocked(); return core.runtimeDirectory(profileId,handle);
    }
}
