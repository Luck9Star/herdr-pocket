package org.herdr.pairing;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Arrays;
import java.util.UUID;

/** Bounded persistent core; injected fixture backend is only accessible in package tests. */
final class DeviceKeyStoreCore {
    interface SeedOperation<T> { T run(byte[] seed) throws Exception; }
    interface EnvelopeBackend {
        byte[] createEnvelope(String handle, byte[] seed) throws Exception;
        <T> T withSeed(String handle, byte[] envelope, SeedOperation<T> operation) throws Exception;
        void delete(String handle) throws Exception;
    }
    static final int MAX_KEYS = 128;
    private static final byte[] MAGIC = {'H', 'D', 'K', 1};
    private static final int RECORD_SIZE = 4 + 32 + 61;
    // Includes multiple instances in the same app process; file lock covers other app processes.
    private static final Object PROCESS_LOCK = new Object();
    private final Path root;
    private final EnvelopeBackend backend;
    static final class Created {
        final String handle;
        final String publicKey;
        Created(String handle, String publicKey) { this.handle = handle; this.publicKey = publicKey; }
    }
    DeviceKeyStoreCore(Path noBackupDirectory, EnvelopeBackend backend) throws Exception {
        this.root = noBackupDirectory.resolve("herdr-device-keys-v1");
        this.backend = backend;
        if (Files.isSymbolicLink(noBackupDirectory)) throw new IOException("unsafe storage root");
        if (!Files.exists(root, LinkOption.NOFOLLOW_LINKS)) Files.createDirectory(root);
        if (Files.isSymbolicLink(root) || !Files.isDirectory(root, LinkOption.NOFOLLOW_LINKS))
            throw new IOException("unsafe key directory");
    }
    private interface Work<T> { T run() throws Exception; }
    private <T> T locked(Work<T> work) throws Exception {
        synchronized (PROCESS_LOCK) {
            Path lock = root.resolve(".lock");
            if (Files.isSymbolicLink(root) || Files.isSymbolicLink(lock)) throw new IOException("unsafe storage");
            try (FileChannel channel = FileChannel.open(lock, StandardOpenOption.CREATE,
                    StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS);
                 FileLock ignored = channel.lock()) { return work.run(); }
        }
    }
    static String checkedHandle(String handle) {
        if (handle == null || !handle.matches("[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}")
                || !UUID.fromString(handle).toString().equals(handle))
            throw new IllegalArgumentException("local UUID handle");
        return handle;
    }
    private Path path(String handle) { return root.resolve(checkedHandle(handle) + ".key"); }
    Created create() throws Exception {
        return locked(() -> {
            try (java.util.stream.Stream<Path> files = Files.list(root)) {
                // Count all entries, including crash remnants: refuse unbounded disk growth.
                if (files.limit(MAX_KEYS + 1L).count() >= MAX_KEYS + 1L) throw new IOException("key capacity");
            }
            String handle = UUID.randomUUID().toString();
            Path destination = path(handle);
            if (Files.exists(destination, LinkOption.NOFOLLOW_LINKS)) throw new IOException("handle collision");
            byte[] seed = new byte[32];
            new SecureRandom().nextBytes(seed);
            Path temporary = null;
            boolean createdEnvelope = false;
            try {
                byte[] pub = Ed25519Operations.publicBytes(seed);
                // Backend owns cleanup of partial creation; do not delete an existing alias
                // if it rejected a collision before creating anything.
                byte[] envelope = backend.createEnvelope(handle, seed);
                createdEnvelope = true;
                if (envelope.length != 61 || envelope[0] != 1) throw new IOException("envelope bounds");
                byte[] record = ByteBuffer.allocate(RECORD_SIZE).put(MAGIC).put(pub).put(envelope).array();
                temporary = Files.createTempFile(root, ".pending-", ".tmp");
                try (FileChannel channel = FileChannel.open(temporary, StandardOpenOption.WRITE)) {
                    ByteBuffer bytes = ByteBuffer.wrap(record);
                    while (bytes.hasRemaining()) channel.write(bytes);
                    channel.force(true);
                }
                // Same directory/filesystem; no non-atomic fallback and no handle replacement.
                Files.move(temporary, destination, StandardCopyOption.ATOMIC_MOVE);
                syncDirectory();
                return new Created(handle, Ed25519Operations.publicLine(pub));
            } catch (Exception failure) {
                try { Files.deleteIfExists(destination); } catch (Exception cleanup) { failure.addSuppressed(cleanup); }
                if (temporary != null) try { Files.deleteIfExists(temporary); } catch (Exception cleanup) { failure.addSuppressed(cleanup); }
                if (createdEnvelope) try { backend.delete(handle); } catch (Exception cleanup) { failure.addSuppressed(cleanup); }
                throw failure;
            } finally { Arrays.fill(seed, (byte) 0); }
        });
    }
    private void syncDirectory() throws IOException {
        try (FileChannel directory = FileChannel.open(root, StandardOpenOption.READ)) { directory.force(true); }
    }
    private byte[] record(String handle) throws Exception {
        Path file = path(handle);
        if (!Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS) || Files.size(file) != RECORD_SIZE)
            throw new IOException("device key missing or malformed; pair explicitly");
        // Bound reads even if a same-UID writer changes the file during this operation.
        byte[] record = new byte[RECORD_SIZE];
        try (java.io.InputStream input = Files.newInputStream(file, LinkOption.NOFOLLOW_LINKS)) {
            int offset = 0;
            while (offset < record.length) {
                int count = input.read(record, offset, record.length - offset);
                if (count < 0) throw new IOException("truncated device key");
                offset += count;
            }
            if (input.read() != -1) throw new IOException("oversized device key");
        }
        if (!Arrays.equals(MAGIC, Arrays.copyOf(record, 4))) throw new IOException("device key version");
        return record;
    }
    private <T> T withVerifiedSeed(String handle, SeedOperation<T> operation) throws Exception {
        byte[] record = record(handle);
        byte[] pub = Arrays.copyOfRange(record, 4, 36);
        return backend.withSeed(handle, Arrays.copyOfRange(record, 36, RECORD_SIZE), seed -> {
            if (!MessageDigest.isEqual(pub, Ed25519Operations.publicBytes(seed)))
                throw new IOException("device public key mismatch");
            return operation.run(seed);
        });
    }
    String publicKey(String handle) throws Exception {
        checkedHandle(handle);
        return locked(() -> withVerifiedSeed(handle, seed -> Ed25519Operations.publicLine(Ed25519Operations.publicBytes(seed))));
    }
    byte[] sign(String handle, byte[] message) throws Exception {
        checkedHandle(handle);
        Ed25519Operations.checkMessage(message);
        byte[] bounded = message.clone();
        return locked(() -> withVerifiedSeed(handle, seed -> Ed25519Operations.sign(seed, bounded)));
    }
    void delete(String handle) throws Exception {
        checkedHandle(handle);
        locked(() -> {
            // Invalidate the protected seed before unlinking its envelope. A failed unlink cannot sign.
            backend.delete(handle);
            Files.deleteIfExists(path(handle));
            syncDirectory();
            return null;
        });
    }
}
