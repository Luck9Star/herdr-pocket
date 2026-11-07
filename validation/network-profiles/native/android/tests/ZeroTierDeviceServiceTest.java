package org.herdr.network;

import android.app.KeyguardManager;
import android.content.Context;
import android.os.Build;
import java.io.IOException;
import java.nio.channels.FileChannel;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.Security;
import java.util.Arrays;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import java.lang.reflect.Field;

/** Isolated JVM check for the shared device metadata service; all identities are synthetic. */
public final class ZeroTierDeviceServiceTest {
    private static int checks;
    private static final String WRONG_INSTANCE = "11111111-1111-4111-8111-111111111111";
    private static final Set<String> ROOT_KEYS = Set.of("available", "device", "pendingCreation", "pendingDeletion");
    private static final Set<String> DEVICE_KEYS = Set.of("handle", "instanceId");
    private static final Set<String> PENDING_KEYS = Set.of("handle", "phase");

    private interface Attempt { void run() throws Exception; }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
        checks++;
    }

    private static void rejects(Attempt work, String message) throws Exception {
        try {
            work.run();
        } catch (Exception expected) {
            checks++;
            return;
        }
        throw new AssertionError(message);
    }

    private static final class Factory implements AndroidZeroTierDeviceStore.IdentityFactory {
        int generated;
        volatile CountDownLatch generationEntered;
        volatile CountDownLatch generationRelease;

        void blockNextGeneration() {
            generationEntered = new CountDownLatch(1);
            generationRelease = new CountDownLatch(1);
        }

        @Override public byte[] generate() throws Exception {
            CountDownLatch entered = generationEntered;
            CountDownLatch release = generationRelease;
            if (entered != null && release != null) {
                generationEntered = null;
                entered.countDown();
                if (!release.await(3, TimeUnit.SECONDS)) throw new IOException("bounded test latch timed out");
            }
            generated++;
            byte[] value = new byte[ZeroTierDeviceStoreCore.IDENTITY_BYTES];
            Arrays.fill(value, (byte) 'X');
            return value;
        }

        @Override public boolean validate(byte[] identity) {
            if (identity == null || identity.length != ZeroTierDeviceStoreCore.IDENTITY_BYTES) return false;
            for (byte value : identity) if (value != 'X') return false;
            return true;
        }
    }

    private static final class Owner implements AndroidZeroTierDeviceStore.NativeOwner {
        boolean allow;
        int calls;
        String handle;
        String instanceId;
        String leaseId;

        @Override public boolean retireExact(String h, String i, String l) {
            calls++;
            return allow && h.equals(handle) && i.equals(instanceId) && l.equals(leaseId);
        }

        void bind(AndroidZeroTierDeviceStore.RuntimeLease lease) {
            handle = lease.device().handle;
            instanceId = lease.device().instanceId;
            leaseId = lease.leaseId();
        }
    }

    private static Map<String, Object> status() throws Exception {
        return AndroidZeroTierDeviceService.status();
    }

    private static Map<String, String> write(String action, String handle, String instanceId, String expectedPhase) throws Exception {
        return AndroidZeroTierDeviceService.write(action, handle, instanceId, expectedPhase);
    }

    private static Map<?, ?> map(Object value, String message) {
        check(value instanceof Map<?, ?>, message);
        return (Map<?, ?>) value;
    }

    private static void exactKeys(Map<?, ?> value, Set<String> allowed, String message) {
        check(value.keySet().equals(allowed), message + ": " + value.keySet());
    }

    @SuppressWarnings({"rawtypes", "unchecked"})
    private static void immutable(Map<?, ?> value, String message) {
        try {
            ((Map) value).put("mutation", "must fail");
        } catch (UnsupportedOperationException expected) {
            checks++;
            return;
        }
        throw new AssertionError(message);
    }

    private static void publicRoot(Map<String, Object> value, boolean available) {
        exactKeys(value, ROOT_KEYS, "service status exposes only public top-level fields");
        check(Boolean.valueOf(available).equals(value.get("available")), "availability is explicit");
        immutable(value, "status map must be immutable");
        Object device = value.get("device");
        if (device != null) {
            Map<?, ?> record = map(device, "device is a public map");
            exactKeys(record, DEVICE_KEYS, "device exposes handle and instance only");
            immutable(record, "device map must be immutable");
        }
        for (String key : new String[] {"pendingCreation", "pendingDeletion"}) {
            Object pending = value.get(key);
            if (pending != null) {
                Map<?, ?> record = map(pending, "pending state is a public map");
                exactKeys(record, PENDING_KEYS, "pending state exposes handle and phase only");
                immutable(record, "pending map must be immutable");
            }
        }
        check(!value.toString().contains("X".repeat(32)), "service status never contains identity bytes");
    }

    private static void publicWriteResult(Map<String, String> value) {
        if (value == null) return;
        check(DEVICE_KEYS.containsAll(value.keySet()) || PENDING_KEYS.containsAll(value.keySet()),
            "write result contains only public metadata keys");
        immutable(value, "write result map must be immutable");
        check(!value.toString().contains("X".repeat(32)), "write result never contains identity bytes");
    }

    private static void installFakeProvider() {
        if (Security.getProvider("AndroidKeyStore") == null) {
            Security.addProvider(new ZeroTierAndroidStoreTest.FakeProvider());
        }
        Build.VERSION.SDK_INT = 35;
    }

    private static Path tempDirectory(String prefix) throws Exception {
        return Files.createTempDirectory(prefix);
    }

    private static void removeTree(Path root) throws Exception {
        if (!Files.exists(root)) return;
        try (java.util.stream.Stream<Path> paths = Files.walk(root)) {
            paths.sorted(java.util.Comparator.reverseOrder()).forEach(path -> {
                try { Files.deleteIfExists(path); }
                catch (Exception error) { throw new RuntimeException(error); }
            });
        }
    }

    private static void runUninstalled() throws Exception {
        Path base = tempDirectory("zerotier-service-uninstalled-");
        try {
            Map<String, Object> before = status();
            publicRoot(before, false);
            check(before.get("device") == null && before.get("pendingCreation") == null
                && before.get("pendingDeletion") == null, "uninstalled status is unknown, not absent");
            check(Files.list(base).count() == 0, "status before install does not create storage directories");
            rejects(() -> write("create", null, null, null), "writes are unavailable before installation");
            check(Files.list(base).count() == 0, "uninstalled write does not create storage directories");
            System.out.println("PASS uninstalled checks=" + checks);
        } finally {
            removeTree(base);
        }
    }

    private static void runInstalled() throws Exception {
        installFakeProvider();
        Path base = tempDirectory("zerotier-service-installed-");
        try {
            KeyguardManager keyguard = new KeyguardManager();
            Context context = new Context(base.toFile(), keyguard);
            Factory factory = new Factory();
            Owner owner = new Owner();
            AndroidZeroTierDeviceStore store = new AndroidZeroTierDeviceStore(context, factory, owner);

            AndroidZeroTierDeviceService.install(store);
            AndroidZeroTierDeviceService.install(store);
            publicRoot(status(), true);
            Map<String, Object> empty = status();
            check(empty.get("device") == null && empty.get("pendingCreation") == null
                && empty.get("pendingDeletion") == null, "empty installed snapshot is consistent");

            AndroidZeroTierDeviceStore other = new AndroidZeroTierDeviceStore(context, factory, owner);
            rejects(() -> AndroidZeroTierDeviceService.install(other), "different store instance cannot replace installed store");

            rejects(() -> write("create", WRONG_INSTANCE, null, null), "create rejects a supplied handle");
            rejects(() -> write("create", null, WRONG_INSTANCE, null), "create rejects a supplied instance id");
            rejects(() -> write("create", null, null, "record-present"), "create rejects a supplied phase");
            rejects(() -> write("unknown", null, null, null), "unknown action is rejected");
            rejects(() -> write("recoverPendingCreation", WRONG_INSTANCE, WRONG_INSTANCE, "record-present"), "recovery rejects extra instance argument");
            rejects(() -> write("discardPendingCreation", WRONG_INSTANCE, null, "record-present"), "discard rejects installed-record phase");
            rejects(() -> write("recoverPendingDeletion", WRONG_INSTANCE, null, "record-pending"), "deletion recovery rejects invalid phase");
            check(factory.generated == 0, "invalid requests do not generate identity");

            Map<String, String> created = write("create", null, null, null);
            check(created != null, "create returns public metadata");
            publicWriteResult(created);
            exactKeys(created, DEVICE_KEYS, "create returns only handle and instance id");
            String handle = created.get("handle");
            String instanceId = created.get("instanceId");
            check(handle != null && instanceId != null, "create returns exact public device identity");
            Map<String, Object> active = status();
            publicRoot(active, true);
            Map<?, ?> record = map(active.get("device"), "created device is readable");
            check(handle.equals(record.get("handle")) && instanceId.equals(record.get("instanceId")),
                "status returns the created public record");

            rejects(() -> write("forget", handle, WRONG_INSTANCE, null), "wrong instance id cannot forget identity");
            check(handle.equals(map(status().get("device"), "wrong-instance forget keeps device").get("handle")),
                "wrong instance forget preserves current record");
            rejects(() -> write("forget", handle, null, null), "forget requires exact instance id");
            rejects(() -> write("forget", handle, instanceId, "record-present"), "ordinary forget rejects pending phase");
            rejects(() -> write("recoverPendingDeletion", handle, null, "record-present"),
                "pending deletion recovery cannot fall back to first deletion");
            check(handle.equals(map(status().get("device"), "rejected pending deletion keeps device").get("handle")),
                "missing pending deletion rejection preserves the ordinary record");

            AndroidZeroTierDeviceStore.RuntimeLease lease = store.acquire(handle);
            owner.bind(lease);
            rejects(() -> write("forget", handle, instanceId, null), "active runtime lease blocks forget");
            check(owner.calls == 0, "active lease rejection does not invent native retirement proof");
            owner.allow = true;
            lease.confirmDrained();
            Map<String, String> forgotten = write("forget", handle, instanceId, null);
            publicWriteResult(forgotten);
            Map<String, Object> absent = status();
            publicRoot(absent, true);
            check(absent.get("device") == null, "exact forget removes device after drain proof");

            factory.blockNextGeneration();
            CountDownLatch createDone = new CountDownLatch(1);
            AtomicReference<Map<String, String>> concurrentCreate = new AtomicReference<>();
            AtomicReference<Throwable> concurrentFailure = new AtomicReference<>();
            Thread creator = new Thread(() -> {
                try { concurrentCreate.set(write("create", null, null, null)); }
                catch (Throwable error) { concurrentFailure.set(error); }
                finally { createDone.countDown(); }
            }, "synthetic-zero-tier-service-create");
            int generatedBefore = factory.generated;
            creator.start();
            check(factory.generationEntered.await(2, TimeUnit.SECONDS), "create reaches bounded synthetic identity gate");
            long busyStart = System.nanoTime();
            rejects(ZeroTierDeviceServiceTest::status, "status refuses while an operation owns the service lock");
            rejects(() -> write("create", null, null, null), "write refuses while an operation owns the service lock");
            long busyMillis = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - busyStart);
            check(busyMillis < 500, "busy status/write reject promptly instead of queueing");
            factory.generationRelease.countDown();
            check(createDone.await(2, TimeUnit.SECONDS), "the admitted operation completes after latch release");
            creator.join(2000);
            check(!creator.isAlive() && concurrentFailure.get() == null, "concurrent create completes exactly once");
            check(factory.generated == generatedBefore + 1, "busy writes did not generate an extra identity");
            Map<String, String> recreated = concurrentCreate.get();
            check(recreated != null, "admitted concurrent create returns public metadata");
            publicWriteResult(recreated);
            String secondHandle = recreated.get("handle");
            keyguard.locked = true;
            rejects(ZeroTierDeviceServiceTest::status, "locked storage error is not reported as absence");
            keyguard.locked = false;

            Path state = base.resolve("herdr-zerotier-device-v1/device.state");
            byte[] damaged = Files.readAllBytes(state);
            damaged[damaged.length - 1] ^= 1;
            Files.write(state, damaged);
            rejects(ZeroTierDeviceServiceTest::status, "corrupt record error is not reported as absence");
            check(Files.exists(state) && secondHandle != null, "corrupt record remains for explicit recovery");
            System.out.println("PASS installed checks=" + checks);
        } finally {
            Security.removeProvider("AndroidKeyStore");
            removeTree(base);
        }
    }

    private static void runPendingRecovery() throws Exception {
        installFakeProvider();
        Path base = tempDirectory("zerotier-service-pending-");
        try {
            KeyguardManager keyguard = new KeyguardManager();
            Context context = new Context(base.toFile(), keyguard);
            Factory factory = new Factory();
            Owner owner = new Owner();
            AndroidZeroTierDeviceStore store = new AndroidZeroTierDeviceStore(context, factory, owner);
            final boolean[] failAfterCommit = {true};
            final int[] syncCalls = {0};
            final int[] failSyncAt = {0};
            ZeroTierDeviceStoreCore.Writer writer = (root, target, bytes, creating) -> {
                Path temporary = root.resolve(".service-pending-" + UUID.randomUUID() + ".tmp");
                Files.write(temporary, bytes, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
                Files.setPosixFilePermissions(temporary, PosixFilePermissions.fromString("rw-------"));
                Files.move(temporary, target, StandardCopyOption.ATOMIC_MOVE);
                if (creating && failAfterCommit[0]) throw new IOException("synthetic failure after record commit");
            };
            ZeroTierDeviceStoreCore injected = new ZeroTierDeviceStoreCore(
                base, new AndroidZeroTierEnvelope(), writer, Files::delete, directory -> {
                    syncCalls[0]++;
                    if (failSyncAt[0] != 0 && syncCalls[0] == failSyncAt[0])
                        throw new IOException("synthetic directory sync failure");
                    try (FileChannel channel = FileChannel.open(directory, StandardOpenOption.READ)) {
                        channel.force(true);
                    }
                });
            Field coreField = AndroidZeroTierDeviceStore.class.getDeclaredField("core");
            coreField.setAccessible(true);
            coreField.set(store, injected);
            AndroidZeroTierDeviceService.install(store);
            rejects(() -> write("create", null, null, null),
                "synthetic post-commit failure leaves recoverable record-present pending state");
            Map<String, Object> pendingSnapshot = status();
            publicRoot(pendingSnapshot, true);
            check(pendingSnapshot.get("device") == null && pendingSnapshot.get("pendingDeletion") == null,
                "pending creation snapshot does not expose a usable device");
            Map<?, ?> pending = map(pendingSnapshot.get("pendingCreation"), "pending creation is visible");
            check("record-present".equals(pending.get("phase")), "record-present pending phase is exact");
            String handle = (String) pending.get("handle");

            rejects(() -> write("recoverPendingCreation", handle, WRONG_INSTANCE, "record-present"), "recovery rejects extra instance id");
            rejects(() -> write("recoverPendingCreation", WRONG_INSTANCE, null, "record-present"), "recovery rejects stale pending handle");
            rejects(() -> write("recoverPendingCreation", handle, null, "finishing"), "recovery rejects stale pending phase");
            rejects(() -> write("discardPendingCreation", handle, null, "record-present"), "record-present pending creation cannot be discarded");
            Map<String, String> recovered = write("recoverPendingCreation", handle, null, "record-present");
            check(recovered != null, "explicit recovery returns public device metadata");
            publicWriteResult(recovered);
            exactKeys(recovered, DEVICE_KEYS, "recovery returns only handle and instance id");
            check(handle.equals(recovered.get("handle")), "recovery binds to the reviewed pending handle");
            Map<String, Object> after = status();
            publicRoot(after, true);
            Map<?, ?> device = map(after.get("device"), "recovered device becomes readable");
            check(handle.equals(device.get("handle")) && after.get("pendingCreation") == null,
                "recovery atomically replaces pending state with public device state");
            check(factory.generated == 1, "pending recovery did not generate a replacement identity");

            check(write("forget", recovered.get("handle"), recovered.get("instanceId"), null) == null,
                "exact ordinary forget releases recovered device before the next fixture");
            failAfterCommit[0] = false;
            syncCalls[0] = 0;
            failSyncAt[0] = 2;
            rejects(() -> write("create", null, null, null), "synthetic final sync failure leaves finishing creation");
            Map<?, ?> finishing = map(status().get("pendingCreation"), "final sync failure exposes finishing creation");
            String finishingHandle = (String) finishing.get("handle");
            check("finishing".equals(finishing.get("phase")), "final sync failure exposes exact finishing creation phase");
            rejects(() -> write("recoverPendingCreation", finishingHandle, null, "record-present"),
                "finishing creation rejects stale record-present phase");
            check("finishing".equals(map(status().get("pendingCreation"), "stale creation phase remains pending").get("phase")),
                "stale create phase does not mutate finishing pending state");
            syncCalls[0] = 0;
            failSyncAt[0] = 0;
            Map<String, String> finished = write("recoverPendingCreation", finishingHandle, null, "finishing");
            check(finished != null && finishingHandle.equals(finished.get("handle")),
                "exact finishing creation recovery preserves reviewed identity");
            check(status().get("pendingCreation") == null && factory.generated == 2,
                "finishing recovery clears pending without generating a replacement");
            System.out.println("PASS pending-recovery checks=" + checks);
        } finally {
            Security.removeProvider("AndroidKeyStore");
            removeTree(base);
        }
    }

    private static void runPendingDeletionRecovery() throws Exception {
        installFakeProvider();
        Path base = tempDirectory("zerotier-service-delete-pending-");
        try {
            KeyguardManager keyguard = new KeyguardManager();
            Context context = new Context(base.toFile(), keyguard);
            Factory factory = new Factory();
            Owner owner = new Owner();
            AndroidZeroTierDeviceStore store = new AndroidZeroTierDeviceStore(context, factory, owner);
            final boolean[] failRemove = {false};
            final int[] syncCalls = {0};
            final int[] failSyncAt = {0};
            ZeroTierDeviceStoreCore injected = new ZeroTierDeviceStoreCore(
                base, new AndroidZeroTierEnvelope(),
                (root, target, bytes, creating) -> Files.write(target, bytes),
                target -> {
                    if (failRemove[0]) throw new IOException("synthetic state unlink failure");
                    Files.delete(target);
                },
                directory -> {
                    syncCalls[0]++;
                    if (failSyncAt[0] != 0 && syncCalls[0] == failSyncAt[0])
                        throw new IOException("synthetic directory sync failure");
                    try (FileChannel channel = FileChannel.open(directory, StandardOpenOption.READ)) {
                        channel.force(true);
                    }
                });
            Field coreField = AndroidZeroTierDeviceStore.class.getDeclaredField("core");
            coreField.setAccessible(true);
            coreField.set(store, injected);
            AndroidZeroTierDeviceService.install(store);

            Map<String, String> first = write("create", null, null, null);
            String firstHandle = first.get("handle");
            String firstInstance = first.get("instanceId");
            failRemove[0] = true;
            rejects(() -> write("forget", firstHandle, firstInstance, null),
                "synthetic unlink failure leaves pending deletion");
            Map<?, ?> presentPending = map(status().get("pendingDeletion"), "failed unlink exposes pending deletion");
            check(firstHandle.equals(presentPending.get("handle")) && "record-present".equals(presentPending.get("phase")),
                "failed unlink exposes exact record-present phase");
            rejects(() -> write("recoverPendingDeletion", WRONG_INSTANCE, null, "record-present"),
                "pending deletion rejects stale handle");
            rejects(() -> write("recoverPendingDeletion", firstHandle, null, "record-removed"),
                "pending deletion rejects stale phase");
            Map<?, ?> unchangedPresent = map(status().get("pendingDeletion"), "stale recovery preserves pending deletion");
            check(firstHandle.equals(unchangedPresent.get("handle")) && "record-present".equals(unchangedPresent.get("phase")),
                "stale handle or phase does not mutate pending deletion");
            failRemove[0] = false;
            check(write("recoverPendingDeletion", firstHandle, null, "record-present") == null,
                "exact record-present deletion recovery returns no device metadata");
            check(status().get("device") == null && status().get("pendingDeletion") == null,
                "record-present recovery completes the reviewed deletion");

            Map<String, String> second = write("create", null, null, null);
            String secondHandle = second.get("handle");
            syncCalls[0] = 0;
            failSyncAt[0] = 1;
            rejects(() -> write("forget", secondHandle, second.get("instanceId"), null),
                "synthetic post-unlink sync failure leaves pending deletion");
            Map<?, ?> removedPending = map(status().get("pendingDeletion"), "post-unlink failure exposes pending deletion");
            check(secondHandle.equals(removedPending.get("handle")) && "record-removed".equals(removedPending.get("phase")),
                "post-unlink failure exposes exact record-removed phase");
            rejects(() -> write("recoverPendingDeletion", secondHandle, null, "record-present"),
                "record-removed pending rejects stale record-present phase");
            check("record-removed".equals(map(status().get("pendingDeletion"), "stale deletion phase is retained").get("phase")),
                "stale record-present phase leaves record-removed pending unchanged");
            syncCalls[0] = 0;
            failSyncAt[0] = 0;
            check(write("recoverPendingDeletion", secondHandle, null, "record-removed") == null,
                "exact record-removed deletion recovery succeeds");
            check(status().get("device") == null && status().get("pendingDeletion") == null,
                "record-removed recovery clears the reviewed intent");

            Map<String, String> third = write("create", null, null, null);
            String thirdHandle = third.get("handle");
            syncCalls[0] = 0;
            failSyncAt[0] = 2;
            rejects(() -> write("forget", thirdHandle, third.get("instanceId"), null),
                "synthetic final sync failure leaves finishing deletion");
            Map<?, ?> finishing = map(status().get("pendingDeletion"), "final sync failure exposes finishing deletion");
            check(thirdHandle.equals(finishing.get("handle")) && "finishing".equals(finishing.get("phase")),
                "final sync failure exposes exact finishing phase");
            syncCalls[0] = 0;
            failSyncAt[0] = 0;
            check(write("recoverPendingDeletion", thirdHandle, null, "finishing") == null,
                "exact finishing deletion recovery succeeds");
            check(status().get("device") == null && status().get("pendingDeletion") == null,
                "finishing recovery clears the reviewed operation");
            System.out.println("PASS pending-deletion-recovery checks=" + checks);
        } finally {
            Security.removeProvider("AndroidKeyStore");
            removeTree(base);
        }
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new IllegalArgumentException("expected uninstalled, installed, pending-recovery, or pending-deletion-recovery mode");
        switch (args[0]) {
            case "uninstalled" -> runUninstalled();
            case "installed" -> runInstalled();
            case "pending-recovery" -> runPendingRecovery();
            case "pending-deletion-recovery" -> runPendingDeletionRecovery();
            default -> throw new IllegalArgumentException("unknown test mode");
        }
    }
}
