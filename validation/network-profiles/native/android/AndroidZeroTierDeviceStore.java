package org.herdr.network;

import android.app.KeyguardManager;
import android.content.Context;
import android.os.Build;

/**
 * Native manager surface. Keep one instance for the application lifetime.
 * No method here is a Flutter/Tauri channel or a license to export an identity.
 * All operations can block and must run off the UI thread.
 */
public final class AndroidZeroTierDeviceStore {
    /** Implement only with the vetted native identity ABI; no Java fallback. */
    public interface IdentityFactory {
        /** Returns canonical private identity bytes; ownership transfers to the store. */
        byte[] generate() throws Exception;
        /** Synchronous, non-retaining validation by the same vetted native ABI. */
        boolean validate(byte[] identity) throws Exception;
    }
    /** Native manager, not GUI: atomically retires the original node/attempt and all callbacks and streams.
     * A network leave, NODE_DOWN event, timeout or unknown result is never proof of retirement. */
    public interface NativeOwner {
        boolean retireExact(String handle,String instanceId,String leaseId) throws Exception;
    }
    /** Synchronous native init must copy the identity before returning and must not retain this Java array. */
    public interface NativeInitializer { void initialize(byte[] identity) throws Exception; }

    public static final class Device {
        public final String handle,instanceId;
        private Device(ZeroTierDeviceStoreCore.PublicRecord value) { handle=value.handle; instanceId=value.instanceId; }
    }
    public static final class Pending {
        public final String handle,phase;
        private Pending(String handle,String phase) { this.handle=handle; this.phase=phase; }
    }
    /** One data-lock snapshot; pending operations and an authenticated device are exclusive. */
    public static final class Snapshot {
        public final Device device;
        public final Pending pendingCreation,pendingDeletion;
        private Snapshot(ZeroTierDeviceStoreCore.Snapshot value) {
            device=value.device==null ? null : new Device(value.device);
            pendingCreation=value.creation==null ? null : new Pending(value.creation.handle,value.creation.phase);
            pendingDeletion=value.deletion==null ? null : new Pending(value.deletion.handle,value.deletion.phase);
        }
    }
    /** Native-only capability; show only handle and state to the user. */
    public static final class UnreadableReview {
        private final AndroidZeroTierDeviceStore store;
        private final ZeroTierDeviceStoreCore.UnreadableReview value;
        private UnreadableReview(AndroidZeroTierDeviceStore store,ZeroTierDeviceStoreCore.UnreadableReview value) {
            this.store=store; this.value=value;
        }
        public String handle() { return value.handle(); }
        public String state() { return value.state(); }
    }
    /** Never release this lease on timeout, GC, network leave, or an unknown result. */
    public final class RuntimeLease {
        private final ZeroTierDeviceStoreCore.RuntimeLease value;
        private RuntimeLease(ZeroTierDeviceStoreCore.RuntimeLease value) { this.value=value; }
        public Device device() { return new Device(value.identity); }
        /** Native-only ephemeral ID used to bind the owner's proof. */
        public String leaseId() { return value.leaseId(); }
        public void initialize(NativeInitializer initializer) throws Exception {
            if (initializer==null) throw new IllegalArgumentException("native initializer required");
            requireUnlocked(); value.withIdentity(initializer::initialize);
        }
        /** Must be called only after native stop; false/exception retains the owner lock. */
        public void confirmDrained() throws Exception { value.confirmDrained(); }
    }

    private final ZeroTierDeviceStoreCore core;
    private final ZeroTierDeviceStoreCore.IdentityFactory factory;
    private final ZeroTierDeviceStoreCore.DrainVerifier verifier;
    private final KeyguardManager keyguard;

    public AndroidZeroTierDeviceStore(Context context,IdentityFactory identityFactory,NativeOwner nativeOwner) throws Exception {
        if (Build.VERSION.SDK_INT<35) throw new UnsupportedOperationException("API 35 required");
        if (context==null || identityFactory==null || nativeOwner==null) throw new IllegalArgumentException("native owner and application context required");
        Context app=context.getApplicationContext();
        if (app==null) throw new IllegalStateException("application context unavailable");
        keyguard=app.getSystemService(KeyguardManager.class);
        if (keyguard==null || app.getNoBackupFilesDir()==null) throw new IllegalStateException("device storage unavailable");
        factory=new ZeroTierDeviceStoreCore.IdentityFactory() {
            public byte[] generate() throws Exception { return identityFactory.generate(); }
            public boolean validate(byte[] identity) throws Exception { return identityFactory.validate(identity); }
        };
        verifier=nativeOwner::retireExact;
        core=new ZeroTierDeviceStoreCore(app.getNoBackupFilesDir().toPath(),new AndroidZeroTierEnvelope());
    }
    private void requireUnlocked() { if (keyguard.isDeviceLocked()) throw new IllegalStateException("device locked"); }
    public Device create() throws Exception { requireUnlocked(); return new Device(core.create(factory)); }
    /** Null only for genuinely absent state; locked, missing key and corruption throw. */
    public Device status() throws Exception {
        requireUnlocked(); ZeroTierDeviceStoreCore.PublicRecord result=core.status(factory);
        return result==null ? null : new Device(result);
    }
    public Snapshot statusSnapshot() throws Exception { requireUnlocked(); return new Snapshot(core.snapshot(factory)); }
    public RuntimeLease acquire(String handle) throws Exception {
        requireUnlocked(); return new RuntimeLease(core.acquire(handle,factory,verifier));
    }
    public void forget(String handle) throws Exception { requireUnlocked(); core.forget(handle,factory); }
    /** First removal from a reviewed GUI; pending deletion is not implicitly resumed. */
    public void forgetExact(String handle,String instanceId) throws Exception {
        requireUnlocked(); core.forgetExact(handle,instanceId,factory);
    }
    public Pending pendingCreation() throws Exception {
        requireUnlocked(); ZeroTierDeviceStoreCore.PendingCreation value=core.pendingStatus();
        return value==null ? null : new Pending(value.handle,value.phase);
    }
    public Device recoverPendingCreation(String handle) throws Exception {
        requireUnlocked(); return new Device(core.recoverPendingCreate(handle,factory));
    }
    public void discardPendingCreation(String handle) throws Exception { requireUnlocked(); core.discardPendingCreate(handle); }
    public Device recoverPendingCreationExact(String handle,String expectedPhase) throws Exception {
        requireUnlocked(); return new Device(core.recoverPendingCreateExact(handle,expectedPhase,factory));
    }
    public void discardPendingCreationExact(String handle,String expectedPhase) throws Exception {
        requireUnlocked(); core.discardPendingCreateExact(handle,expectedPhase);
    }
    public void recoverPendingDeletion(String handle,String expectedPhase) throws Exception {
        requireUnlocked(); core.recoverPendingDeletion(handle,expectedPhase);
    }
    public Pending pendingDeletion() throws Exception {
        requireUnlocked(); ZeroTierDeviceStoreCore.PendingDeletion value=core.pendingDeletionStatus();
        return value==null ? null : new Pending(value.handle,value.phase);
    }
    /** The handle must have been authenticated by this instance before the record became unreadable. */
    public UnreadableReview beginDiscardUnreadable(String handle) throws Exception {
        requireUnlocked(); ZeroTierDeviceStoreCore.UnreadableReview result=core.beginDiscardUnreadable(handle,factory);
        requireUnlocked(); return new UnreadableReview(this,result);
    }
    public void confirmDiscardUnreadable(UnreadableReview review) throws Exception {
        requireUnlocked();
        if (review==null || review.store!=this) throw new IllegalArgumentException("invalid device review");
        core.confirmDiscardUnreadable(review.value);
    }
}
