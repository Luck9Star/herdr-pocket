package org.herdr.network;

import android.app.KeyguardManager;
import android.content.Context;
import android.os.Build;
import android.security.keystore.KeyGenParameterSpec;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.Key;
import java.security.KeyStore;
import java.security.KeyStoreSpi;
import java.security.Provider;
import java.security.SecureRandom;
import java.security.Security;
import java.security.cert.Certificate;
import java.security.spec.AlgorithmParameterSpec;
import java.util.Arrays;
import java.util.Collections;
import java.util.Date;
import java.util.Enumeration;
import java.util.HashMap;
import java.util.Map;
import javax.crypto.KeyGenerator;
import javax.crypto.KeyGeneratorSpi;
import javax.crypto.SecretKey;

/** JVM simulation only: real wrapper/envelope, fake Android API/provider, synthetic identities. */
public final class ZeroTierAndroidStoreTest {
    private static int checks;
    private static void check(boolean value,String message) { if (!value) throw new AssertionError(message); checks++; }
    interface Attempt { void run() throws Exception; }
    private static void rejects(Attempt work,String message) throws Exception {
        try { work.run(); } catch (Exception expected) { checks++; return; }
        throw new AssertionError(message);
    }
    private static final Map<String,Key> KEYS=new HashMap<>();
    private static KeyGenParameterSpec lastSpec;
    private static boolean failGenerate;

    public static final class FakeProvider extends Provider {
        private static final long serialVersionUID=1L;
        FakeProvider() { super("AndroidKeyStore", "1", "isolated test provider");
            put("KeyStore.AndroidKeyStore",FakeStore.class.getName());
            put("KeyGenerator.AES",FakeGenerator.class.getName()); }
    }
    public static final class FakeStore extends KeyStoreSpi {
        public Key engineGetKey(String alias,char[] password) { return KEYS.get(alias); }
        public Certificate[] engineGetCertificateChain(String alias) { return null; }
        public Certificate engineGetCertificate(String alias) { return null; }
        public Date engineGetCreationDate(String alias) { return null; }
        public void engineSetKeyEntry(String alias,Key key,char[] password,Certificate[] chain) { KEYS.put(alias,key); }
        public void engineSetKeyEntry(String alias,byte[] key,Certificate[] chain) { throw new UnsupportedOperationException(); }
        public void engineSetCertificateEntry(String alias,Certificate cert) { throw new UnsupportedOperationException(); }
        public void engineDeleteEntry(String alias) { KEYS.remove(alias); }
        public Enumeration<String> engineAliases() { return Collections.enumeration(KEYS.keySet()); }
        public boolean engineContainsAlias(String alias) { return KEYS.containsKey(alias); }
        public int engineSize() { return KEYS.size(); }
        public boolean engineIsKeyEntry(String alias) { return KEYS.containsKey(alias); }
        public boolean engineIsCertificateEntry(String alias) { return false; }
        public String engineGetCertificateAlias(Certificate cert) { return null; }
        public void engineStore(OutputStream stream,char[] password) {}
        public void engineLoad(InputStream stream,char[] password) {}
    }
    public static final class FakeGenerator extends KeyGeneratorSpi {
        private KeyGenParameterSpec spec;
        protected void engineInit(SecureRandom random) { throw new UnsupportedOperationException(); }
        protected void engineInit(int size,SecureRandom random) { throw new UnsupportedOperationException(); }
        protected void engineInit(AlgorithmParameterSpec params,SecureRandom random) { spec=(KeyGenParameterSpec)params; lastSpec=spec; }
        protected SecretKey engineGenerateKey() {
            try {
                KeyGenerator generator=KeyGenerator.getInstance("AES","SunJCE"); generator.init(256);
                SecretKey key=generator.generateKey(); KEYS.put(spec.name,key);
                if (failGenerate) throw new IllegalStateException("synthetic generation failure");
                return key;
            } catch (Exception error) { throw new IllegalStateException(error); }
        }
    }
    private static final class Factory implements AndroidZeroTierDeviceStore.IdentityFactory {
        int generated; byte[] generatedBytes, validatedBytes;
        public byte[] generate() { generated++; generatedBytes=new byte[270]; Arrays.fill(generatedBytes,(byte)'X'); return generatedBytes; }
        public boolean validate(byte[] identity) { validatedBytes=identity; return identity.length==270 && identity[0]=='X'; }
    }
    private static boolean wiped(byte[] value) { if(value==null) return false; for(byte b:value) if(b!=0) return false; return true; }
    private static final class Owner implements AndroidZeroTierDeviceStore.NativeOwner {
        boolean allow; String handle,instance,lease;
        public boolean retireExact(String h,String i,String l) { return allow && h.equals(handle) && i.equals(instance) && l.equals(lease); }
        void bind(AndroidZeroTierDeviceStore.RuntimeLease value) { handle=value.device().handle; instance=value.device().instanceId; lease=value.leaseId(); }
    }
    public static void main(String[] args) throws Exception {
        Security.addProvider(new FakeProvider()); Path dir=Files.createTempDirectory("zerotier-android-stub-");
        try { run(dir); System.out.println("PASS: "+checks+" Android wrapper checks; JVM stubs and test JCE provider only"); }
        finally {
            Security.removeProvider("AndroidKeyStore");
            try(java.util.stream.Stream<Path> paths=Files.walk(dir)) {
                paths.sorted(java.util.Comparator.reverseOrder()).forEach(path -> { try { Files.deleteIfExists(path); } catch(Exception e) { throw new RuntimeException(e); } });
            }
        }
    }
    private static void run(Path dir) throws Exception {
        KeyguardManager guard=new KeyguardManager(); Context context=new Context(dir.toFile(),guard); Factory factory=new Factory(); Owner owner=new Owner();
        Build.VERSION.SDK_INT=34; rejects(() -> new AndroidZeroTierDeviceStore(context,factory,owner),"old API must fail"); Build.VERSION.SDK_INT=35;
        rejects(() -> new AndroidZeroTierDeviceStore(context,null,owner),"no factory must fail");
        rejects(() -> new AndroidZeroTierDeviceStore(context,factory,null),"no owner must fail");
        AndroidZeroTierDeviceStore store=new AndroidZeroTierDeviceStore(context,factory,owner);
        check(store.status()==null && factory.generated==0,"missing identity does not generate");
        guard.locked=true; rejects(store::create,"locked create denied"); check(factory.generated==0,"locked create did not generate"); guard.locked=false;
        AndroidZeroTierDeviceStore.Device device=store.create();
        check(wiped(factory.generatedBytes) && wiped(factory.validatedBytes),"native generator and validation arrays wiped");
        check(lastSpec.name.equals(ZeroTierDeviceStoreCore.alias(device.handle)) && lastSpec.size==256
            && lastSpec.purposes==3 && lastSpec.mode.equals("GCM") && lastSpec.padding.equals("NoPadding")
            && lastSpec.randomized && lastSpec.unlocked,"provider receives isolated alias and AES-GCM restrictions");
        byte[] state=Files.readAllBytes(dir.resolve("herdr-zerotier-device-v1/device.state"));
        check(!new String(state,java.nio.charset.StandardCharsets.ISO_8859_1).contains("X".repeat(32)),"disk does not contain synthetic identity");
        AndroidZeroTierEnvelope isolatedEnvelope=new AndroidZeroTierEnvelope();
        String deviceAlias=ZeroTierDeviceStoreCore.alias(device.handle);
        rejects(() -> isolatedEnvelope.create(deviceAlias,new byte[]{1},new byte[1]),"duplicate alias cannot replace existing key");
        check(store.status().handle.equals(device.handle),"duplicate alias preserved original key");
        byte[] encrypted=Arrays.copyOfRange(state,40,state.length);
        rejects(() -> isolatedEnvelope.open(deviceAlias,new byte[]{0},encrypted,value -> {}),"wrong AAD cannot decrypt");
        byte[] correctAad=("herdr-zerotier-device:1:"+device.handle).getBytes(java.nio.charset.StandardCharsets.US_ASCII);
        final byte[][] plaintext={null};
        rejects(() -> isolatedEnvelope.open(deviceAlias,correctAad,encrypted,value -> { plaintext[0]=value; throw new Exception("synthetic callback"); }),"backend callback error propagates");
        check(wiped(plaintext[0]),"backend plaintext wiped on callback error");
        AndroidZeroTierDeviceStore.RuntimeLease lease=store.acquire(device.handle); owner.bind(lease);
        AndroidZeroTierDeviceStore competitor=new AndroidZeroTierDeviceStore(context,factory,owner);
        rejects(() -> competitor.acquire(device.handle),"second wrapper cannot acquire live device");
        final byte[][] borrowed={null}; lease.initialize(identity -> borrowed[0]=identity);
        check(wiped(borrowed[0]),"initializer array wiped after synchronous return");
        rejects(() -> lease.initialize(identity -> {}),"initialization cannot repeat");
        rejects(() -> store.forget(device.handle),"live node holds device owner");
        rejects(lease::confirmDrained,"false native proof keeps owner");
        guard.locked=true; owner.allow=true; lease.confirmDrained(); guard.locked=false;
        check(store.status().handle.equals(device.handle),"retirement works while locked and retains device");
        AndroidZeroTierDeviceStore.RuntimeLease failing=store.acquire(device.handle); owner.bind(failing); owner.allow=false;
        final byte[][] failed={null}; rejects(() -> failing.initialize(identity -> { failed[0]=identity; throw new Exception("synthetic init"); }),"failed init surfaces error");
        check(wiped(failed[0]),"failed init array wiped"); rejects(() -> store.forget(device.handle),"failed init retains owner"); owner.allow=true; failing.confirmDrained();
        AndroidZeroTierDeviceStore second=new AndroidZeroTierDeviceStore(context,factory,owner);
        KEYS.remove(ZeroTierDeviceStoreCore.alias(device.handle));
        rejects(store::status,"missing key is not absence"); rejects(() -> store.forget(device.handle),"normal forget cannot skip decrypt");
        rejects(() -> second.beginDiscardUnreadable(device.handle),"new instance does not trust plaintext header");
        guard.locked=true; rejects(() -> store.beginDiscardUnreadable(device.handle),"locked device is not a discard authorization"); guard.locked=false;
        AndroidZeroTierDeviceStore.UnreadableReview review=store.beginDiscardUnreadable(device.handle);
        check(review.handle().equals(device.handle) && review.state().equals("unreadable"),"review only exposes public metadata");
        rejects(() -> second.confirmDiscardUnreadable(review),"review bound to original wrapper");
        store.confirmDiscardUnreadable(review); check(store.status()==null,"explicit confirmed discard removes unreadable identity");
        rejects(() -> store.confirmDiscardUnreadable(review),"review cannot be reused");
        check(factory.generated==1,"key loss did not silently create identity");
        AndroidZeroTierEnvelope envelope=new AndroidZeroTierEnvelope();
        rejects(() -> envelope.delete("other-provider-alias"),"alias cannot escape provider namespace");
        check(KEYS.isEmpty(),"explicit discard retired isolated key");
        failGenerate=true; rejects(store::create,"failed Android key creation is surfaced"); failGenerate=false;
        check(KEYS.isEmpty() && store.status()==null,"failed key generation cleans uncommitted alias and leaves no identity");
    }
}
