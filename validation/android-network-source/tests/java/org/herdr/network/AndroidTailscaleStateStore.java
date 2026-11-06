package org.herdr.network;
import android.content.Context;
import java.util.*;
/** Synthetic vault for the JNI fixture; never linked into an application. */
final class AndroidTailscaleStateStore {
    static int calls, mode;
    static byte[] lastKey, lastValue, lastOutput;
    static final Map<List<Byte>,byte[]> values = new HashMap<>();
    static final class StateKeyNotFoundException extends Exception { }
    AndroidTailscaleStateStore(Context context) { }
    String runtimeDirectory(String profile, String handle) throws Exception { calls++; if(mode!=0) throw new Exception(); return "/private/tmp/herdr-tailscale-state-v1/runtime/"+handle; }
    static List<Byte> key(byte[] b) { List<Byte> k=new ArrayList<>(); for(byte x:b) k.add(x); return k; }
    byte[] readStateBytes(String profile, String handle, byte[] key) throws Exception {
        calls++; lastKey=key;
        if(mode==1) throw new Exception("synthetic");
        if(mode==2) return null;
        byte[] value=values.get(key(key)); if(value==null) throw new StateKeyNotFoundException();
        lastOutput=value.clone(); return lastOutput;
    }
    void writeStateBytes(String profile, String handle, byte[] key, byte[] value) throws Exception {
        calls++; lastKey=key; lastValue=value;
        if(mode==1) throw new Exception("synthetic");
        if(value==null) values.remove(key(key)); else values.put(key(key),value.clone());
    }
}
