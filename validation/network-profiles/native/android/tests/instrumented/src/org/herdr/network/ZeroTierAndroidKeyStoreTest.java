package org.herdr.network;

import android.content.Context;
import android.os.Build;
import android.security.keystore.KeyInfo;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.Key;
import java.security.KeyStore;
import java.security.MessageDigest;
import java.security.Provider;
import java.security.Security;
import java.util.Arrays;
import java.util.Enumeration;
import javax.crypto.SecretKey;
import javax.crypto.SecretKeyFactory;

/**
 * Real system AndroidKeyStore verification of the production ZeroTier device
 * identity store. Registers no JCE provider of its own: JCA must resolve
 * "AndroidKeyStore" to the platform provider, which is asserted first, so the
 * production envelope and storage core run exactly as they do inside a shipped
 * app. Needs an unlocked API 35+ device or emulator. An emulator's software
 * KeyMint proves the provider path only; {@code hardwareBacked} records the
 * measured {@link KeyInfo} answer and {@code hardwareIsolationClaimed} stays
 * false because this run can never establish a TEE/StrongBox conclusion.
 */
public final class ZeroTierAndroidKeyStoreTest {
    /** One line per event; the instrumentation maps this to status output. */
    public interface Report { void line(String message); }

    private static final String STORE_DIR="herdr-zerotier-device-v1";
    private static final String WRONG_INSTANCE="00000000-0000-4000-8000-000000000000";
    private static final int RECORD_BYTES=374, HEADER_BYTES=40;

    private static int checks;
    private static void check(boolean value,String message) {
        if (!value) throw new AssertionError(message);
        checks++;
    }
    private interface Attempt { void run() throws Exception; }
    /** True when the attempt was refused; a silent success is a test failure. */
    private static boolean rejects(Attempt work,String message) throws Exception {
        try { work.run(); } catch (Exception expected) { checks++; return true; }
        throw new AssertionError(message);
    }

    /** Fixed synthetic identity bytes; the vetted native identity ABI is out of scope here. */
    private static final class Factory implements AndroidZeroTierDeviceStore.IdentityFactory {
        int generated; byte[] digest;
        public byte[] generate() {
            generated++;
            byte[] identity=new byte[ZeroTierDeviceStoreCore.IDENTITY_BYTES];
            Arrays.fill(identity,(byte)'Z'); digest=sha(identity); return identity;
        }
        public boolean validate(byte[] identity) {
            return identity!=null && identity.length==ZeroTierDeviceStoreCore.IDENTITY_BYTES && identity[0]=='Z';
        }
    }
    private static final class Owner implements AndroidZeroTierDeviceStore.NativeOwner {
        boolean allow; String handle,instance,lease;
        public boolean retireExact(String handle,String instance,String lease) {
            return allow && handle.equals(this.handle) && instance.equals(this.instance) && lease.equals(this.lease);
        }
        void bind(AndroidZeroTierDeviceStore.RuntimeLease value) {
            handle=value.device().handle; instance=value.device().instanceId; lease=value.leaseId();
        }
    }

    private static byte[] sha(byte[] value) {
        try { return MessageDigest.getInstance("SHA-256").digest(value); }
        catch (Exception unavailable) { throw new IllegalStateException(unavailable); }
    }
    private static boolean contains(byte[] haystack,byte[] needle) {
        outer: for (int i=0;i<=haystack.length-needle.length;i++) {
            for (int j=0;j<needle.length;j++) if (haystack[i+j]!=needle[j]) continue outer;
            return true;
        }
        return false;
    }
    @SuppressWarnings("deprecation")
    private static Boolean hardwareBacked(SecretKey key) {
        try {
            SecretKeyFactory factory=SecretKeyFactory.getInstance(key.getAlgorithm(),"AndroidKeyStore");
            // The platform factory returns the generic KeySpec; the Android
            // implementation is the only provider that can supply a KeyInfo.
            java.security.spec.KeySpec spec=factory.getKeySpec(key,KeyInfo.class);
            if (!(spec instanceof KeyInfo)) return null;
            return Boolean.valueOf(((KeyInfo)spec).isInsideSecureHardware());
        } catch (Exception unavailable) { return null; }
    }
    private static String quote(String value) {
        return value.replace("\\","\\\\").replace("\"","\\\"");
    }
    private static String evidenceJson(int count,String abi,int sdkInt,String providerClass,
            boolean nonExportable,Boolean hardwareBacked,boolean freshReader,boolean identityMatched,
            boolean wrongAad,boolean tamperRejected,boolean wrongInstance,boolean removed,boolean empty) {
        StringBuilder json=new StringBuilder();
        json.append("{\"passed\":true,\"checks\":").append(count)
            .append(",\"androidAbi\":\"").append(quote(abi)).append("\",\"androidSdkInt\":").append(sdkInt)
            .append(",\"keyStoreProviderClass\":\"").append(quote(providerClass)).append("\",\"fakeAndroidKeyStore\":false")
            .append(",\"encryptedAtRest\":true,\"nonExportableKey\":").append(nonExportable)
            .append(",\"hardwareBacked\":").append(hardwareBacked)
            .append(",\"hardwareIsolationClaimed\":false")
            .append(",\"freshReaderMatched\":").append(freshReader)
            .append(",\"identityDigestMatched\":").append(identityMatched)
            .append(",\"wrongAadRejected\":").append(wrongAad)
            .append(",\"tamperRejected\":").append(tamperRejected)
            .append(",\"wrongInstanceRejected\":").append(wrongInstance)
            .append(",\"explicitlyRemoved\":").append(removed)
            .append(",\"keyStoreEmpty\":").append(empty).append('}');
        return json.toString();
    }

    public static String run(Context context,Report report) throws Exception {
        Provider provider=Security.getProvider("AndroidKeyStore");
        check(provider!=null,"platform must register the AndroidKeyStore provider");
        // The framework class loader is the platform one; a provider registered
        // by this test would arrive through the application class loader.
        ClassLoader framework=Build.class.getClassLoader();
        check(framework!=null && provider.getClass().getClassLoader()==framework,
            "the AndroidKeyStore provider must be a platform class, never a provider registered by this test");
        String providerClass=provider.getClass().getName();
        report.line("case systemProviderActive ok provider="+providerClass);

        Factory first=new Factory(), second=new Factory();
        Owner owner=new Owner(); owner.allow=true;
        AndroidZeroTierDeviceStore store=new AndroidZeroTierDeviceStore(context,first,owner);
        check(store.status()==null && first.generated==0,"missing identity does not generate");

        AndroidZeroTierDeviceStore.Device device=store.create();
        check(first.generated==1,"one synthetic identity generated");
        Path state=context.getNoBackupFilesDir().toPath().resolve(STORE_DIR+"/device.state");
        byte[] record=Files.readAllBytes(state);
        check(record.length==RECORD_BYTES && record[0]=='H' && record[1]=='Z' && record[2]=='D' && record[3]==1,
            "encrypted record on disk with the production header");
        byte[] identity=new byte[ZeroTierDeviceStoreCore.IDENTITY_BYTES];
        Arrays.fill(identity,(byte)'Z');
        check(!contains(record,identity),"plaintext identity bytes never reach disk");

        String alias=ZeroTierDeviceStoreCore.alias(device.handle);
        KeyStore keyStore=KeyStore.getInstance("AndroidKeyStore");
        keyStore.load(null);
        check(keyStore.containsAlias(alias),"device key lives in the system AndroidKeyStore");
        Key key=keyStore.getKey(alias,null);
        check(key instanceof SecretKey,"device key is a secret key");
        boolean nonExportable=key.getEncoded()==null;
        check(nonExportable,"system key is non-exportable (getEncoded is null)");
        Boolean hardwareBacked=hardwareBacked((SecretKey)key);
        report.line("case createStoresEncryptedRecord ok hardwareBacked="+hardwareBacked
            +" (emulator software KeyMint expected; not a hardware-isolation conclusion)");

        AndroidZeroTierEnvelope envelope=new AndroidZeroTierEnvelope();
        byte[] sealed=Arrays.copyOfRange(record,HEADER_BYTES,record.length);
        rejects(() -> envelope.create(alias,new byte[]{1},new byte[1]),"duplicate alias cannot replace the system key");
        boolean wrongAadRejected=rejects(() -> envelope.open(alias,new byte[]{0},sealed,value -> {}),
            "wrong AAD cannot decrypt through the system key");
        check(store.status().handle.equals(device.handle),"rejected envelope probes preserved the device");

        AndroidZeroTierDeviceStore restarted=new AndroidZeroTierDeviceStore(context,second,owner);
        AndroidZeroTierDeviceStore.Device readBack=restarted.status();
        boolean freshReader=readBack!=null && device.handle.equals(readBack.handle)
            && device.instanceId.equals(readBack.instanceId) && second.generated==0;
        check(freshReader,"a fresh store instance reads back the same identity without regenerating");
        final boolean[] matched={false};
        final byte[] expected=first.digest;
        AndroidZeroTierDeviceStore.RuntimeLease lease=restarted.acquire(device.handle);
        owner.bind(lease);
        lease.initialize(value -> matched[0]=MessageDigest.isEqual(sha(value),expected));
        lease.confirmDrained();
        boolean identityMatched=matched[0];
        check(identityMatched,"identity decrypted through the system key matches the generated bytes");
        report.line("case freshInstanceReadsBackIdentity ok");

        record[100]^=0x5a;
        Files.write(state,record);
        boolean tamperRejected=rejects(restarted::status,"tampered ciphertext is unreadable, never silently repaired");
        AndroidZeroTierDeviceStore stranger=new AndroidZeroTierDeviceStore(context,second,owner);
        rejects(() -> stranger.beginDiscardUnreadable(device.handle),"a fresh instance does not trust the plaintext header");
        AndroidZeroTierDeviceStore.UnreadableReview review=store.beginDiscardUnreadable(device.handle);
        check(device.handle.equals(review.handle()) && "unreadable".equals(review.state()),
            "review exposes only public metadata");
        rejects(() -> restarted.confirmDiscardUnreadable(review),"review is bound to the wrapper that verified the handle");
        store.confirmDiscardUnreadable(review);
        check(store.status()==null && restarted.status()==null,"confirmed discard removes the unreadable identity");
        keyStore=KeyStore.getInstance("AndroidKeyStore");
        keyStore.load(null);
        check(!keyStore.containsAlias(alias),"confirmed discard retired the system key");
        rejects(() -> store.confirmDiscardUnreadable(review),"review cannot be reused");
        report.line("case tamperUnreadableTwoStepDiscard ok");

        AndroidZeroTierDeviceStore.Device replacement=store.create();
        String replacementAlias=ZeroTierDeviceStoreCore.alias(replacement.handle);
        boolean wrongInstanceRejected=rejects(() -> store.forgetExact(replacement.handle,WRONG_INSTANCE),
            "forget with a wrong instance id is refused");
        check(store.status().handle.equals(replacement.handle),"refused forget left the record installed");
        store.forgetExact(replacement.handle,replacement.instanceId);
        boolean removed=store.status()==null;
        check(removed,"exact forget removes the identity");
        keyStore=KeyStore.getInstance("AndroidKeyStore");
        keyStore.load(null);
        check(keyStore.getKey(replacementAlias,null)==null,"explicit removal deleted the system key");
        boolean leftover=false;
        for (Enumeration<String> names=keyStore.aliases(); names.hasMoreElements(); )
            if (names.nextElement().startsWith(ZeroTierDeviceStoreCore.KEYSTORE_ALIAS_PREFIX)) leftover=true;
        boolean empty=!leftover;
        check(empty,"no ZeroTier device alias remains in the system keystore");
        check(store.pendingDeletion()==null && store.pendingCreation()==null,"no recovery marker is left behind");
        report.line("case forgetExactLocksToInstance ok");

        String abi=Build.SUPPORTED_ABIS.length>0 ? Build.SUPPORTED_ABIS[0] : "unknown";
        String json=evidenceJson(checks,abi,Build.VERSION.SDK_INT,providerClass,nonExportable,hardwareBacked,
            freshReader,identityMatched,wrongAadRejected,tamperRejected,wrongInstanceRejected,removed,empty);
        report.line("cases complete checks="+checks);
        return json;
    }
}
