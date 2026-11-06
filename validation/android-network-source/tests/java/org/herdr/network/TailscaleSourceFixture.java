package org.herdr.network;
import android.content.Context;
public final class TailscaleSourceFixture {
    static native int probe(int mode);
    static native boolean bindClass(Class<?> candidate, Context context);
    static int checks;
    static void check(boolean ok,String message) { if(!ok) throw new AssertionError(message); checks++; }
    static void wiped(byte[] bytes) { if(bytes!=null) for(byte b:bytes) check(b==0,"JNI buffer wiped"); }
    static final class OtherConfig {
        static String directory(Context c,String p,String h) { return "/private/tmp"; }
        static byte[] read(Context c,String p,String h,byte[] k) { return null; }
        static void write(Context c,String p,String h,byte[] k,byte[] v) { }
        static boolean isMissing(Throwable t) { return true; }
    }
    public static void main(String[] args) {
        System.load(args[0]);
        check(probe(6)==3,"unbound rejects");
        Context app=new Context();
        check(!AndroidTailscaleConfig.bindNative(null),"null rejects");
        check(AndroidTailscaleConfig.bindNative(app),"bind");
        check(AndroidTailscaleConfig.bindNative(app),"same binding");
        check(!AndroidTailscaleConfig.bindNative(new Context()),"other context rejects");
        check(!bindClass(OtherConfig.class,app),"other class rejects");
        int before=AndroidTailscaleStateStore.calls;
        check(probe(17)==0 && before==AndroidTailscaleStateStore.calls,"construct does not touch vault");
        for(int mode=2;mode<=5;mode++) check(probe(mode)==2,"stale spec "+mode);
        check(probe(13)==2,"other profile rejects");
        check(before==AndroidTailscaleStateStore.calls,"stale spec never touches vault");
        check(probe(1)==2 && AndroidTailscaleStateStore.calls==before+1,"new attempt rejected before vault");
        before=AndroidTailscaleStateStore.calls;
        check(probe(15)==0 && AndroidTailscaleStateStore.calls==before+2,"wrong fields and zero attempt do not claim; same attempt reusable");
        before=AndroidTailscaleStateStore.calls;
        check(probe(16)==0 && AndroidTailscaleStateStore.calls==before+1,"concurrent attempts only one binds");
        before=AndroidTailscaleStateStore.calls; AndroidTailscaleStateStore.mode=1;
        check(probe(18)==0 && AndroidTailscaleStateStore.calls==before+1,"failed first load still binds attempt");
        AndroidTailscaleStateStore.mode=0;
        check(probe(6)==0,"vetted directory");
        for(int i=0;i<4;i++) {
            android.system.Os.badIndex=i; android.system.Os.badUid=101;
            check(probe(14)==0,"wrong owner refuses "+i);
            android.system.Os.badUid=100; android.system.Os.badMode=0120777;
            check(probe(14)==0,"symlink refuses "+i);
            android.system.Os.badMode=0040700;
        }
        for(int i=1;i<4;i++) {
            android.system.Os.badIndex=i; android.system.Os.badMode=0040771;
            check(probe(14)==0,"broad private directory refuses "+i);
        }
        android.system.Os.badIndex=-1; android.system.Os.badMode=0040700;
        for(int mode=7;mode<=9;mode++) { check(probe(mode)==0,"state mode "+mode); wiped(AndroidTailscaleStateStore.lastKey); wiped(AndroidTailscaleStateStore.lastValue); wiped(AndroidTailscaleStateStore.lastOutput); }
        AndroidTailscaleStateStore.mode=1;
        check(probe(10)==0,"generic exception unavailable"); wiped(AndroidTailscaleStateStore.lastKey);
        AndroidTailscaleStateStore.mode=2;
        check(probe(10)==0,"null is unavailable");
        AndroidTailscaleStateStore.mode=0;
        before=AndroidTailscaleStateStore.calls;
        check(probe(11)==0 && before==AndroidTailscaleStateStore.calls,"bounds before vault");
        check(probe(12)==0,"1024 byte binary key"); wiped(AndroidTailscaleStateStore.lastKey); wiped(AndroidTailscaleStateStore.lastValue); wiped(AndroidTailscaleStateStore.lastOutput);
        System.out.println("Tailscale JNI fixture: "+checks+" checks passed; synthetic desktop JVM vault");
    }
}
