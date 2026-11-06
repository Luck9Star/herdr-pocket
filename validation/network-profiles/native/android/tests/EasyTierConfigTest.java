package org.herdr.network;

import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

/** Synthetic identity and secret only; parsed independently by run.sh. */
public final class EasyTierConfigTest {
    static int checks;
    interface Checked { void run() throws Exception; }
    static void check(boolean value, String message) { checks++; if (!value) throw new AssertionError(message); }
    static void fails(Checked task, String message) throws Exception {
        checks++; try { task.run(); } catch (Exception expected) { return; } throw new AssertionError(message);
    }
    static int indexOf(byte[] data, byte[] needle) {
        outer: for (int i = 0; i + needle.length <= data.length; i++) {
            for (int j = 0; j < needle.length; j++) if (data[i+j] != needle[j]) continue outer;
            return i;
        }
        return -1;
    }
    public static void main(String[] args) throws Exception {
        Path base = Files.createTempDirectory("easytier-config-test-");
        try {
            NetworkSecretStoreCoreTest.MemoryBackend backend = new NetworkSecretStoreCoreTest.MemoryBackend();
            NetworkSecretStoreCore vault = new NetworkSecretStoreCore(base, backend);
            String id = NetworkSecretStoreCoreTest.id(1), name = "中文\"\\quoted";
            String[] peers = {"tcp://example.com:11010", "wss://example.org/path"};
            byte[] secret = "假密码\"\\\t\n\u0085".getBytes(StandardCharsets.UTF_8);
            NetworkSecretStoreCore.Result identity = vault.create(id, "easytier", false, secret);
            NetworkSecretStoreCore.Result status = vault.status(id, "easytier");
            check(status.instanceId.equals(identity.instanceId) && !status.publicNetwork, "public status identity");
            check(Arrays.stream(NetworkSecretStoreCore.Result.class.getDeclaredFields()).noneMatch(f -> f.getType() == byte[].class), "status has no secret field");
            byte[] config = vault.easyTierConfig(id, identity.handle, name, peers);
            byte[] restarted = new NetworkSecretStoreCore(base, backend).easyTierConfig(id, identity.handle, name, peers);
            check(Arrays.equals(config, restarted), "stable instance and deterministic config after restart");
            check(config.length <= 65536, "config size");
            byte[] expectedId = ("instance_id = \"" + identity.instanceId + "\"").getBytes(StandardCharsets.US_ASCII);
            check(indexOf(config, expectedId) == 0, "config embeds authenticated stable instanceId");
            Files.write(Paths.get(args[0]), config);
            Arrays.fill(config, (byte) 0); Arrays.fill(restarted, (byte) 0);
            fails(() -> vault.easyTierConfig(id, UUID.randomUUID().toString(), name, peers), "wrong handle");
            fails(() -> vault.easyTierConfig(NetworkSecretStoreCoreTest.id(99), identity.handle, name, peers), "missing profile");
            backend.locked = true; fails(() -> vault.easyTierConfig(id, identity.handle, name, peers), "locked"); backend.locked = false;
            javax.crypto.SecretKey key = backend.keys.remove(identity.handle);
            fails(() -> vault.easyTierConfig(id, identity.handle, name, peers), "missing alias"); backend.keys.put(identity.handle, key);
            String pubId = NetworkSecretStoreCoreTest.id(2);
            NetworkSecretStoreCore.Result pub = vault.create(pubId, "easytier", true, new byte[0]);
            try { vault.easyTierConfig(pubId, pub.handle, name, peers); throw new AssertionError("public rejected"); }
            catch (IllegalStateException expected) { check("public_network_secret_unsupported".equals(expected.getMessage()), "explicit public refusal"); }
            for (String bad : new String[]{"", "  ", "abc\n[flags]", "a\u0085b", "\ud800", "x".repeat(65)})
                fails(() -> vault.easyTierConfig(id, identity.handle, bad, peers), "invalid name");
            for (String bad : new String[]{"tcp://host", "tcp://host:0", "tcp://host:65536", "tcp://host:12/path", "wss://user@host/path", "wss://host/?x", "ws://host/#x", "ws://host/\\test", "wss://host/path\n[flags]", "http://host", "wss://host:", "ws://host/\"evil"})
                fails(() -> vault.easyTierConfig(id, identity.handle, name, new String[]{bad}), "invalid peer");
            fails(() -> vault.easyTierConfig(id, identity.handle, name, new String[]{peers[0], peers[0]}), "duplicate peer");
            fails(() -> vault.easyTierConfig(id, identity.handle, name, new String[0]), "empty peers");
            fails(() -> vault.easyTierConfig(id, identity.handle, name, new String[17]), "peer limit");
            String[] longest = new String[16];
            for (int i = 0; i < longest.length; i++) longest[i] = "wss://example.com/" + ("a".repeat(2028)) + i;
            byte[] max = vault.easyTierConfig(id, identity.handle, name, longest); check(max.length <= 65536, "bounded max inputs"); Arrays.fill(max, (byte)0);
            vault.delete(id, "easytier", identity.handle);
            vault.create(id, "easytier", false, secret);
            fails(() -> vault.easyTierConfig(id, identity.handle, name, peers), "stale handle after replacement");
            Arrays.fill(secret, (byte)0);
            System.out.println("PASS: " + checks + " EasyTier config checks (synthetic JVM fixture)");
        } finally {
            try (java.util.stream.Stream<Path> files = Files.walk(base)) {
                files.sorted(Comparator.reverseOrder()).forEach(p -> { try { Files.deleteIfExists(p); } catch (Exception e) { throw new RuntimeException(e); } });
            }
        }
    }
}
