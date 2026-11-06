package org.herdr.network;

import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.NoSuchFileException;
import java.nio.file.attribute.BasicFileAttributes;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.util.Arrays;
import java.util.UUID;

/** Internal core. All backend operations and callbacks run under the storage lock. */
final class NetworkSecretStoreCore {
    static final int MAX_PROFILES = 128, MAX_SECRET_BYTES = 1024;
    private static final int HEADER = 4 + 36, MAX_RECORD = HEADER + 12 + 16 + 37 + MAX_SECRET_BYTES;
    private static final byte[] MAGIC = {'H', 'N', 'S', 1};
    private static final Object PROCESS_LOCK = new Object();
    interface SecretOperation { void run(byte[] secret) throws Exception; }
    interface PayloadOperation { void run(byte[] payload) throws Exception; }
    interface Backend {
        byte[] create(String handle, byte[] aad, byte[] payload) throws Exception;
        void open(String handle, byte[] aad, byte[] envelope, PayloadOperation operation) throws Exception;
        void delete(String handle) throws Exception;
    }
    static final class Result {
        final String profileId, provider, handle, instanceId;
        final boolean publicNetwork;
        Result(String profileId, String provider, String handle, String instanceId, boolean publicNetwork) {
            this.profileId = profileId; this.provider = provider; this.handle = handle;
            this.instanceId = instanceId; this.publicNetwork = publicNetwork;
        }
    }
    private final Path root;
    private final Backend backend;
    interface RecordMetadata { void read(Path path) throws IOException; }
    private final RecordMetadata metadata;
    NetworkSecretStoreCore(Path noBackup, Backend backend) throws IOException {
        this(noBackup, backend, path -> Files.readAttributes(path, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS));
    }
    // Package-private injection makes metadata I/O errors reproducible in isolated JVM tests.
    NetworkSecretStoreCore(Path noBackup, Backend backend, RecordMetadata metadata) throws IOException {
        if (Files.isSymbolicLink(noBackup) || !Files.isDirectory(noBackup, LinkOption.NOFOLLOW_LINKS))
            throw new IOException("unsafe storage root");
        root = noBackup.resolve("herdr-network-secrets-v1");
        try { Files.createDirectory(root); } catch (java.nio.file.FileAlreadyExistsException ignored) { }
        if (Files.isSymbolicLink(root) || !Files.isDirectory(root, LinkOption.NOFOLLOW_LINKS))
            throw new IOException("unsafe storage directory");
        this.backend = backend;
        this.metadata = metadata;
    }
    private interface Work<T> { T run() throws Exception; }
    private <T> T locked(Work<T> work) throws Exception {
        synchronized (PROCESS_LOCK) {
            Path lock = root.resolve(".lock");
            if (Files.isSymbolicLink(root) || Files.isSymbolicLink(lock)) throw new IOException("unsafe storage");
            try (FileChannel channel = FileChannel.open(lock, StandardOpenOption.CREATE, StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS);
                 FileLock ignored = channel.lock()) { return work.run(); }
        }
    }
    private static void checkProfile(String id, String provider) {
        if (id == null || !id.matches("[0-9a-f]{32}")) throw new IllegalArgumentException("profileId must be 32 lowercase hex");
        if (!"easytier".equals(provider)) throw new IllegalArgumentException("unsupported provider");
    }
    static String checkedHandle(String handle) {
        if (handle == null || !handle.matches("[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}"))
            throw new IllegalArgumentException("invalid local UUID");
        return handle;
    }
    private Path file(String profileId) { return root.resolve(profileId + ".network"); }
    private static byte[] aad(String profileId, String provider, String handle) {
        return ("herdr-network-secret:1:" + profileId + ":" + provider + ":" + handle).getBytes(StandardCharsets.US_ASCII);
    }
    private boolean recordExists(Path record) throws IOException {
        try {
            metadata.read(record);
            return true;
        } catch (NoSuchFileException absent) {
            return false;
        }
    }
    Result create(String profileId, String provider, boolean publicNetwork, byte[] secret) throws Exception {
        checkProfile(profileId, provider);
        if (secret == null || secret.length > MAX_SECRET_BYTES || (publicNetwork ? secret.length != 0 : secret.length == 0))
            throw new IllegalArgumentException("invalid secret mode or size");
        byte[] copy = secret.clone();
        try {
            if (!publicNetwork) checkUtf8(copy);
            return locked(() -> {
            Path destination = file(profileId);
            if (recordExists(destination)) throw new IOException("profile already exists");
            try (java.util.stream.Stream<Path> entries = Files.list(root)) {
                // Counts orphaned temporary files too, so crashes cannot grow storage without bound.
                if (entries.limit(MAX_PROFILES + 1L).count() >= MAX_PROFILES + 1L) throw new IOException("profile capacity");
            }
            String handle = UUID.randomUUID().toString(), instanceId = UUID.randomUUID().toString();
            byte[] payload = new byte[37 + copy.length];
            payload[0] = (byte) (publicNetwork ? 1 : 0);
            System.arraycopy(instanceId.getBytes(StandardCharsets.US_ASCII), 0, payload, 1, 36);
            System.arraycopy(copy, 0, payload, 37, copy.length);
            Path temporary = null; boolean keyCreated = false, installed = false;
            try {
                byte[] envelope = backend.create(handle, aad(profileId, provider, handle), payload);
                keyCreated = true;
                if (envelope.length != 12 + 16 + payload.length) throw new IOException("envelope bounds");
                ByteBuffer data = ByteBuffer.allocate(HEADER + envelope.length).put(MAGIC)
                    .put(handle.getBytes(StandardCharsets.US_ASCII)).put(envelope);
                data.flip();
                temporary = Files.createTempFile(root, ".pending-", ".tmp");
                try (FileChannel channel = FileChannel.open(temporary, StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS)) {
                    while (data.hasRemaining()) channel.write(data);
                    channel.force(true);
                }
                Files.move(temporary, destination, StandardCopyOption.ATOMIC_MOVE);
                installed = true;
                syncDirectory();
                return new Result(profileId, provider, handle, instanceId, publicNetwork);
            } catch (Exception failure) {
                if (installed) try { Files.deleteIfExists(destination); syncDirectory(); } catch (Exception cleanup) { failure.addSuppressed(cleanup); }
                if (temporary != null) try { Files.deleteIfExists(temporary); } catch (Exception cleanup) { failure.addSuppressed(cleanup); }
                if (keyCreated) try { backend.delete(handle); } catch (Exception cleanup) { failure.addSuppressed(cleanup); }
                throw failure;
            } finally { Arrays.fill(payload, (byte) 0); }
        }); } finally { Arrays.fill(copy, (byte) 0); }
    }
    private static void checkUtf8(byte[] secret) {
        for (byte value : secret) if (value == 0) throw new IllegalArgumentException("NUL is not allowed");
        char[] chars = new char[secret.length];
        try {
            java.nio.charset.CharsetDecoder decoder = StandardCharsets.UTF_8.newDecoder();
            java.nio.charset.CoderResult result = decoder.decode(ByteBuffer.wrap(secret), java.nio.CharBuffer.wrap(chars), true);
            if (result.isError() || result.isOverflow()) throw new IllegalArgumentException("secret must be UTF-8");
        } finally { Arrays.fill(chars, '\0'); }
    }
    private void syncDirectory() throws IOException {
        try (FileChannel channel = FileChannel.open(root, StandardOpenOption.READ)) { channel.force(true); }
    }
    private byte[] read(Path file) throws IOException {
        if (!Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS)) throw new IOException("record missing or unsafe");
        try (InputStream input = Files.newInputStream(file, LinkOption.NOFOLLOW_LINKS)) {
            byte[] bytes = input.readNBytes(MAX_RECORD + 1);
            if (bytes.length < HEADER + 12 + 16 + 37 || bytes.length > MAX_RECORD) throw new IOException("record bounds");
            if (!Arrays.equals(MAGIC, Arrays.copyOf(bytes, 4))) throw new IOException("record version");
            return bytes;
        }
    }
    private Result inspect(String profileId, String provider, String expectedHandle, SecretOperation operation) throws Exception {
        byte[] bytes = read(file(profileId));
        String handle = checkedHandle(new String(bytes, 4, 36, StandardCharsets.US_ASCII));
        if (expectedHandle != null && !handle.equals(checkedHandle(expectedHandle))) throw new IOException("handle mismatch");
        Result[] result = new Result[1];
        backend.open(handle, aad(profileId, provider, handle), Arrays.copyOfRange(bytes, HEADER, bytes.length), payload -> {
            if (payload.length < 37 || payload.length > 37 + MAX_SECRET_BYTES || (payload[0] != 0 && payload[0] != 1))
                throw new IOException("invalid protected record");
            boolean publicNetwork = payload[0] == 1;
            if (publicNetwork != (payload.length == 37)) throw new IOException("invalid protected mode");
            String instance = checkedHandle(new String(payload, 1, 36, StandardCharsets.US_ASCII));
            result[0] = new Result(profileId, provider, handle, instance, publicNetwork);
            if (operation != null) {
                byte[] secret = Arrays.copyOfRange(payload, 37, payload.length);
                try { operation.run(secret); } finally { Arrays.fill(secret, (byte) 0); }
            }
        });
        if (result[0] == null) throw new IOException("backend did not verify record");
        return result[0];
    }
    Result status(String profileId, String provider) throws Exception {
        checkProfile(profileId, provider);
        return locked(() -> !recordExists(file(profileId)) ? null : inspect(profileId, provider, null, null));
    }
    void withSecret(String profileId, String provider, String handle, SecretOperation operation) throws Exception {
        checkProfile(profileId, provider); checkedHandle(handle);
        if (operation == null) throw new IllegalArgumentException("operation required");
        locked(() -> { inspect(profileId, provider, handle, operation); return null; });
    }
    void delete(String profileId, String provider, String handle) throws Exception {
        checkProfile(profileId, provider); checkedHandle(handle);
        locked(() -> {
            inspect(profileId, provider, handle, null);
            // Destroy key first. If unlink fails, an unreadable record remains for diagnosis.
            backend.delete(handle);
            Files.delete(file(profileId));
            syncDirectory();
            return null;
        });
    }
}
