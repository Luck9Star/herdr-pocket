package org.herdr.pairing;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.SecureRandom;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HexFormat;
import java.util.Map;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import org.bouncycastle.math.ec.rfc8032.Ed25519;

/** Pure JVM test: only disposable temp files + memory AES keys; never AndroidKeyStore. */
public final class DeviceKeyStoreCoreTest {
    private static int checks;
    private interface Throwing { void run() throws Exception; }
    private static void require(boolean ok, String label) {
        if (!ok) throw new AssertionError(label);
        checks++;
    }
    private static void rejects(Throwing action, String label) throws Exception {
        try { action.run(); } catch (Exception expected) { checks++; return; }
        throw new AssertionError(label);
    }
    private static final class MemoryEnvelope implements DeviceKeyStoreCore.EnvelopeBackend {
        final Map<String, SecretKey> keys = new HashMap<>();
        boolean locked;
        boolean failAfterCreate;
        boolean malformedEnvelope;
        byte[] activeSeed;
        public byte[] createEnvelope(String handle, byte[] seed) throws Exception {
            if (keys.containsKey(handle) || locked) throw new IllegalStateException("fixture unavailable");
            KeyGenerator generator = KeyGenerator.getInstance("AES");
            generator.init(256);
            keys.put(handle, generator.generateKey());
            activeSeed = seed;
            if (failAfterCreate) {
                keys.remove(handle); // Production backend also owns partial-create cleanup.
                throw new IllegalStateException("injected create failure");
            }
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, keys.get(handle));
            cipher.updateAAD(handle.getBytes(StandardCharsets.US_ASCII));
            byte[] record = new byte[61];
            record[0] = 1;
            System.arraycopy(cipher.getIV(), 0, record, 1, 12);
            System.arraycopy(cipher.doFinal(seed), 0, record, 13, 48);
            return malformedEnvelope ? new byte[1] : record;
        }
        public <T> T withSeed(String handle, byte[] envelope, DeviceKeyStoreCore.SeedOperation<T> operation) throws Exception {
            if (locked || !keys.containsKey(handle)) throw new IllegalStateException("fixture unavailable");
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, keys.get(handle), new GCMParameterSpec(128, envelope, 1, 12));
            cipher.updateAAD(handle.getBytes(StandardCharsets.US_ASCII));
            activeSeed = cipher.doFinal(envelope, 13, 48);
            try { return operation.run(activeSeed); } finally { Arrays.fill(activeSeed, (byte) 0); }
        }
        public void delete(String handle) { keys.remove(handle); }
    }
    public static void main(String[] args) throws Exception {
        byte[] seed = HexFormat.of().parseHex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60");
        byte[] pub = HexFormat.of().parseHex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a");
        require(Arrays.equals(Ed25519Operations.publicBytes(seed), pub), "RFC8032 public vector");
        require(HexFormat.of().formatHex(Ed25519Operations.sign(seed, new byte[0])).equals(
            "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"), "RFC8032 signature vector");
        String expected = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINdamAGCsQq31Uv+08lkBzoO4XLz2qYjJa8CGmj3B1Ea";
        require(Ed25519Operations.publicLine(pub).equals(expected), "canonical SSH wire and padding");
        rejects(() -> Ed25519Operations.sign(seed, new byte[65537]), "oversize message");
        rejects(() -> Ed25519Operations.sign(seed, null), "null message");
        Path temporary = Files.createTempDirectory("herdr-device-key-fixture-");
        try {
            MemoryEnvelope backend = new MemoryEnvelope();
            DeviceKeyStoreCore store = new DeviceKeyStoreCore(temporary, backend);
            DeviceKeyStoreCore.Created created = store.create();
            require(Arrays.equals(backend.activeSeed, new byte[32]), "create clears seed");
            require(created.publicKey.equals(store.publicKey(created.handle)), "create public roundtrip");
            DeviceKeyStoreCore reopened = new DeviceKeyStoreCore(temporary, backend);
            require(created.publicKey.equals(reopened.publicKey(created.handle)), "restart keeps identity");
            byte[] message = "temporary fixture challenge".getBytes(StandardCharsets.UTF_8);
            byte[] signature = reopened.sign(created.handle, message);
            byte[] wire = java.util.Base64.getDecoder().decode(created.publicKey.split(" ")[1]);
            require(signature.length == 64 && Ed25519.verify(signature, 0, wire, 19, message, 0, message.length), "64-byte signature verifies");
            require(Arrays.equals(backend.activeSeed, new byte[32]), "sign clears seed");
            byte[] maximum = new byte[65536]; new SecureRandom().nextBytes(maximum);
            require(store.sign(created.handle, maximum).length == 64, "max payload accepted");
            rejects(() -> store.sign(created.handle, new byte[65537]), "oversize store message");
            rejects(() -> store.publicKey("../escape"), "path traversal handle");
            rejects(() -> store.publicKey(created.handle.toUpperCase()), "noncanonical UUID");
            backend.locked = true;
            rejects(() -> store.sign(created.handle, message), "locked rejects sign");
            rejects(() -> store.publicKey(created.handle), "locked rejects public retrieval");
            backend.locked = false;
            Path recordPath = temporary.resolve("herdr-device-keys-v1").resolve(created.handle + ".key");
            byte[] record = Files.readAllBytes(recordPath);
            require(record.length == 97, "bounded encrypted record");
            record[5] ^= 1; Files.write(recordPath, record);
            rejects(() -> store.publicKey(created.handle), "tampered public mismatch");
            record[5] ^= 1; record[50] ^= 1; Files.write(recordPath, record);
            rejects(() -> store.sign(created.handle, message), "GCM tamper rejects");
            record[50] ^= 1; Files.write(recordPath, record);
            Files.write(recordPath, new byte[98]);
            rejects(() -> store.sign(created.handle, message), "oversized envelope");
            Files.write(recordPath, new byte[96]);
            rejects(() -> store.sign(created.handle, message), "truncated envelope");
            Files.write(recordPath, record);
            backend.keys.clear();
            rejects(() -> reopened.sign(created.handle, message), "lost key rejects with no replacement");
            require(backend.keys.isEmpty() && Files.exists(recordPath), "lost key retained fail-closed");
            store.delete(created.handle);
            rejects(() -> store.sign(created.handle, message), "deleted key unavailable");
            require(!Files.exists(recordPath), "delete removes envelope");
            backend.failAfterCreate = true;
            rejects(store::create, "create failure returned");
            require(backend.keys.isEmpty(), "partial alias cleaned");
            require(Arrays.equals(backend.activeSeed, new byte[32]), "failed create seed cleared");
            try (java.util.stream.Stream<Path> files = Files.list(recordPath.getParent())) {
                require(files.count() == 1, "failed create leaves only lock");
            }
            backend.failAfterCreate = false;
            backend.malformedEnvelope = true;
            rejects(store::create, "invalid envelope cleanup");
            require(backend.keys.isEmpty(), "successful envelope then persistence rejection removes alias");
            backend.malformedEnvelope = false;
            for (int i = 0; i < DeviceKeyStoreCore.MAX_KEYS; i++) store.create();
            rejects(store::create, "capacity limit");
        } finally {
            try (java.util.stream.Stream<Path> paths = Files.walk(temporary)) {
                for (Path path : paths.sorted(java.util.Comparator.reverseOrder()).toList()) Files.delete(path);
            }
        }
        System.out.println("{\"scope\":\"pure-JVM-temp-fixture-only\",\"checks\":" + checks
            + ",\"androidKeystore\":\"not-executed\",\"realDevice\":\"not-executed\"}");
    }
}
