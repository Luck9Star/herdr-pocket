package org.herdr.network;

import java.nio.file.*;
import java.security.SecureRandom;
import java.util.*;
import java.util.concurrent.*;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** Disposable JVM-only backend; never accesses AndroidKeyStore or real identities. */
public final class NetworkSecretStoreCoreTest {
    static final class MemoryBackend implements NetworkSecretStoreCore.Backend {
        final Map<String, SecretKey> keys = new HashMap<>();
        boolean locked, failCreate;
        public byte[] create(String handle, byte[] aad, byte[] plaintext) throws Exception {
            if (locked) throw new IllegalStateException("locked");
            if (failCreate) throw new IllegalStateException("create failed");
            KeyGenerator generator = KeyGenerator.getInstance("AES"); generator.init(256);
            SecretKey key = generator.generateKey(); keys.put(handle, key);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.ENCRYPT_MODE, key);
            cipher.updateAAD(aad); byte[] encrypted = cipher.doFinal(plaintext), iv = cipher.getIV();
            byte[] out = Arrays.copyOf(iv, iv.length + encrypted.length);
            System.arraycopy(encrypted, 0, out, iv.length, encrypted.length); return out;
        }
        public void open(String handle, byte[] aad, byte[] envelope, NetworkSecretStoreCore.PayloadOperation operation) throws Exception {
            if (locked) throw new IllegalStateException("locked");
            SecretKey key = keys.get(handle); if (key == null) throw new IllegalStateException("missing key");
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key, new GCMParameterSpec(128, envelope, 0, 12)); cipher.updateAAD(aad);
            byte[] payload = cipher.doFinal(envelope, 12, envelope.length - 12);
            try { operation.run(payload); } finally { Arrays.fill(payload, (byte) 0); }
        }
        public void delete(String handle) { keys.remove(handle); }
    }
    static final class IOExceptionForTest extends Exception {}
    interface Checked { void run() throws Exception; }
    static int checks;
    static void check(boolean value, String message) { checks++; if (!value) throw new AssertionError(message); }
    static void fails(Checked work, String message) throws Exception {
        checks++; try { work.run(); } catch (Exception expected) { return; } throw new AssertionError(message);
    }
    static String id(int n) { return String.format("%032x", n); }
    public static void main(String[] args) throws Exception {
        Path base = Files.createTempDirectory("network-vault-test-");
        try { run(base); System.out.println("PASS: " + checks + " checks (isolated JVM memory-key backend)"); }
        finally { try (java.util.stream.Stream<Path> files = Files.walk(base)) { files.sorted(Comparator.reverseOrder()).forEach(p -> { try { Files.deleteIfExists(p); } catch (Exception e) { throw new RuntimeException(e); } }); } }
    }
    static void run(Path base) throws Exception {
        MemoryBackend backend = new MemoryBackend();
        NetworkSecretStoreCore core = new NetworkSecretStoreCore(base, backend);
        check(core.status(id(1), "easytier") == null, "absent");
        byte[] original = {1, 2, 3};
        NetworkSecretStoreCore.Result created = core.create(id(1), "easytier", false, original);
        check(Arrays.equals(original, new byte[]{1,2,3}), "caller owns input");
        NetworkSecretStoreCore.Result restart = new NetworkSecretStoreCore(base, backend).status(id(1), "easytier");
        check(created.handle.equals(restart.handle) && created.instanceId.equals(restart.instanceId), "restart identity");
        final byte[][] borrowed = new byte[1][];
        core.withSecret(id(1), "easytier", created.handle, value -> { check(Arrays.equals(value, original), "secret callback"); borrowed[0] = value; });
        check(Arrays.equals(borrowed[0], new byte[3]), "callback buffer cleared");
        fails(() -> core.withSecret(id(1), "easytier", created.handle, value -> { borrowed[0] = value; throw new IOExceptionForTest(); }), "callback failure");
        check(Arrays.equals(borrowed[0], new byte[3]), "callback failure clears buffer");
        fails(() -> core.create(id(1), "easytier", false, original), "duplicate");
        fails(() -> core.status(id(1), "zerotier"), "wrong provider");
        fails(() -> core.withSecret(id(1), "easytier", UUID.randomUUID().toString(), s -> {}), "wrong handle");
        fails(() -> core.delete(id(1), "easytier", UUID.randomUUID().toString()), "stale delete");
        fails(() -> core.status("../bad", "easytier"), "path traversal");
        Path root = base.resolve("herdr-network-secrets-v1"), record = root.resolve(id(1) + ".network");
        Path other = root.resolve(id(2) + ".network"); Files.copy(record, other);
        fails(() -> core.status(id(2), "easytier"), "AAD wrong profile"); Files.delete(other);
        byte[] before = Files.readAllBytes(record), changed = before.clone(); changed[changed.length-1] ^= 1; Files.write(record, changed);
        fails(() -> core.status(id(1), "easytier"), "tamper"); Files.write(record, before);
        backend.locked = true; fails(() -> core.status(id(1), "easytier"), "locked"); backend.locked = false;
        SecretKey removed = backend.keys.remove(created.handle); fails(() -> core.status(id(1), "easytier"), "missing alias");
        fails(() -> core.create(id(1), "easytier", false, original), "missing alias does not recreate"); backend.keys.put(created.handle, removed);
        backend.failCreate = true; fails(() -> core.create(id(2), "easytier", false, original), "create failure"); backend.failCreate = false;
        check(core.status(id(2), "easytier") == null, "failed create leaves no record");
        fails(() -> core.create(id(2), "easytier", false, new byte[0]), "private empty");
        fails(() -> core.create(id(2), "easytier", true, original), "public nonempty");
        fails(() -> core.create(id(2), "easytier", false, new byte[1025]), "secret limit");
        fails(() -> core.create(id(2), "easytier", false, new byte[]{0}), "NUL rejected");
        fails(() -> core.create(id(2), "easytier", false, new byte[]{(byte) 0xff}), "invalid UTF-8 rejected");
        NetworkSecretStoreCore.Result pub = core.create(id(2), "easytier", true, new byte[0]);
        check(core.status(id(2), "easytier").publicNetwork, "explicit public");
        core.withSecret(id(2), "easytier", pub.handle, value -> check(value.length == 0, "public secret empty"));
        core.delete(id(2), "easytier", pub.handle); check(core.status(id(2), "easytier") == null, "delete");
        fails(() -> core.withSecret(id(2), "easytier", pub.handle, value -> {}), "deleted unavailable");
        Files.createSymbolicLink(other, record); fails(() -> core.status(id(2), "easytier"), "record symlink"); Files.delete(other);
        // Two instances cannot race to establish different identities for one profile.
        ExecutorService pool = Executors.newFixedThreadPool(2); CountDownLatch start = new CountDownLatch(1);
        List<Future<Boolean>> futures = new ArrayList<>();
        for (int i=0; i<2; i++) futures.add(pool.submit(() -> { start.await(); try { new NetworkSecretStoreCore(base, backend).create(id(3), "easytier", false, original); return true; } catch (Exception e) { return false; } }));
        start.countDown(); int successes = 0; for (Future<Boolean> f : futures) if (f.get()) successes++; pool.shutdown();
        check(successes == 1, "concurrent duplicate creation");
        NetworkSecretStoreCore metadataError = new NetworkSecretStoreCore(base, backend, path -> {
            throw new java.nio.file.AccessDeniedException("simulated metadata access denial");
        });
        fails(() -> metadataError.status(id(4), "easytier"), "metadata I/O error is not absent");
        fails(() -> metadataError.create(id(4), "easytier", false, original), "metadata I/O error rejects create");
        // A storage path that becomes a non-directory is a reproducible I/O error,
        // never "record absent" or permission to create another identity.
        Path displaced = base.resolve("displaced-network-directory");
        Files.move(root, displaced); Files.write(root, new byte[] {1});
        try {
            fails(() -> core.status(id(4), "easytier"), "unavailable storage is not absent");
            fails(() -> core.create(id(4), "easytier", false, original), "unavailable storage rejects create");
        } finally { Files.delete(root); Files.move(displaced, root); }
        // POSIX permission denial is conditional: privileged processes may bypass it.
        try {
            java.util.Set<java.nio.file.attribute.PosixFilePermission> permissions = Files.getPosixFilePermissions(root);
            try {
                Files.setPosixFilePermissions(root, java.util.Collections.emptySet());
                if (!Files.isReadable(root)) {
                    fails(() -> core.status(id(4), "easytier"), "permission denial is not absent");
                    fails(() -> core.create(id(4), "easytier", false, original), "permission denial rejects create");
                    System.out.println("PASS: POSIX permission denial checks");
                } else {
                    System.out.println("SKIP: POSIX permission denial (effective user bypasses permissions)");
                }
            } finally { Files.setPosixFilePermissions(root, permissions); }
        } catch (UnsupportedOperationException unsupported) {
            System.out.println("SKIP: POSIX permissions unavailable");
        }
        for (int i=4; i<=129; i++) core.create(id(i), "easytier", false, original);
        fails(() -> core.create(id(130), "easytier", false, original), "capacity");
        core.delete(id(1), "easytier", created.handle); check(!backend.keys.containsKey(created.handle), "key destroyed");
    }
}
