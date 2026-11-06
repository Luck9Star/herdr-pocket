package org.herdr.network;
import android.content.Context;
import java.nio.charset.StandardCharsets;
/** Synthetic native-only callback; does not access production vaults. */
public final class AndroidEasyTierConfig {
    static byte[] last;
    static int mode, calls;
    public static native boolean bindNative(Context context);
    public static byte[] load(Context context,String profile,String handle,String network,String[] peers) {
        if (Thread.currentThread().getName().equals("main")) throw new IllegalStateException("worker required");
        if (context==null || !profile.equals("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") ||
            !handle.equals("11111111-1111-4111-8111-111111111111") || !network.equals("fixture") ||
            peers.length!=1 || !peers[0].equals("tcp://node.invalid:11010")) throw new IllegalArgumentException("binding mismatch");
        calls++;
        last=null;
        switch(mode) {
            case 1: throw new IllegalStateException("synthetic sensitive exception must never be logged");
            case 2: last=new byte[]{'a',0,'b'}; break;
            case 3: last=new byte[65537]; java.util.Arrays.fill(last,(byte)42); break;
            case 4: return null;
            case 5: last=new byte[0]; break;
            case 6: last=new byte[]{(byte)0xff}; break;
            default: last="[network_identity]\nnetwork_name=\"fixture\"\nnetwork_secret=\"synthetic-only\"\n".getBytes(StandardCharsets.UTF_8);
        }
        return last;
    }
}
