package org.herdr.network;

import android.app.KeyguardManager;
import android.content.Context;
import java.io.IOException;
import java.lang.reflect.Field;
import java.nio.channels.FileChannel;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.Security;
import java.util.Arrays;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Test-only store installation/faults. Never linked into an Android app. */
public final class ZeroTierPluginServiceFixture {
    public static final KeyguardManager lock = new KeyguardManager();
    public static volatile boolean failCreate, failDelete;
    public static volatile CountDownLatch entered, release;
    public static int generated;
    private static AndroidZeroTierDeviceStore store;
    private static AndroidZeroTierDeviceStore.RuntimeLease lease;
    private static Path root;
    private static boolean ownProvider;
    public static void install(String directory) throws Exception {
        root = Files.createDirectory(Path.of(directory));
        if (Security.getProvider("AndroidKeyStore") != null)
            throw new IllegalStateException("pre-existing provider refused");
        if (Security.addProvider(new ZeroTierAndroidStoreTest.FakeProvider()) < 1)
            throw new IllegalStateException("fixture provider not installed");
        ownProvider = true;
        store = new AndroidZeroTierDeviceStore(new Context(root.toFile(),lock),
            new AndroidZeroTierDeviceStore.IdentityFactory() {
                public byte[] generate() throws Exception {
                    if (entered != null) {
                        entered.countDown();
                        if (!release.await(5,TimeUnit.SECONDS)) throw new IOException("bounded fixture wait");
                    }
                    generated++;
                    byte[] identity = new byte[ZeroTierDeviceStoreCore.IDENTITY_BYTES];
                    Arrays.fill(identity,(byte)'X');
                    return identity;
                }
                public boolean validate(byte[] value) {
                    if (value == null || value.length != ZeroTierDeviceStoreCore.IDENTITY_BYTES) return false;
                    for (byte item : value) if (item != 'X') return false;
                    return true;
                }
            }, (handle,instance,id) -> true);
        ZeroTierDeviceStoreCore injected = new ZeroTierDeviceStoreCore(root,new AndroidZeroTierEnvelope(),
            (directoryRoot,target,bytes,creating) -> {
                Path temporary = directoryRoot.resolve(".plugin-fixture-"+UUID.randomUUID()+".tmp");
                Files.write(temporary,bytes,StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE);
                Files.setPosixFilePermissions(temporary,PosixFilePermissions.fromString("rw-------"));
                Files.move(temporary,target,StandardCopyOption.ATOMIC_MOVE);
                if (creating && failCreate) throw new IOException("synthetic post-commit failure");
            }, target -> {
                if (failDelete && target.getFileName().toString().equals("device.state"))
                    throw new IOException("synthetic deletion failure");
                Files.delete(target);
            }, directoryRoot -> {
                try (FileChannel channel = FileChannel.open(directoryRoot,StandardOpenOption.READ)) { channel.force(true); }
            });
        Field core = AndroidZeroTierDeviceStore.class.getDeclaredField("core");
        core.setAccessible(true); core.set(store,injected);
        AndroidZeroTierDeviceService.install(store);
    }
    public static void acquire(String handle) throws Exception { lease = store.acquire(handle); }
    public static void drain() throws Exception { lease.confirmDrained(); lease = null; }
    public static void cleanup() throws Exception {
        if (release != null) release.countDown();
        if (lease != null) drain();
        if (ownProvider) {
            Security.removeProvider("AndroidKeyStore");
            if (Security.getProvider("AndroidKeyStore") != null)
                throw new AssertionError("fixture provider remains");
        }
        if (root != null && Files.exists(root)) {
            try (java.util.stream.Stream<Path> paths = Files.walk(root)) {
                for (Path path : paths.sorted(java.util.Comparator.reverseOrder()).toList()) Files.delete(path);
            }
            if (Files.exists(root)) throw new AssertionError("fixture directory remains");
        }
    }
}
