package dev.herdr.pocket;

/** Uses the unchanged product JNI entry points from the fixed native bundle. */
public final class NetworkRuntimeChannel {
    public static native long nativeCreateScope();
    public static native Object[] nativeCall(long scope, String method, String json, byte[] payload);
    public static native String nativeCloseScope(long scope);
}
