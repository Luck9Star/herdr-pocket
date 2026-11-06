package dev.herdr.pocket;

/** Desktop JVM JNI fixture only. No Android classes, vault, engine or sockets. */
public final class NetworkRuntimeChannel {
    public static native long nativeCreateScope();
    public static native String nativeReserveOpen(long scope, String id);
    public static native Object[] nativeCall(long scope, String method, String json, byte[] payload);
    public static native String nativeCloseScope(long scope);
    private static int assertions;
    private static void check(boolean value) {
        assertions++;
        if (!value) throw new AssertionError("JNI fixture assertion " + assertions);
    }
    private static String call(long scope, String method, String json, byte[] payload) {
        Object[] reply = nativeCall(scope, method, json, payload);
        check(reply != null && reply.length == 2 && reply[0] instanceof String && reply[1] == null);
        return (String)reply[0];
    }
    private static void run() {
        long scope = nativeCreateScope();
        check(scope > 0);
        check(call(scope, "available", "{}", null).contains("\"available\":false"));
        check(call(scope, "available", "{}", null).contains("overlay_provider_unavailable"));
        check(call(0, "available", "{}", null).contains("network_scope_unavailable"));
        check(call(scope, "unknown", "{}", null).contains("invalid_network_request"));
        check(call(scope, "available", "{}", new byte[1]).contains("invalid_network_request"));
        check(call(scope, "streamWrite", "{}", new byte[65537]).contains("invalid_network_request"));
        check(call(scope, "nodeStatus", "{\"profileId\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\"}", null).contains("unavailable"));
        check(call(scope, "nodeStart", "{\"binding\":{\"profileId\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\",\"profileRevision\":7,\"networkName\":\"synthetic\",\"identityRef\":\"11111111-1111-4111-8111-111111111111\"},\"peers\":[\"tcp://synthetic.invalid:1\"]}", null).contains("overlay_provider_unavailable"));
        check(call(scope, "nodeStop", "{\"binding\":{\"profileId\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\",\"profileRevision\":7,\"networkName\":\"synthetic\",\"identityRef\":\"11111111-1111-4111-8111-111111111111\"}}", null).contains("\"state\":\"stopped\""));
        check(nativeReserveOpen(scope,"0").contains("network_open_id_invalid"));
        check(nativeReserveOpen(scope,"1").contains("\"reserved\":true"));
        check(nativeReserveOpen(scope,"1").contains("network_open_id_reused"));
        check(call(scope,"cancelOpen","{\"openId\":\"2\"}",null).contains("\"cancelled\":true"));
        check(nativeReserveOpen(scope,"2").contains("\"error\":\"cancelled\""));
        check(call(scope,"streamRead","{\"streamId\":\"not-a-native-handle\",\"maxBytes\":65537}",null).contains("invalid_network_request"));
        // Java null arguments and oversized metadata cannot leave a pending
        // exception that poisons the next otherwise valid JNI call.
        check(call(scope,"available",null,null).contains("invalid_network_request"));
        check(call(scope,"available","x".repeat(40001),null).contains("invalid_network_request"));
        check(call(scope,"available","{}",null).contains("\"ok\":true"));
        check(nativeCloseScope(scope).contains("\"closing\":true"));
        check(call(scope,"available","{}",null).contains("network_scope_unavailable"));
        long fresh = nativeCreateScope();
        check(fresh > scope);
        check(nativeCloseScope(fresh).contains("\"ok\":true"));
        System.out.println("Flutter network JNI fixture: " + assertions + " assertions passed");
    }
    public static void main(String[] args) throws Exception {
        System.load(args[0]);
        final Throwable[] error = new Throwable[1];
        Thread worker = new Thread(() -> {try {run();} catch (Throwable t) {error[0]=t;}},"fixture-native-worker");
        worker.start();worker.join();
        if (error[0]!=null) throw new AssertionError("JNI fixture failed",error[0]);
    }
}
