package org.herdr.network;
import android.content.Context;
public final class NetworkSourceFixture {
    static native int probe(int mode);
    static int checks;
    static void check(boolean value,String name) { if(!value) throw new AssertionError(name); checks++; }
    public static void main(String[] args) {
        System.load(args[0]);
        check(probe(0)==3,"no context refuses");
        Context app=new Context();
        check(!AndroidEasyTierConfig.bindNative(null),"null context refuses");
        check(AndroidEasyTierConfig.bindNative(app),"bind application");
        check(AndroidEasyTierConfig.bindNative(app),"same binding idempotent");
        check(!AndroidEasyTierConfig.bindNative(new Context()),"different context refuses");
        int previous=AndroidEasyTierConfig.calls;
        check(probe(1)==2,"stale config revision refuses");
        check(AndroidEasyTierConfig.calls==previous,"stale config never loads secret");
        for (int mode=0;mode<=6;mode++) {
            AndroidEasyTierConfig.mode=mode;
            check(probe(0)==(mode==0?0:1),"bounded native result "+mode);
            if(AndroidEasyTierConfig.last!=null) {
                for(byte b:AndroidEasyTierConfig.last) if(b!=0) throw new AssertionError("Java secret buffer retained");
                checks++;
            }
        }
        AndroidEasyTierConfig.mode=0;
        for(int i=0;i<32;i++) check(probe(0)==0,"worker attachment and local frame "+i);
        check(AndroidEasyTierConfig.bindNative(app),"Java exception was cleared");
        System.out.println("JNI source fixture: "+checks+" checks passed; synthetic desktop JVM only");
    }
}
