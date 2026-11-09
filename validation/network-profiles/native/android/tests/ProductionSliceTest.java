package org.herdr.network;

import java.util.Map;
import java.util.Set;

/** Runs against only the production slice: the JNI bridge class ships in the
 * slice but stays unbound without a host library, so no test fake store. */
 public final class ProductionSliceTest {
     public static void main(String[] args) throws Exception {
        Class.forName("org.herdr.network.AndroidZeroTierNative");
        try {
            AndroidZeroTierNative.createStore(null);
            throw new AssertionError("null-context bridge must reject");
        } catch (IllegalStateException expected) { }
        Map<String,Object> value=AndroidZeroTierDeviceService.status();
        if (!value.keySet().equals(Set.of("available","device","pendingCreation","pendingDeletion"))
            || !Boolean.FALSE.equals(value.get("available")) || value.get("device")!=null
            || value.get("pendingCreation")!=null || value.get("pendingDeletion")!=null)
            throw new AssertionError("unbound service must be precisely unavailable");
        String handle="11111111-1111-4111-8111-111111111111";
        String[][] requests={
            {"create",null,null,null}, {"forget",handle,handle,null},
            {"recoverPendingCreation",handle,null,"record-present"},
            {"discardPendingCreation",handle,null,"record-pending"},
            {"recoverPendingDeletion",handle,null,"record-removed"}
        };
        for (String[] request:requests) {
            try {
                AndroidZeroTierDeviceService.write(request[0],request[1],request[2],request[3]);
                throw new AssertionError("unbound mutation succeeded");
            } catch (IllegalStateException expected) {
                if (!"device store unavailable".equals(expected.getMessage())) throw expected;
            }
        }
        System.out.println("PASS production slice: JNI bridge present yet unbound; unavailable status and five mutations");
    }
}
