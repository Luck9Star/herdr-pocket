package org.herdr.network;

import android.content.Context;

/** Native-only JNI bridge. The embedding host explicitly loads and binds the
 * pinned libraries; this class never loads a library or provides a fallback. */
public final class AndroidZeroTierNative {
    private AndroidZeroTierNative() { }
    // Hold the original capability even if JNI cannot create a global ref or
    // its caller drops an operation. It is cleared only after exact retirement.
    private static AndroidZeroTierDeviceStore.RuntimeLease retained;
    private static AndroidZeroTierDeviceStore originalStore;
    private static Context originalApplication;

    private static native byte[] identityCreate();
    private static native boolean identityValidate(byte[] identity);
    private static native int initializeDevice(long reservation,byte[] identity,int timeoutMs);
    private static native boolean retiredExactly(String handle,String instanceId,String leaseId);
    /** Host plugin calls this after explicitly loading the ZeroTier provider
     * library; it binds the store bridge and never loads a library itself. */
    public static native boolean bindNative(Context context);

    /** Invoked once by native binding on the application class-loader thread. */
    public static synchronized AndroidZeroTierDeviceStore createStore(Context context) throws Exception {
        Context app=context==null ? null : context.getApplicationContext();
        if (app==null || (originalApplication!=null && originalApplication!=app))
            throw new IllegalStateException("application binding changed");
        if (originalStore!=null) return originalStore;
        AndroidZeroTierDeviceStore store=new AndroidZeroTierDeviceStore(app,new AndroidZeroTierDeviceStore.IdentityFactory() {
            @Override public byte[] generate() {
                byte[] value=identityCreate();
                if (value==null) throw new IllegalStateException("native identity unavailable");
                return value;
            }
            @Override public boolean validate(byte[] identity) { return identityValidate(identity); }
        },AndroidZeroTierNative::retiredExactly);
        AndroidZeroTierDeviceService.install(store);
        originalStore=store; originalApplication=app;
        return store;
    }

    /** Synchronous native worker only. The store owns and wipes the borrowed bytes. */
    public static int initialize(AndroidZeroTierDeviceStore.RuntimeLease lease,long reservation,int timeoutMs) throws Exception {
        if (lease==null || reservation<=0 || timeoutMs<=0 || timeoutMs>60000)
            throw new IllegalArgumentException("invalid native admission");
        int[] result={-1};
        lease.initialize(identity -> result[0]=initializeDevice(reservation,identity,timeoutMs));
        return result[0];
    }

    public static synchronized AndroidZeroTierDeviceStore.RuntimeLease acquireRetained(
            AndroidZeroTierDeviceStore store,String handle) throws Exception {
        if (retained!=null) throw new IllegalStateException("device owner busy");
        retained=store.acquire(handle);
        return retained;
    }

    /** Native worker recovery after the original acquire call has settled. */
    public static synchronized AndroidZeroTierDeviceStore.RuntimeLease recoverRetained(String handle) {
        if (retained==null) return null;
        if (!retained.device().handle.equals(handle)) throw new IllegalStateException("device owner changed");
        return retained;
    }

    public static synchronized void confirmAndClear(AndroidZeroTierDeviceStore.RuntimeLease lease) throws Exception {
        if (lease==null || retained!=lease) throw new IllegalStateException("device owner changed");
        lease.confirmDrained();
        retained=null;
    }
}
