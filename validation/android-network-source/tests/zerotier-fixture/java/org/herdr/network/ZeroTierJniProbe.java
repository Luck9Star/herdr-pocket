package org.herdr.network;

import android.app.KeyguardManager;
import android.content.Context;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.Security;
import java.util.Comparator;

/** Synthetic C ABI and fake AndroidKeyStore provider; never starts a node. */
public final class ZeroTierJniProbe {
    private static native boolean bind(Context context);
    private static native long acquire(String handle);
    private static native long acquireTimeout(String handle,int timeoutMs);
    private static native long owner(long session);
    private static native boolean retire(long session);
    private static native void stopResult(int code);
    private static native void startResult(int code);
    private static native void validatorResult(int code);
    private static native void generatorResult(int code);
    private static native void failMetadata(boolean value);
    private static native void failBeforeNative(boolean value);
    private static native void blockInit(boolean block);
    private static native boolean initEntered();
    private static int checks;
    private static void check(boolean value,String message) { if (!value) throw new AssertionError(message); checks++; }
    interface Attempt { void run() throws Exception; }
    private static void rejects(Attempt action,String message) throws Exception {
        try { action.run(); } catch(Exception expected) {checks++;return;} throw new AssertionError(message);
    }
    @SuppressWarnings("restricted")
    public static void main(String[] args) throws Exception {
        System.load(args[0]); Security.addProvider(new ZeroTierAndroidStoreTest.FakeProvider());
        Path directory=Files.createTempDirectory("zerotier-jni-probe-");
        try {
            KeyguardManager guard=new KeyguardManager(); Context context=new Context(directory.toFile(),guard);
            check(acquire("00000000-0000-4000-8000-000000000000")==0,"unbound source unavailable");
            AndroidZeroTierDeviceStore store=AndroidZeroTierNative.createStore(context);
            generatorResult(4); rejects(store::create,"native generator failure has no fallback");
            generatorResult(0); check(store.status()==null,"failed generation did not install identity");
            AndroidZeroTierDeviceStore.Device identity=store.create();
            check(bind(context) && bind(context),"application binding stable");
            check(!bind(new Context(directory.toFile(),new KeyguardManager())),"different application context cannot replace binding");
            validatorResult(4);
            rejects(store::status,"native validator unavailable is not missing");
            rejects(() -> store.beginDiscardUnreadable(identity.handle),"validator failure cannot authorize discard");
            validatorResult(0);
            guard.delayMillis=80;
            long beforeInit=acquireTimeout(identity.handle,20);
            guard.delayMillis=0;
            check(beforeInit<0 && owner(-beforeInit)==0,"deadline before native init retains cleanup reservation");
            check(retire(-beforeInit),"settled pre-init failure retires exact Java lease");
            check(store.status().handle.equals(identity.handle),"pre-init cleanup preserves identity");
            failMetadata(true); long uncertain=acquire(identity.handle); failMetadata(false);
            check(uncertain<0 && owner(-uncertain)==0,"JNI metadata exception retains original lease");
            rejects(() -> store.forget(identity.handle),"JNI exception cannot silently unlock vault");
            check(retire(-uncertain),"retirement recovers exact Java lease after JNI exception");
            failBeforeNative(true); long copyFailure=acquire(identity.handle); failBeforeNative(false);
            check(copyFailure<0 && owner(-copyFailure)==0,"JNI failure after callback claim retains reservation");
            rejects(() -> store.forget(identity.handle),"conversion failure retains vault until explicit retirement");
            check(retire(-copyFailure),"settled callback without native dispatch retires exact lease");
            long one=acquire(identity.handle),two=acquire(identity.handle);
            check(one>0 && two>0 && one!=two,"separate profile reservations");
            check(owner(one)==41 && owner(two)==41,"reservations share device owner");
            check(!retire(999999),"foreign reservation cannot retire the owner");
            rejects(() -> store.forget(identity.handle),"active device protects vault");
            check(retire(one),"first profile retires");
            check(!retire(one),"first reservation not reused");
            rejects(() -> store.forget(identity.handle),"remaining profile retains vault");
            stopResult(4); check(!retire(two),"native timeout retains exact reservation");
            rejects(() -> store.forget(identity.handle),"timeout retains vault");
            stopResult(0); check(retire(two),"last profile exact stop and release retires vault");
            long[] slots=new long[32];
            for(int i=0;i<slots.length;i++) { slots[i]=acquire(identity.handle); check(slots[i]>0,"reservation capacity accepts bounded owner"); }
            check(acquire(identity.handle)==0,"reservation capacity rejects overflow");
            for(long slot:slots) check(retire(slot),"bounded reservation retires exactly once");
            startResult(5); long failed=acquire(identity.handle);
            check(failed<0 && owner(-failed)==41,"failed native start retains original owner");
            rejects(() -> store.forget(identity.handle),"failed start retains vault");
            startResult(0); check(retire(-failed),"failed start owner explicitly retired");
            blockInit(true); final long[] late={0};
            Thread worker=new Thread(() -> late[0]=acquire(identity.handle)); worker.start();
            long limit=System.nanoTime()+java.util.concurrent.TimeUnit.SECONDS.toNanos(3);
            while(!initEntered() && System.nanoTime()<limit) Thread.yield();
            check(initEntered(),"native initialization entered");
            rejects(() -> store.forget(identity.handle),"blocked original init retains vault");
            check(acquire(identity.handle)==0,"concurrent reservation does not overtake pending initialization");
            blockInit(false); worker.join(3000);
            check(!worker.isAlive() && late[0]>0,"original initialization settled");
            check(retire(late[0]),"settled owner can retire exactly");
            store.forget(identity.handle);
            check(store.status()==null,"explicit forget works after exact retirement");
            System.out.println("PASS: "+checks+" JNI checks; synthetic engine and JVM Android stubs only");
        } finally {
            Security.removeProvider("AndroidKeyStore");
            try(java.util.stream.Stream<Path> paths=Files.walk(directory)) {
                paths.sorted(Comparator.reverseOrder()).forEach(path -> { try { Files.deleteIfExists(path); } catch(Exception error) { throw new RuntimeException(error); } });
            }
        }
    }
}
