package org.herdr.network;

import android.app.KeyguardManager;
import android.content.Context;
import android.os.Build;
import java.io.File;
import java.io.IOException;
import java.lang.reflect.Field;
import java.nio.channels.FileChannel;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.security.Security;
import java.util.Arrays;
import java.util.UUID;

/** Synthetic-only injection into the actual shared service and device store. */
public final class ZeroTierServiceBridgeFixture {
    private static AndroidZeroTierDeviceStore store;
    private static AndroidZeroTierDeviceStore.RuntimeLease lease;
    private static boolean failAfterCommit;
    private static boolean allowDrain;
    private static boolean failRemove;
    public static int generations;
    public static void install(File root, boolean failCreation) throws Exception {
        Security.addProvider(new ZeroTierAndroidStoreTest.FakeProvider());
        Build.VERSION.SDK_INT = 35; failAfterCommit = failCreation;
        AndroidZeroTierDeviceStore.IdentityFactory factory = new AndroidZeroTierDeviceStore.IdentityFactory() {
            public byte[] generate() { generations++; byte[] value = new byte[ZeroTierDeviceStoreCore.IDENTITY_BYTES]; Arrays.fill(value,(byte)'X'); return value; }
            public boolean validate(byte[] value) { if (value == null || value.length != ZeroTierDeviceStoreCore.IDENTITY_BYTES) return false; for (byte b:value) if (b!='X') return false; return true; }
        };
        store = new AndroidZeroTierDeviceStore(new Context(root,new KeyguardManager()),factory,(h,i,l) -> allowDrain);
        ZeroTierDeviceStoreCore.Writer writer = (dir,target,bytes,creating) -> {
            Path temporary=dir.resolve(".bridge-"+UUID.randomUUID());
            Files.write(temporary,bytes,StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE);
            Files.setPosixFilePermissions(temporary,java.nio.file.attribute.PosixFilePermissions.fromString("rw-------"));
            Files.move(temporary,target,StandardCopyOption.ATOMIC_MOVE);
            if (creating && failAfterCommit) { failAfterCommit=false; throw new IOException("synthetic after commit"); }
        };
        ZeroTierDeviceStoreCore core=new ZeroTierDeviceStoreCore(root.toPath(),new AndroidZeroTierEnvelope(),writer,
            target -> {if (failRemove) {failRemove=false;throw new IOException("synthetic remove failure");} Files.delete(target);},
            directory -> {try (FileChannel file=FileChannel.open(directory,StandardOpenOption.READ)) {file.force(true);}});
        Field field=AndroidZeroTierDeviceStore.class.getDeclaredField("core");field.setAccessible(true);field.set(store,core);
        AndroidZeroTierDeviceService.install(store);
    }
    public static void acquire(String handle) throws Exception { lease=store.acquire(handle); }
    public static void failNextRemoval() { failRemove=true; }
    public static void release() throws Exception { allowDrain=true; lease.confirmDrained(); lease=null; }
}
