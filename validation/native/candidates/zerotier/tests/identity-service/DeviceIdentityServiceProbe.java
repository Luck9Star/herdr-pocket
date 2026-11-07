package org.herdr.network;

import android.app.KeyguardManager;
import android.content.Context;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.KeyStore;
import java.security.Security;
import java.util.Map;
import java.util.Set;

/** Real identity algorithm, service, wrapper, envelope/core; synthetic platform/KeyStore only. */
public final class DeviceIdentityServiceProbe {
    private static int checks;
    private static void check(boolean value) { if (!value) throw new AssertionError("identity_fixture_check"); checks++; }
    private interface Attempt { void run() throws Exception; }
    private static void rejects(Attempt operation) throws Exception {
        try { operation.run(); } catch (Exception expected) { checks++;return; }
        throw new AssertionError("identity_fixture_rejection_missing");
    }
    private static boolean containsCanonicalIdentity(byte[] value) {
        for (int start=0;start+270<=value.length;start++) {
            boolean match=true;
            for (int index=0;index<270 && match;index++) {
                int item=value[start+index]&255;
                match=(index==10 || index==12 || index==141) ? item==':' : index==11 ? item=='0' :
                    (item>='0' && item<='9') || (item>='a' && item<='f');
            }
            if (match) return true;
        }
        return false;
    }
    private static void removeTree(Path root) throws Exception {
        if (!Files.exists(root)) return;
        try (java.util.stream.Stream<Path> paths=Files.walk(root)) {
            for (Path item:paths.sorted(java.util.Comparator.reverseOrder()).toList()) Files.delete(item);
        }
        check(!Files.exists(root));
    }
    public static void main(String[] arguments) throws Exception {
        // Refuse an existing provider rather than ever consulting a real keystore.
        check(Security.getProvider("AndroidKeyStore")==null);
        Path root=Files.createDirectory(Path.of(arguments[0]),PosixFilePermissions.asFileAttribute(
            PosixFilePermissions.fromString("rwx------")));
        IdentityBridge factory=null;
        boolean ownProvider=false, passed=false;
        try {
            check(Security.addProvider(new ZeroTierAndroidStoreTest.FakeProvider())>0);ownProvider=true;
            KeyguardManager lock=new KeyguardManager();Context context=new Context(root.toFile(),lock);
            factory=new IdentityBridge();
            AndroidZeroTierDeviceStore.NativeOwner noRuntime=(handle,instance,lease)->{throw new AssertionError("no_runtime_allowed");};
            AndroidZeroTierDeviceStore store=new AndroidZeroTierDeviceStore(context,factory,noRuntime);
            AndroidZeroTierDeviceService.install(store);
            check(AndroidZeroTierDeviceService.status().get("device")==null);
            Map<String,String> created=AndroidZeroTierDeviceService.write("create",null,null,null);
            check(created.keySet().equals(Set.of("handle","instanceId")));check(factory.creates==1);
            check(factory.generatedBufferCleared());
            Path state=root.resolve("herdr-zerotier-device-v1/device.state");
            byte[] encrypted=Files.readAllBytes(state);
            check(encrypted.length>270);check(!containsCanonicalIdentity(encrypted));
            KeyStore keys=KeyStore.getInstance("AndroidKeyStore");keys.load(null);check(keys.size()==1);
            Map<?,?> reread=(Map<?,?>)AndroidZeroTierDeviceService.status().get("device");
            check(created.equals(reread));
            AndroidZeroTierDeviceStore freshReader=new AndroidZeroTierDeviceStore(context,factory,noRuntime);
            check(freshReader.status().instanceId.equals(created.get("instanceId")));
            check(factory.validations>=3);
            IdentityBridge originalFactory=factory;
            check(!originalFactory.validate(null));check(!originalFactory.validate(new byte[269]));
            check(!originalFactory.validate(new byte[270]));
            byte[] damaged=encrypted.clone();damaged[damaged.length-1]^=1;Files.write(state,damaged);
            rejects(AndroidZeroTierDeviceService::status);Files.write(state,encrypted);
            check(created.equals(AndroidZeroTierDeviceService.status().get("device")));
            rejects(()->AndroidZeroTierDeviceService.write("forget",created.get("handle"),
                "11111111-1111-4111-8111-111111111111",null));
            check(AndroidZeroTierDeviceService.write("forget",created.get("handle"),created.get("instanceId"),null)==null);
            Map<String,Object> after=AndroidZeroTierDeviceService.status();
            check(Boolean.TRUE.equals(after.get("available")));check(after.get("device")==null);
            check(after.get("pendingCreation")==null && after.get("pendingDeletion")==null);
            check(!Files.exists(state));check(keys.size()==0);check(factory.generatedBufferCleared());
            passed=true;
        } finally {
            if (factory!=null) factory.clear();
            if (ownProvider) Security.removeProvider("AndroidKeyStore");
            check(Security.getProvider("AndroidKeyStore")==null);
            removeTree(root);
        }
        check(passed);
        System.out.println("{\"passed\":true,\"checks\":"+checks+",\"nativeCreates\":"+factory.creates+
            ",\"nativeValidations\":"+factory.validations+",\"encryptedAtRest\":true,\"freshReaderMatched\":true,"+
            "\"tamperRejected\":true,\"wrongInstanceRejected\":true,\"explicitlyRemoved\":true,"+
            "\"buffersCleared\":true,\"keyStoreEmpty\":true,\"temporaryRootRemoved\":true}");
    }
}
