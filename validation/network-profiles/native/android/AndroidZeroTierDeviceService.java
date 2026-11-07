package org.herdr.network;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.locks.ReentrantLock;

/**
 * Public device metadata/operations shared by both Android GUI hosts.
 * This is an in-process facade, not an Android background Service. It never
 * loads native libraries, starts a node, exports identity bytes or retires a
 * live runtime lease. The host separately locks and validates its full catalog
 * review before calling write. All methods must run off the UI thread.
 */
public final class AndroidZeroTierDeviceService {
    private static final ReentrantLock OPERATION = new ReentrantLock();
    private static volatile AndroidZeroTierDeviceStore installed;
    private AndroidZeroTierDeviceService() { }

    /** Only the original native application binding may publish its exact store. */
    static synchronized void install(AndroidZeroTierDeviceStore store) {
        if (store==null || (installed!=null && installed!=store))
            throw new IllegalStateException("device store binding changed");
        installed=store;
    }
    private static void enter() {
        // Reject rather than queue behind a possibly unresolved storage call.
        if (OPERATION.isHeldByCurrentThread() || !OPERATION.tryLock())
            throw new IllegalStateException("device operation pending");
    }
    private static String uuid(String value) {
        if (value==null || !value.matches("[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}"))
            throw new IllegalArgumentException("invalid device reference");
        return value;
    }
    private static Map<String,String> device(AndroidZeroTierDeviceStore.Device value) {
        if (value==null) return null;
        Map<String,String> result=new LinkedHashMap<>();
        result.put("handle",uuid(value.handle)); result.put("instanceId",uuid(value.instanceId));
        return Collections.unmodifiableMap(result);
    }
    private static Map<String,String> pending(AndroidZeroTierDeviceStore.Pending value) {
        if (value==null) return null;
        Map<String,String> result=new LinkedHashMap<>();
        result.put("handle",uuid(value.handle)); result.put("phase",value.phase);
        return Collections.unmodifiableMap(result);
    }
    public static Map<String,Object> status() throws Exception {
        enter();
        try {
            AndroidZeroTierDeviceStore store=installed;
            AndroidZeroTierDeviceStore.Snapshot snapshot=store==null ? null : store.statusSnapshot();
            Map<String,Object> result=new LinkedHashMap<>();
            result.put("available",store!=null);
            result.put("device",snapshot==null ? null : device(snapshot.device));
            result.put("pendingCreation",snapshot==null ? null : pending(snapshot.pendingCreation));
            result.put("pendingDeletion",snapshot==null ? null : pending(snapshot.pendingDeletion));
            return Collections.unmodifiableMap(result);
        } finally { OPERATION.unlock(); }
    }
    private static void phase(String value,String... allowed) {
        for (String item:allowed) if (item.equals(value)) return;
        throw new IllegalArgumentException("invalid pending phase");
    }
    public static Map<String,String> write(String action,String handle,String instanceId,String expectedPhase) throws Exception {
        // Validate before storage. Null means absent, never an empty identifier.
        if (action==null) throw new IllegalArgumentException("invalid device action");
        switch (action) {
            case "create":
                if (handle!=null || instanceId!=null || expectedPhase!=null) throw new IllegalArgumentException("invalid create reference");
                break;
            case "forget":
                uuid(handle); uuid(instanceId);
                if (expectedPhase!=null) throw new IllegalArgumentException("invalid removal phase");
                break;
            case "recoverPendingCreation": case "discardPendingCreation": case "recoverPendingDeletion":
                uuid(handle);
                if (instanceId!=null) throw new IllegalArgumentException("invalid pending reference");
                if (action.equals("recoverPendingCreation")) phase(expectedPhase,"record-present","finishing");
                else if (action.equals("discardPendingCreation")) phase(expectedPhase,"record-pending","finishing");
                else phase(expectedPhase,"record-present","record-removed","finishing");
                break;
            default: throw new IllegalArgumentException("invalid device action");
        }
        enter();
        try {
            AndroidZeroTierDeviceStore store=installed;
            if (store==null) throw new IllegalStateException("device store unavailable");
            switch (action) {
                case "create": return device(store.create());
                case "forget": store.forgetExact(handle,instanceId); return null;
                case "recoverPendingCreation": return device(store.recoverPendingCreationExact(handle,expectedPhase));
                case "discardPendingCreation": store.discardPendingCreationExact(handle,expectedPhase); return null;
                case "recoverPendingDeletion": store.recoverPendingDeletion(handle,expectedPhase); return null;
                default: throw new IllegalStateException("invalid device action");
            }
        } finally { OPERATION.unlock(); }
    }
}
