package org.herdr.network;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.EOFException;
import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.CharBuffer;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.NoSuchFileException;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.BasicFileAttributes;
import java.nio.file.attribute.PosixFilePermission;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.UUID;

/** Native-only encrypted complete StateStore. No key or value is a filesystem path. */
final class TailscaleStateStoreCore {
    static final int MAX_PROFILES = 32, MAX_KEYS = 256, MAX_KEY = 1024;
    static final int MAX_VALUE = 262144, MAX_PLAINTEXT = 4 * 1024 * 1024;
    private static final int HEADER = 4 + 36, MAX_RECORD = HEADER + 12 + 16 + MAX_PLAINTEXT;
    private static final byte[] MAGIC = {'H','T','S',1}, DELETE_MAGIC = {'H','T','D',1};
    private static final int DELETE_BYTES = 4 + 32 + 36 + 32, MAX_PENDING = 32;
    private static final Object PROCESS_LOCK = new Object();
    // An externally removed, previously observed file is not a new identity in
    // this process. A deliberate successful delete clears this observation.
    private static final Set<String> OBSERVED = new HashSet<>();
    // An intent may be unlinked before its directory fsync fails. The same
    // process retains the exact handle until a successful sync/retry.
    private static final Map<String,String> FINISHING = new java.util.HashMap<>();

    static final class NotFound extends Exception { NotFound() { super("state key not found"); } }
    interface PayloadOperation { void run(byte[] payload) throws Exception; }
    interface Backend {
        byte[] create(String handle, byte[] aad, byte[] payload) throws Exception;
        byte[] seal(String handle, byte[] aad, byte[] payload) throws Exception;
        void open(String handle, byte[] aad, byte[] envelope, PayloadOperation operation) throws Exception;
        void delete(String handle) throws Exception;
    }
    interface RecordWriter { void replace(Path root, Path destination, byte[] record, boolean creating) throws Exception; }
    interface RecordRemover { void remove(Path record) throws Exception; }
    interface DirectorySync { void sync(Path directory) throws Exception; }
    static final class Result {
        final String profileId, handle, instanceId;
        Result(String profileId, String handle, String instanceId) {
            this.profileId = profileId; this.handle = handle; this.instanceId = instanceId;
        }
    }
    // Clone at the boundary so neither caller mutation nor map access can change ordering.
    private static final class ByteKey implements Comparable<ByteKey> {
        private final byte[] bytes;
        ByteKey(byte[] bytes) {
            if (bytes == null || bytes.length > MAX_KEY) throw new IllegalArgumentException("state key bounds");
            this.bytes = bytes.clone();
        }
        public int compareTo(ByteKey other) {
            int limit = Math.min(bytes.length, other.bytes.length);
            for (int i = 0; i < limit; i++) {
                int difference = (bytes[i] & 0xff) - (other.bytes[i] & 0xff);
                if (difference != 0) return difference;
            }
            return Integer.compare(bytes.length, other.bytes.length);
        }
    }
    private static final class State {
        final String instanceId;
        final TreeMap<ByteKey,byte[]> values;
        State(String instanceId, TreeMap<ByteKey,byte[]> values) { this.instanceId = instanceId; this.values = values; }
        void clear() { for (byte[] value : values.values()) Arrays.fill(value, (byte) 0); values.clear(); }
    }
    private final Path root;
    private final Backend backend;
    private final RecordWriter writer;
    private final RecordRemover remover;
    private final DirectorySync directorySync;
    TailscaleStateStoreCore(Path noBackup, Backend backend) throws IOException {
        this(noBackup, backend, TailscaleStateStoreCore::atomicReplace, Files::delete, TailscaleStateStoreCore::syncDir);
    }
    TailscaleStateStoreCore(Path noBackup, Backend backend, RecordWriter writer) throws IOException {
        this(noBackup, backend, writer, Files::delete, TailscaleStateStoreCore::syncDir);
    }
    TailscaleStateStoreCore(Path noBackup, Backend backend, RecordRemover remover) throws IOException {
        this(noBackup, backend, TailscaleStateStoreCore::atomicReplace, remover, TailscaleStateStoreCore::syncDir);
    }
    TailscaleStateStoreCore(Path noBackup, Backend backend, RecordWriter writer, RecordRemover remover) throws IOException {
        this(noBackup,backend,writer,remover,TailscaleStateStoreCore::syncDir);
    }
    TailscaleStateStoreCore(Path noBackup, Backend backend, RecordRemover remover, DirectorySync directorySync) throws IOException {
        this(noBackup,backend,TailscaleStateStoreCore::atomicReplace,remover,directorySync);
    }
    TailscaleStateStoreCore(Path noBackup, Backend backend, RecordWriter writer, RecordRemover remover, DirectorySync directorySync) throws IOException {
        if (backend == null || writer == null || remover == null || directorySync == null || Files.isSymbolicLink(noBackup) || !Files.isDirectory(noBackup, LinkOption.NOFOLLOW_LINKS))
            throw new IOException("unsafe storage root");
        root = noBackup.toRealPath(LinkOption.NOFOLLOW_LINKS).resolve("herdr-tailscale-state-v1");
        createPrivateDir(root, noBackup);
        this.backend = backend; this.writer = writer; this.remover = remover; this.directorySync = directorySync;
    }
    private static final Set<PosixFilePermission> PRIVATE_MODE = PosixFilePermissions.fromString("rwx------");
    private static void verifyPrivateDir(Path directory, Path ownerReference) throws IOException {
        if (Files.isSymbolicLink(directory) || !Files.isDirectory(directory, LinkOption.NOFOLLOW_LINKS)
            || !Files.getPosixFilePermissions(directory, LinkOption.NOFOLLOW_LINKS).equals(PRIVATE_MODE)
            || !Files.getOwner(directory, LinkOption.NOFOLLOW_LINKS).equals(Files.getOwner(ownerReference, LinkOption.NOFOLLOW_LINKS)))
            throw new IOException("unsafe private directory");
    }
    private static void createPrivateDir(Path directory, Path ownerReference) throws IOException {
        try { Files.createDirectory(directory, PosixFilePermissions.asFileAttribute(PRIVATE_MODE)); }
        catch (java.nio.file.FileAlreadyExistsException ignored) { }
        verifyPrivateDir(directory, ownerReference);
    }
    private interface Work<T> { T run() throws Exception; }
    private <T> T locked(Work<T> work) throws Exception {
        synchronized (PROCESS_LOCK) {
            Path lock = root.resolve(".lock");
            verifyPrivateDir(root, root.getParent());
            if (Files.isSymbolicLink(lock)) throw new IOException("unsafe storage");
            try (FileChannel file = FileChannel.open(lock, StandardOpenOption.CREATE, StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS);
                 FileLock ignored = file.lock()) { return work.run(); }
        }
    }
    private static void profile(String profile) {
        if (profile == null || !profile.matches("[a-f0-9]{32}")) throw new IllegalArgumentException("invalid profile");
    }
    static String handle(String handle) {
        if (handle == null || !handle.matches("[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}"))
            throw new IllegalArgumentException("invalid identity");
        return handle;
    }
    private static byte[] keyBytes(String key) throws Exception {
        if (key == null || key.length() > MAX_KEY) throw new IllegalArgumentException("invalid state key");
        ByteBuffer encoded = StandardCharsets.UTF_8.newEncoder().onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT).encode(CharBuffer.wrap(key));
        if (encoded.remaining() > MAX_KEY) throw new IllegalArgumentException("state key bounds");
        byte[] bytes = new byte[encoded.remaining()]; encoded.get(bytes); return bytes;
    }
    private Path file(String profile) { return root.resolve(profile + ".state"); }
    private Path intentFile(String profile) { return root.resolve(profile + ".delete"); }
    private String observation(String profile) { return root.toString() + "\u0000" + profile; }
    private boolean exists(Path file) throws IOException {
        try { Files.readAttributes(file, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS); return true; }
        catch (NoSuchFileException missing) { return false; }
    }
    private boolean existsOrFail(String profile) throws IOException {
        // A dangling, damaged or valid deletion intent is never absence.
        if (FINISHING.containsKey(observation(profile)) || exists(intentFile(profile))) throw new IOException("deletion requires recovery");
        boolean present = exists(file(profile));
        if (!present && OBSERVED.contains(observation(profile))) throw new IOException("state record disappeared");
        if (present) OBSERVED.add(observation(profile));
        return present;
    }
    private static byte[] aad(String profile, String handle) {
        return ("herdr-tailscale-state:1:tailscale:" + profile + ":" + handle).getBytes(StandardCharsets.US_ASCII);
    }
    private static void syncDir(Path directory) throws IOException {
        try (FileChannel channel = FileChannel.open(directory, StandardOpenOption.READ)) { channel.force(true); }
    }
    private static void atomicReplace(Path root, Path destination, byte[] record, boolean creating) throws Exception {
        try (java.util.stream.Stream<Path> entries = Files.list(root)) {
            if (entries.filter(p -> p.getFileName().toString().startsWith(".pending-") &&
                p.getFileName().toString().endsWith(".tmp")).limit(MAX_PENDING).count() >= MAX_PENDING)
                throw new IOException("pending file capacity");
        }
        Path pending = Files.createTempFile(root, ".pending-", ".tmp");
        try {
            try (FileChannel file = FileChannel.open(pending, StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS)) {
                ByteBuffer data = ByteBuffer.wrap(record); while (data.hasRemaining()) file.write(data); file.force(true);
            }
            if (creating) Files.move(pending, destination, StandardCopyOption.ATOMIC_MOVE);
            else Files.move(pending, destination, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
            syncDir(root);
        } finally { Files.deleteIfExists(pending); }
    }
    private byte[] readRecord(String profile) throws IOException {
        Path path = file(profile);
        if (!Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS)) throw new IOException("invalid state record");
        try (InputStream input = Files.newInputStream(path, LinkOption.NOFOLLOW_LINKS)) {
            byte[] result = input.readNBytes(MAX_RECORD + 1);
            if (result.length < HEADER + 12 + 16 || result.length > MAX_RECORD ||
                !Arrays.equals(MAGIC, Arrays.copyOf(result, 4))) throw new IOException("invalid state record");
            return result;
        }
    }
    private static byte[] record(String handle, byte[] envelope) throws IOException {
        if (envelope == null || envelope.length < 28 || envelope.length > 28 + MAX_PLAINTEXT) throw new IOException("envelope bounds");
        return ByteBuffer.allocate(HEADER + envelope.length).put(MAGIC).put(handle.getBytes(StandardCharsets.US_ASCII)).put(envelope).array();
    }
    private static final class WipingBuffer extends ByteArrayOutputStream {
        void wipe() { Arrays.fill(buf,(byte) 0); reset(); }
    }
    private static byte[] encode(State state) throws Exception {
        WipingBuffer bytes = new WipingBuffer();
        try {
            try (DataOutputStream out = new DataOutputStream(bytes)) {
                out.write(handle(state.instanceId).getBytes(StandardCharsets.US_ASCII));
                if (state.values.size() > MAX_KEYS) throw new IOException("state key capacity");
                out.writeInt(state.values.size());
                for (Map.Entry<ByteKey,byte[]> entry : state.values.entrySet()) {
                    byte[] key = entry.getKey().bytes, value = entry.getValue();
                    if (value == null || value.length > MAX_VALUE || (long) bytes.size() + 8L + key.length + value.length > MAX_PLAINTEXT)
                        throw new IOException("state capacity");
                    out.writeInt(key.length); out.write(key); out.writeInt(value.length); out.write(value);
                }
            }
            byte[] payload = bytes.toByteArray(); if (payload.length > MAX_PLAINTEXT) throw new IOException("state capacity"); return payload;
        } finally { bytes.wipe(); }
    }
    private static State decode(byte[] payload) throws Exception {
        if (payload.length < 40 || payload.length > MAX_PLAINTEXT) throw new IOException("invalid state payload");
        TreeMap<ByteKey,byte[]> values = new TreeMap<>();
        try (DataInputStream input = new DataInputStream(new ByteArrayInputStream(payload))) {
            byte[] id = input.readNBytes(36); if (id.length != 36) throw new EOFException();
            String instanceId = handle(new String(id, StandardCharsets.US_ASCII));
            int count = input.readInt(); if (count < 0 || count > MAX_KEYS) throw new IOException("state key capacity");
            for (int i=0;i<count;i++) {
                int keyLength = input.readInt(); if (keyLength < 0 || keyLength > MAX_KEY || keyLength > input.available()) throw new IOException("invalid state key");
                byte[] key = input.readNBytes(keyLength);
                ByteKey name = new ByteKey(key);
                int length = input.readInt(); if (length < 0 || length > MAX_VALUE || length > input.available() || values.containsKey(name)) throw new IOException("invalid state value");
                values.put(name, input.readNBytes(length));
            }
            if (input.read() != -1) throw new IOException("trailing state bytes");
            return new State(instanceId, values);
        } catch (Exception error) { for (byte[] value : values.values()) Arrays.fill(value, (byte) 0); throw error; }
    }
    private interface Verified<T> { T run(String handle, State state, byte[] original) throws Exception; }
    private <T> T inspect(String profile, String expected, Verified<T> work) throws Exception {
        byte[] record = readRecord(profile);
        String actual = handle(new String(record, 4, 36, StandardCharsets.US_ASCII));
        if (expected != null && !actual.equals(handle(expected))) throw new IOException("identity mismatch");
        final Object[] result = new Object[1]; final boolean[] visited = {false};
        backend.open(actual, aad(profile, actual), Arrays.copyOfRange(record, HEADER, record.length), payload -> {
            State state = decode(payload);
            try { result[0] = work.run(actual, state, record); visited[0] = true; } finally { state.clear(); }
        });
        if (!visited[0]) throw new IOException("state key unavailable");
        @SuppressWarnings("unchecked") T value = (T) result[0]; return value;
    }
    Result create(String profile) throws Exception {
        profile(profile);
        return locked(() -> {
            if (existsOrFail(profile)) throw new IOException("profile already exists");
            try (java.util.stream.Stream<Path> entries = Files.list(root)) {
                long profiles = entries.map(p -> p.getFileName().toString())
                    .filter(n -> n.matches("[a-f0-9]{32}\\.(?:state|delete)"))
                    .map(n -> n.substring(0,32)).distinct().limit(MAX_PROFILES).count();
                if (profiles >= MAX_PROFILES) throw new IOException("profile capacity");
            }
            String h = UUID.randomUUID().toString(), id = UUID.randomUUID().toString();
            State state = new State(id, new TreeMap<>()); byte[] payload = encode(state);
            boolean keyCreated = false;
            try {
                byte[] encrypted = backend.create(h, aad(profile,h), payload); keyCreated = true;
                if (encrypted == null || encrypted.length != payload.length + 28) throw new IOException("envelope bounds");
                writer.replace(root, file(profile), record(h,encrypted), true);
                OBSERVED.add(observation(profile));
                return new Result(profile,h,id);
            } catch (Exception error) {
                // A replacement error can happen after rename; preserve any
                // possibly installed record and key for explicit status review.
                boolean absent = false;
                try { absent = !exists(file(profile)); } catch (Exception uncertain) { error.addSuppressed(uncertain); }
                if (keyCreated && absent) try { backend.delete(h); } catch (Exception cleanup) { error.addSuppressed(cleanup); }
                if (!absent) OBSERVED.add(observation(profile));
                throw error;
            } finally { Arrays.fill(payload, (byte) 0); state.clear(); }
        });
    }
    Result status(String profile) throws Exception {
        profile(profile); return locked(() -> !existsOrFail(profile) ? null : inspect(profile,null,(h,s,original) -> new Result(profile,h,s.instanceId)));
    }
    byte[] readState(String profile, String expected, String key) throws Exception {
        return readStateBytes(profile, expected, keyBytes(key));
    }
    byte[] readStateBytes(String profile, String expected, byte[] key) throws Exception {
        profile(profile); handle(expected); ByteKey name = new ByteKey(key);
        return locked(() -> {
            if (!existsOrFail(profile)) throw new IOException("identity unavailable");
            return inspect(profile,expected,(h,s,original) -> {
                byte[] value = s.values.get(name); if (value == null) throw new NotFound(); return value.clone();
            });
        });
    }
    void writeState(String profile, String expected, String key, byte[] value) throws Exception {
        writeStateBytes(profile, expected, keyBytes(key), value);
    }
    void writeStateBytes(String profile, String expected, byte[] key, byte[] value) throws Exception {
        profile(profile); handle(expected); ByteKey name = new ByteKey(key);
        if (value != null && value.length > MAX_VALUE) throw new IllegalArgumentException("state value bounds");
        byte[] copy = value == null ? null : value.clone();
        try { locked(() -> {
            if (!existsOrFail(profile)) throw new IOException("identity unavailable");
            return inspect(profile,expected,(h,s,original) -> {
                byte[] old = copy == null ? s.values.remove(name) : s.values.put(name, copy.clone());
                if (old != null) Arrays.fill(old, (byte) 0);
                if (copy == null && old == null) return null;
                byte[] payload = encode(s);
                try {
                    byte[] envelope = backend.seal(h,aad(profile,h),payload);
                    if (envelope == null || envelope.length != payload.length + 28) throw new IOException("envelope bounds");
                    if (!Arrays.equals(original,readRecord(profile))) throw new IOException("state conflict");
                    writer.replace(root,file(profile),record(h,envelope),false);
                } finally { Arrays.fill(payload, (byte) 0); }
                return null;
            });
        }); } finally { if (copy != null) Arrays.fill(copy, (byte) 0); }
    }
    String runtimeDirectory(String profile, String expected) throws Exception {
        profile(profile); handle(expected);
        return locked(() -> {
            if (!existsOrFail(profile)) throw new IOException("identity unavailable");
            return inspect(profile,expected,(h,s,original) -> {
                Path parent = root.resolve("runtime");
                createPrivateDir(parent, root);
                Path dir = parent.resolve(h);
                if (!exists(dir)) {
                    try (java.util.stream.Stream<Path> entries = Files.list(parent)) {
                        if (entries.limit(MAX_PROFILES).count() >= MAX_PROFILES) throw new IOException("runtime directory capacity");
                    }
                    createPrivateDir(dir, root);
                }
                verifyPrivateDir(dir, root);
                syncDir(parent); syncDir(root); return dir.toString();
            });
        });
    }
    private static byte[] digest(byte[] value) throws Exception {
        return java.security.MessageDigest.getInstance("SHA-256").digest(value);
    }
    private static byte[] deleteIntent(String profile, String expected, byte[] original) throws Exception {
        return ByteBuffer.allocate(DELETE_BYTES).put(DELETE_MAGIC).put(profile.getBytes(StandardCharsets.US_ASCII))
            .put(expected.getBytes(StandardCharsets.US_ASCII)).put(digest(original)).array();
    }
    private byte[] readIntent(String profile, String expected) throws Exception {
        Path path = intentFile(profile);
        if (!Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS)) throw new IOException("invalid deletion intent");
        byte[] data;
        try (InputStream input = Files.newInputStream(path, LinkOption.NOFOLLOW_LINKS)) { data = input.readNBytes(DELETE_BYTES + 1); }
        if (data.length != DELETE_BYTES || !Arrays.equals(DELETE_MAGIC,Arrays.copyOf(data,4)) ||
            !profile.equals(new String(data,4,32,StandardCharsets.US_ASCII)) ||
            !expected.equals(handle(new String(data,36,36,StandardCharsets.US_ASCII))))
            throw new IOException("invalid deletion intent");
        return Arrays.copyOfRange(data,72,DELETE_BYTES);
    }
    private void requireIntentRecord(String profile, String expected, byte[] intendedHash) throws Exception {
        byte[] current = readRecord(profile);
        if (!expected.equals(handle(new String(current,4,36,StandardCharsets.US_ASCII))) ||
            !java.security.MessageDigest.isEqual(intendedHash,digest(current)))
            throw new IOException("deletion identity changed");
    }
    private void retireEmptyRuntime(String expected) throws Exception {
        // Never recursively erase tsnet output. Retire only this identity's
        // directory if it is still empty; nonempty historical dirs remain.
        Path runtime = root.resolve("runtime"), dir = runtime.resolve(expected);
        if (!Files.isSymbolicLink(runtime) && Files.isDirectory(runtime, LinkOption.NOFOLLOW_LINKS) &&
            !Files.isSymbolicLink(dir) && Files.isDirectory(dir, LinkOption.NOFOLLOW_LINKS)) {
            try { Files.delete(dir); syncDir(runtime); }
            catch (java.nio.file.DirectoryNotEmptyException retained) { /* explicitly retained */ }
        }
    }
    void delete(String profile, String expected) throws Exception {
        profile(profile); handle(expected);
        locked(() -> {
            Path intent = intentFile(profile), record = file(profile);
            String owner = observation(profile);
            String finishing = FINISHING.get(owner);
            if (!exists(intent) && finishing != null) {
                if (!expected.equals(finishing) || exists(record)) throw new IOException("deletion identity changed");
                backend.delete(expected); directorySync.sync(root);
                FINISHING.remove(owner); OBSERVED.remove(owner); retireEmptyRuntime(expected); return null;
            }
            byte[] intendedHash;
            if (exists(intent)) {
                intendedHash = readIntent(profile, expected);
            } else {
                if (!existsOrFail(profile)) throw new IOException("identity unavailable");
                byte[] original = readRecord(profile);
                inspect(profile,expected,(h,s,verified) -> {
                    if (!Arrays.equals(original,verified)) throw new IOException("state conflict"); return null;
                });
                if (!Arrays.equals(original,readRecord(profile))) throw new IOException("state conflict");
                byte[] wire = deleteIntent(profile,expected,original);
                atomicReplace(root,intent,wire,true);
                intendedHash = digest(original);
            }
            // The old hash must match before deleting even the original key.
            boolean present = exists(record);
            if (present) requireIntentRecord(profile,expected,intendedHash);
            backend.delete(expected); // Idempotent when a previous attempt removed it.
            if (present) {
                requireIntentRecord(profile,expected,intendedHash);
                remover.remove(record); directorySync.sync(root);
            }
            FINISHING.put(owner,expected);
            Files.delete(intent); directorySync.sync(root);
            FINISHING.remove(owner); OBSERVED.remove(owner);
            retireEmptyRuntime(expected); return null;
        });
    }
}
