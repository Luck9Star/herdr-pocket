package org.herdr.network;

import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.channels.OverlappingFileLockException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.NoSuchFileException;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.BasicFileAttributes;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/** One device identity; no network profile, plaintext file or GUI secret surface. */
final class ZeroTierDeviceStoreCore {
    static final int IDENTITY_BYTES = 270;
    static final String KEYSTORE_ALIAS_PREFIX = "org.herdr.pocket.zerotier-device.v1.";
    private static final int UUID_BYTES = 36, HEADER = 4 + UUID_BYTES;
    private static final int PLAIN = UUID_BYTES + IDENTITY_BYTES, RECORD = HEADER + 12 + PLAIN + 16;
    private static final int INTENT = 4 + UUID_BYTES + 32, MAX_PENDING = 16;
    private static final byte[] MAGIC = {'H','Z','D',1}, DELETE_MAGIC = {'H','Z','X',1}, CREATE_MAGIC = {'H','Z','C',1};
    private static final Object GUARD = new Object();
    // Strong ownership is deliberate: GC/activity recreation must never retire a node lease.
    private static final Map<Path, Owner> OWNERS = new HashMap<>();
    private static final Set<Path> OBSERVED = new HashSet<>();
    private static final Map<Path, String> FINISHING = new HashMap<>();
    private static final Map<Path, CreatePending> CREATING = new HashMap<>();
    private static final class CreatePending {
        final String handle; final byte[] hash;
        CreatePending(String handle,byte[] hash) { this.handle=handle; this.hash=hash.clone(); }
    }

    interface IdentityFactory {
        /** Caller assumes ownership and clears this array. */
        byte[] generate() throws Exception;
        /** Synchronous validation of canonical private identity; must not retain input. */
        boolean validate(byte[] identity) throws Exception;
    }
    interface PlainOperation { void run(byte[] plaintext) throws Exception; }
    interface IdentityOperation { void run(byte[] identity) throws Exception; }
    /** Native owner only; true atomically retires the exact node and confirms all callbacks/streams drained.
     *  The owner must remain retired after returning; GUI values cannot supply this proof. */
    interface DrainVerifier { boolean retireExact(String handle,String instanceId,String leaseId) throws Exception; }
    interface Backend {
        /** The key name is the complete provider-specific alias supplied by the core.
         * On failure, clean any newly generated uncommitted key. */
        byte[] create(String alias, byte[] aad, byte[] plaintext) throws Exception;
        /** Invokes the operation exactly once, synchronously; no retained plaintext. */
        void open(String alias, byte[] aad, byte[] envelope, PlainOperation operation) throws Exception;
        /** Idempotent, including a missing key after an interrupted deletion. */
        void delete(String alias) throws Exception;
    }
    interface Writer { void replace(Path root, Path target, byte[] bytes, boolean creating) throws Exception; }
    interface Remover { void remove(Path target) throws Exception; }
    interface DirectorySync { void sync(Path root) throws Exception; }
    static final class PublicRecord {
        final String handle, instanceId;
        PublicRecord(String handle, String instanceId) { this.handle = handle; this.instanceId = instanceId; }
    }
    static final class PendingCreation {
        final String handle, phase;
        PendingCreation(String handle,String phase) { this.handle=handle; this.phase=phase; }
    }
    static final class PendingDeletion {
        final String handle, phase;
        PendingDeletion(String handle,String phase) { this.handle=handle; this.phase=phase; }
    }
    static final class Snapshot {
        final PublicRecord device;
        final PendingCreation creation;
        final PendingDeletion deletion;
        Snapshot(PublicRecord device,PendingCreation creation,PendingDeletion deletion) {
            this.device=device; this.creation=creation; this.deletion=deletion;
        }
    }
    /** Opaque, one-shot native review. Only public handle and state may be displayed. */
    static final class UnreadableReview {
        private final ZeroTierDeviceStoreCore store; private final String nonce;
        private final String reviewedHandle; private final byte[] recordHash;
        private boolean consumed;
        private UnreadableReview(ZeroTierDeviceStoreCore store,String nonce,String handle,byte[] hash) {
            this.store=store; this.nonce=nonce; this.reviewedHandle=handle; this.recordHash=hash.clone();
        }
        String handle() { return reviewedHandle; }
        String state() { return "unreadable"; }
    }
    private static final class Owner {
        final Path path; final FileChannel channel; final FileLock lock;
        Owner(Path path, FileChannel channel, FileLock lock) { this.path=path; this.channel=channel; this.lock=lock; }
    }
    private final Path root, state, intent, creation;
    private final Backend backend;
    private final Writer writer;
    private final Remover remover;
    private final DirectorySync directorySync;
    // Review is in-memory, one per instance, and never serializes its digest.
    private UnreadableReview activeUnreadable; private String activeUnreadableNonce;
    // Only successful authenticated operations on this exact core instance may
    // establish a handle for unreadable-record recovery. Header alone cannot.
    private String verifiedHandle;

    ZeroTierDeviceStoreCore(Path noBackup, Backend backend) throws IOException {
        this(noBackup,backend,ZeroTierDeviceStoreCore::atomicReplace,Files::delete,ZeroTierDeviceStoreCore::syncDirectory);
    }
    ZeroTierDeviceStoreCore(Path noBackup, Backend backend, Writer writer, Remover remover, DirectorySync sync) throws IOException {
        if (backend == null || writer == null || remover == null || sync == null || Files.isSymbolicLink(noBackup)
            || !Files.isDirectory(noBackup,LinkOption.NOFOLLOW_LINKS)) throw new IOException("unsafe storage root");
        root = noBackup.toRealPath(LinkOption.NOFOLLOW_LINKS).resolve("herdr-zerotier-device-v1");
        try { Files.createDirectory(root,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------"))); }
        catch (java.nio.file.FileAlreadyExistsException ignored) { }
        verifyRoot();
        state=root.resolve("device.state"); intent=root.resolve("device.delete"); creation=root.resolve("device.create");
        this.backend=backend; this.writer=writer; this.remover=remover; this.directorySync=sync;
    }
    private void verifyRoot() throws IOException {
        if (Files.isSymbolicLink(root) || !Files.isDirectory(root,LinkOption.NOFOLLOW_LINKS)
            || !Files.getPosixFilePermissions(root,LinkOption.NOFOLLOW_LINKS).equals(PosixFilePermissions.fromString("rwx------"))
            || !Files.getOwner(root,LinkOption.NOFOLLOW_LINKS).equals(Files.getOwner(root.getParent(),LinkOption.NOFOLLOW_LINKS)))
            throw new IOException("unsafe device directory");
    }
    private static String handle(String value) {
        if (value == null || !value.matches("[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}"))
            throw new IllegalArgumentException("invalid device handle");
        return value;
    }
    static String alias(String handle) { return KEYSTORE_ALIAS_PREFIX + handle(handle); }
    private static byte[] aad(String handle) { return ("herdr-zerotier-device:1:" + handle).getBytes(StandardCharsets.US_ASCII); }
    private static void syncDirectory(Path dir) throws IOException {
        try (FileChannel channel=FileChannel.open(dir,StandardOpenOption.READ)) { channel.force(true); }
    }
    private static void atomicReplace(Path root,Path destination,byte[] bytes,boolean creating) throws Exception {
        try (java.util.stream.Stream<Path> list=Files.list(root)) {
            if (list.filter(p -> p.getFileName().toString().startsWith(".pending-") && p.getFileName().toString().endsWith(".tmp"))
                    .limit(MAX_PENDING).count() >= MAX_PENDING) throw new IOException("pending capacity");
        }
        Path temp=Files.createTempFile(root,".pending-",".tmp");
        try {
            try (FileChannel file=FileChannel.open(temp,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS)) {
                ByteBuffer input=ByteBuffer.wrap(bytes); while(input.hasRemaining()) file.write(input); file.force(true);
            }
            if (creating) Files.move(temp,destination,StandardCopyOption.ATOMIC_MOVE);
            else Files.move(temp,destination,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
            syncDirectory(root);
        } finally { Files.deleteIfExists(temp); }
    }
    private boolean exists(Path path) throws IOException {
        try { Files.readAttributes(path,BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS); return true; }
        catch (NoSuchFileException missing) { return false; }
    }
    private boolean existsOrFail() throws IOException {
        if (FINISHING.containsKey(root) || exists(intent)) throw new IOException("deletion requires recovery");
        if (CREATING.containsKey(root) || exists(creation)) throw new IOException("creation requires recovery");
        boolean present=exists(state);
        if (!present && OBSERVED.contains(root)) throw new IOException("device state disappeared");
        if (present) OBSERVED.add(root);
        return present;
    }
    private Owner claim() throws Exception {
        synchronized (GUARD) {
            verifyRoot();
            if (OWNERS.containsKey(root)) throw new IOException("device owner busy");
            Path path=root.resolve(".owner.lock");
            if (Files.isSymbolicLink(path)) throw new IOException("unsafe owner lock");
            FileChannel channel=FileChannel.open(path,StandardOpenOption.CREATE,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS);
            try {
                FileLock lock;
                try { lock=channel.tryLock(); } catch (OverlappingFileLockException busy) { throw new IOException("device owner busy"); }
                if (lock == null) throw new IOException("device owner busy");
                Owner owner=new Owner(root,channel,lock); OWNERS.put(root,owner); return owner;
            } catch (Exception error) { channel.close(); throw error; }
        }
    }
    private static void release(Owner owner) throws Exception {
        synchronized (GUARD) {
            if (OWNERS.get(owner.path) != owner) throw new IOException("device owner changed");
            // Retain the registry claim if either OS release or close fails.
            owner.lock.release(); owner.channel.close(); OWNERS.remove(owner.path);
        }
    }
    private interface Work<T> { T run() throws Exception; }
    private <T> T locked(Work<T> work) throws Exception {
        synchronized (GUARD) {
            verifyRoot(); Path path=root.resolve(".data.lock");
            if (Files.isSymbolicLink(path)) throw new IOException("unsafe data lock");
            try (FileChannel file=FileChannel.open(path,StandardOpenOption.CREATE,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS)) {
                FileLock lock;
                try { lock=file.tryLock(); } catch (OverlappingFileLockException busy) { throw new IOException("device data busy"); }
                if (lock == null) throw new IOException("device data busy");
                try { return work.run(); } finally { lock.release(); }
            }
        }
    }
    private byte[] readRecord() throws IOException {
        if (!Files.isRegularFile(state,LinkOption.NOFOLLOW_LINKS)) throw new IOException("device record unavailable");
        try (InputStream input=Files.newInputStream(state,LinkOption.NOFOLLOW_LINKS)) {
            byte[] record=input.readNBytes(RECORD + 1);
            if (record.length != RECORD || !Arrays.equals(MAGIC,Arrays.copyOf(record,4))) throw new IOException("invalid device record");
            return record;
        }
    }
    private static String recordHandle(byte[] record) { return handle(new String(record,4,UUID_BYTES,StandardCharsets.US_ASCII)); }
    private static void validate(IdentityFactory factory, byte[] identity) throws Exception {
        if (factory == null || identity == null || identity.length != IDENTITY_BYTES) throw new IOException("invalid device identity");
        byte[] copy=identity.clone();
        try {
            if (!factory.validate(copy) || !MessageDigest.isEqual(copy,identity)) throw new IOException("invalid device identity");
        } finally { Arrays.fill(copy,(byte)0); }
    }
    private interface Verified<T> { T read(PublicRecord result,byte[] identity,byte[] record) throws Exception; }
    private <T> T inspect(String expected, IdentityFactory factory, Verified<T> action) throws Exception {
        byte[] record=readRecord(); String actual=recordHandle(record);
        if (expected != null && !actual.equals(handle(expected))) throw new IOException("device identity changed");
        final Object[] result=new Object[1]; final boolean[] active={true}, entered={false}, visited={false}, duplicate={false};
        final Object callbackGuard=new Object(); boolean success=false;
        try {
            backend.open(alias(actual),aad(actual),Arrays.copyOfRange(record,HEADER,record.length),plain -> {
                synchronized(callbackGuard) {
                    if (!active[0] || entered[0]) {
                        duplicate[0]=true; if (plain != null) Arrays.fill(plain,(byte)0);
                        throw new IOException("duplicate or late device plaintext");
                    }
                    entered[0]=true;
                    try {
                        if (plain == null || plain.length != PLAIN) throw new IOException("invalid device plaintext");
                        String instance=handle(new String(plain,0,UUID_BYTES,StandardCharsets.US_ASCII));
                        byte[] identity=Arrays.copyOfRange(plain,UUID_BYTES,plain.length);
                        try { validate(factory,identity); result[0]=action.read(new PublicRecord(actual,instance),identity,record); visited[0]=true; }
                        finally { Arrays.fill(identity,(byte)0); }
                    } finally { if (plain != null) Arrays.fill(plain,(byte)0); }
                }
            });
            synchronized(callbackGuard) {
                active[0]=false;
                if (!visited[0] || duplicate[0]) throw new IOException("device key unavailable");
                success=true;
            }
        } finally {
            if (!success) synchronized(callbackGuard) {
                active[0]=false;
                if (result[0] instanceof byte[]) Arrays.fill((byte[])result[0],(byte)0);
            }
        }
        @SuppressWarnings("unchecked") T value=(T)result[0]; return value;
    }
    private CreatePending readCreateIntent() throws Exception {
        if (!Files.isRegularFile(creation,LinkOption.NOFOLLOW_LINKS)) throw new IOException("invalid creation intent");
        byte[] data;
        try (InputStream in=Files.newInputStream(creation,LinkOption.NOFOLLOW_LINKS)) { data=in.readNBytes(INTENT+1); }
        if (data.length != INTENT || !Arrays.equals(CREATE_MAGIC,Arrays.copyOf(data,4))) throw new IOException("invalid creation intent");
        return new CreatePending(handle(new String(data,4,UUID_BYTES,StandardCharsets.US_ASCII)),Arrays.copyOfRange(data,HEADER,INTENT));
    }
    private CreatePending pendingCreate(boolean hasIntent) throws Exception {
        CreatePending memory=CREATING.get(root), disk=hasIntent ? readCreateIntent() : null;
        if (memory != null && disk != null && (!memory.handle.equals(disk.handle) || !MessageDigest.isEqual(memory.hash,disk.hash)))
            throw new IOException("creation identity changed");
        return disk != null ? disk : memory;
    }
    private void settleCreate(String expected,IdentityFactory factory) throws Exception {
        if (FINISHING.containsKey(root) || exists(intent)) throw new IOException("deletion requires recovery");
        boolean hasIntent=exists(creation);
        CreatePending pending=pendingCreate(hasIntent);
        if (pending == null || !expected.equals(pending.handle)) throw new IOException("creation identity changed");
        if (!exists(state)) throw new IOException("creation outcome unavailable");
        byte[] record=readRecord();
        if (!pending.handle.equals(recordHandle(record)) || !MessageDigest.isEqual(pending.hash,digest(record)))
            throw new IOException("creation identity changed");
        inspect(pending.handle,factory,(identity,secret,verified) -> {
            if (!MessageDigest.isEqual(pending.hash,digest(verified))) throw new IOException("creation identity changed");
            return null;
        });
        directorySync.sync(root);
        CREATING.put(root,pending);
        if (hasIntent) Files.delete(creation);
        directorySync.sync(root);
        CREATING.remove(root); OBSERVED.add(root);
    }
    /** Read-only recovery metadata. Never returns private bytes or ciphertext hashes. */
    PendingCreation pendingStatus() throws Exception {
        return locked(this::pendingCreationLocked);
    }
    private PendingCreation pendingCreationLocked() throws Exception {
            boolean marker=exists(creation);
            if (FINISHING.containsKey(root) || exists(intent)) throw new IOException("deletion requires recovery");
            CreatePending pending=pendingCreate(marker);
            if (pending == null) return null;
            boolean present=exists(state);
            if (present) {
                byte[] record=readRecord();
                if (!pending.handle.equals(recordHandle(record)) || !MessageDigest.isEqual(pending.hash,digest(record)))
                    throw new IOException("creation identity changed");
            }
            return new PendingCreation(pending.handle, marker ? (present ? "record-present" : "record-pending") : "finishing");
    }
    /** Explicitly discard only an exact pending creation with no installed record. */
    void discardPendingCreate(String expected) throws Exception {
        discardPendingCreateInternal(expected,null);
    }
    /** GUI recovery must still match the phase explicitly reviewed by the user. */
    void discardPendingCreateExact(String expected,String expectedPhase) throws Exception {
        requirePhase(expectedPhase,"record-pending","finishing");
        discardPendingCreateInternal(expected,expectedPhase);
    }
    private void requireCreationReview(String expected,String expectedPhase) throws Exception {
        PendingCreation pending=pendingCreationLocked();
        if (pending==null || !expected.equals(pending.handle) || !expectedPhase.equals(pending.phase))
            throw new IOException("creation review changed");
    }
    private static void requirePhase(String phase,String... allowed) throws IOException {
        for (String value:allowed) if (value.equals(phase)) return;
        throw new IOException("invalid recovery phase");
    }
    private void discardPendingCreateInternal(String expected,String expectedPhase) throws Exception {
        handle(expected); Owner owner=claim();
        try { locked(() -> {
            if (expectedPhase!=null) requireCreationReview(expected,expectedPhase);
            boolean marker=exists(creation);
            if (FINISHING.containsKey(root) || exists(intent)) throw new IOException("deletion requires recovery");
            CreatePending pending=pendingCreate(marker);
            if (pending == null || !expected.equals(pending.handle) || exists(state)) throw new IOException("creation identity changed");
            if (marker) {
                CreatePending again=readCreateIntent();
                if (!expected.equals(again.handle) || !MessageDigest.isEqual(pending.hash,again.hash)) throw new IOException("creation identity changed");
            }
            backend.delete(alias(expected));
            if (exists(state)) throw new IOException("creation identity changed");
            CREATING.put(root,pending);
            if (marker) {
                CreatePending again=readCreateIntent();
                if (!expected.equals(again.handle) || !MessageDigest.isEqual(pending.hash,again.hash)) throw new IOException("creation identity changed");
                Files.delete(creation);
            }
            directorySync.sync(root); CREATING.remove(root); OBSERVED.remove(root); return null;
        }); } finally { release(owner); }
    }
    /** Explicit recovery for an installed exact record after uncertain create. */
    PublicRecord recoverPendingCreate(String expected,IdentityFactory factory) throws Exception {
        return recoverPendingCreateInternal(expected,null,factory);
    }
    PublicRecord recoverPendingCreateExact(String expected,String expectedPhase,IdentityFactory factory) throws Exception {
        requirePhase(expectedPhase,"record-present","finishing");
        return recoverPendingCreateInternal(expected,expectedPhase,factory);
    }
    private PublicRecord recoverPendingCreateInternal(String expected,String expectedPhase,IdentityFactory factory) throws Exception {
        handle(expected); Owner owner=claim();
        try { return locked(() -> {
            if (expectedPhase!=null) requireCreationReview(expected,expectedPhase);
            settleCreate(expected,factory);
            directorySync.sync(root);
            PublicRecord result=inspect(expected,factory,(value,secret,record) -> value);
            verifiedHandle=result.handle; return result;
        }); } finally { release(owner); }
    }
    PublicRecord status(IdentityFactory factory) throws Exception {
        return locked(() -> statusLocked(factory));
    }
    private PublicRecord statusLocked(IdentityFactory factory) throws Exception {
            if (!existsOrFail()) { verifiedHandle=null; return null; }
            // A prior process may have died after rename but before directory
            // sync; do not report a usable record until this sync succeeds.
            directorySync.sync(root);
            PublicRecord result=inspect(null,factory,(value,identity,record) -> value);
            verifiedHandle=result.handle; return result;
    }
    /** Read one coherent public state under the same data lock; no recovery. */
    Snapshot snapshot(IdentityFactory factory) throws Exception {
        return locked(() -> {
            boolean creating=CREATING.containsKey(root) || exists(creation);
            boolean deleting=FINISHING.containsKey(root) || exists(intent);
            if (creating && deleting) throw new IOException("conflicting device operations");
            if (creating) return new Snapshot(null,pendingCreationLocked(),null);
            if (deleting) return new Snapshot(null,null,pendingDeletionLocked());
            return new Snapshot(statusLocked(factory),null,null);
        });
    }
    PublicRecord create(IdentityFactory factory) throws Exception {
        Owner owner=claim();
        try { return locked(() -> {
            if (existsOrFail()) throw new IOException("device identity already exists");
            byte[] identity=null, plain=null, record=null;
            String h=UUID.randomUUID().toString(), id=UUID.randomUUID().toString(); boolean keyCreated=false;
            try {
                identity=factory.generate(); validate(factory,identity);
                plain=ByteBuffer.allocate(PLAIN).put(id.getBytes(StandardCharsets.US_ASCII)).put(identity).array();
                byte[] encrypted=backend.create(alias(h),aad(h),plain); keyCreated=true;
                if (encrypted == null || encrypted.length != PLAIN + 28) throw new IOException("invalid encrypted device record");
                record=ByteBuffer.allocate(RECORD).put(MAGIC).put(h.getBytes(StandardCharsets.US_ASCII)).put(encrypted).array();
                CreatePending pending=new CreatePending(h,digest(record));
                byte[] wire=ByteBuffer.allocate(INTENT).put(CREATE_MAGIC).put(h.getBytes(StandardCharsets.US_ASCII)).put(pending.hash).array();
                atomicReplace(root,creation,wire,true);
                writer.replace(root,state,record,true);
                directorySync.sync(root);
                CREATING.put(root,pending);
                Files.delete(creation); directorySync.sync(root); CREATING.remove(root);
                OBSERVED.add(root); verifiedHandle=h;
                return new PublicRecord(h,id);
            } catch (Exception error) {
                boolean absent=false, marker=true;
                try { absent=!exists(state); marker=exists(creation); } catch(Exception uncertain) { error.addSuppressed(uncertain); }
                if (keyCreated && absent) {
                    try {
                        CreatePending pending=marker ? readCreateIntent() : null;
                        if (pending != null && (!h.equals(pending.handle) || record==null || !MessageDigest.isEqual(pending.hash,digest(record))))
                            throw new IOException("creation identity changed");
                        if (exists(state)) throw new IOException("creation identity changed");
                        backend.delete(alias(h));
                        if (pending != null) {
                            CREATING.put(root,pending); Files.delete(creation); directorySync.sync(root); CREATING.remove(root);
                        }
                    } catch(Exception cleanup) { error.addSuppressed(cleanup); }
                }
                if (!absent) OBSERVED.add(root);
                throw error;
            } finally { if (identity != null) Arrays.fill(identity,(byte)0); if (plain != null) Arrays.fill(plain,(byte)0); }
        }); } finally { release(owner); }
    }
    private static final class Acquisition {
        final PublicRecord identity; final byte[] recordHash;
        Acquisition(PublicRecord identity,byte[] recordHash) { this.identity=identity; this.recordHash=recordHash; }
    }
    RuntimeLease acquire(String expected, IdentityFactory factory, DrainVerifier verifier) throws Exception {
        handle(expected); if (factory == null || verifier == null) throw new IOException("native owner unavailable");
        Owner owner=claim();
        try {
            Acquisition value=locked(() -> {
                if (!existsOrFail()) throw new IOException("device identity unavailable");
                directorySync.sync(root);
                Acquisition result=inspect(expected,factory,(verified,identity,record) -> new Acquisition(verified,digest(record)));
                verifiedHandle=result.identity.handle; return result;
            });
            return new RuntimeLease(this,owner,value.identity,value.recordHash,factory,verifier);
        } catch (Throwable error) { try { release(owner); } catch (Exception cleanup) { error.addSuppressed(cleanup); } throw error; }
    }
    static final class RuntimeLease {
        private final ZeroTierDeviceStoreCore store; private final Owner owner; final PublicRecord identity;
        private final IdentityFactory factory; private final DrainVerifier verifier; private final byte[] recordHash;
        private final String leaseId=UUID.randomUUID().toString();
        private boolean used, inUse, retired;
        private RuntimeLease(ZeroTierDeviceStoreCore store,Owner owner,PublicRecord identity,byte[] recordHash,IdentityFactory factory,DrainVerifier verifier) {
            this.store=store; this.owner=owner; this.identity=identity; this.recordHash=recordHash.clone(); this.factory=factory; this.verifier=verifier;
        }
        /** Ephemeral native capability; never expose in a GUI or durable route. */
        String leaseId() { return leaseId; }
        /** Exactly one synchronous native-init callback. A failure retains ownership. */
        void withIdentity(IdentityOperation operation) throws Exception {
            synchronized (this) { if (operation == null || used || inUse || retired) throw new IOException("invalid runtime lease"); used=true; inUse=true; }
            byte[] bytes=null;
            try {
                bytes=store.locked(() -> {
                    if (!store.existsOrFail()) throw new IOException("device identity unavailable");
                    return store.inspect(identity.handle,factory,(actual,secret,record) -> {
                        if (!actual.instanceId.equals(identity.instanceId) || !MessageDigest.isEqual(recordHash,digest(record)))
                            throw new IOException("device identity changed");
                        return secret.clone();
                    });
                });
                // Never hold the per-operation file/process lock while native
                // initialization runs or can reenter an event callback.
                operation.run(bytes);
            } finally { if (bytes != null) Arrays.fill(bytes,(byte)0); synchronized(this) { inUse=false; } }
        }
        /** The originally injected native owner must prove this exact lease is quiescent. */
        void confirmDrained() throws Exception {
            synchronized(this) {
                if (retired || inUse) throw new IOException("runtime lease not drained");
                if (!verifier.retireExact(identity.handle,identity.instanceId,leaseId)) throw new IOException("native node not drained");
                release(owner); retired=true;
            }
        }
    }
    private static byte[] digest(byte[] bytes) throws Exception { return MessageDigest.getInstance("SHA-256").digest(bytes); }
    private byte[] readIntent(String expected) throws Exception {
        if (!Files.isRegularFile(intent,LinkOption.NOFOLLOW_LINKS)) throw new IOException("invalid deletion intent");
        byte[] data;
        try (InputStream in=Files.newInputStream(intent,LinkOption.NOFOLLOW_LINKS)) { data=in.readNBytes(INTENT+1); }
        if (data.length != INTENT || !Arrays.equals(DELETE_MAGIC,Arrays.copyOf(data,4)) ||
            !expected.equals(handle(new String(data,4,UUID_BYTES,StandardCharsets.US_ASCII)))) throw new IOException("invalid deletion intent");
        return Arrays.copyOfRange(data,HEADER,INTENT);
    }
    /** Read-only deletion recovery metadata; exact handle is required to retry forget. */
    PendingDeletion pendingDeletionStatus() throws Exception {
        return locked(this::pendingDeletionLocked);
    }
    private PendingDeletion pendingDeletionLocked() throws Exception {
            if (CREATING.containsKey(root) || exists(creation)) throw new IOException("creation requires recovery");
            boolean marker=exists(intent); String finishing=FINISHING.get(root);
            if (!marker && finishing == null) return null;
            String expected;
            if (marker) {
                if (!Files.isRegularFile(intent,LinkOption.NOFOLLOW_LINKS)) throw new IOException("invalid deletion intent");
                byte[] data;
                try (InputStream in=Files.newInputStream(intent,LinkOption.NOFOLLOW_LINKS)) { data=in.readNBytes(INTENT+1); }
                if (data.length != INTENT || !Arrays.equals(DELETE_MAGIC,Arrays.copyOf(data,4))) throw new IOException("invalid deletion intent");
                expected=handle(new String(data,4,UUID_BYTES,StandardCharsets.US_ASCII));
                if (finishing != null && !finishing.equals(expected)) throw new IOException("deletion identity changed");
                if (exists(state)) requireIntentRecord(expected,Arrays.copyOfRange(data,HEADER,INTENT));
            } else {
                expected=handle(finishing);
                if (exists(state)) throw new IOException("deletion identity changed");
            }
            return new PendingDeletion(expected,marker ? (exists(state) ? "record-present" : "record-removed") : "finishing");
    }
    private void requireIntentRecord(String expected,byte[] hash) throws Exception {
        byte[] current=readRecord();
        if (!expected.equals(recordHandle(current)) || !MessageDigest.isEqual(hash,digest(current))) throw new IOException("device identity changed");
    }
    /**
     * Explicit first step. expectedHandle must match a prior successful
     * authenticated create/status/acquire on this exact core instance. A
     * header, pending intent or GUI-supplied UUID never establishes trust.
     * Failure to decrypt/validate is reported only as unreadable, not as proof
     * of permanent key invalidation. GUI must never receive the review object.
     */
    UnreadableReview beginDiscardUnreadable(String expectedHandle,IdentityFactory factory) throws Exception {
        handle(expectedHandle);
        if (factory == null) throw new IOException("identity validator unavailable");
        Owner owner=claim();
        try { return locked(() -> {
            if (!expectedHandle.equals(verifiedHandle)) throw new IOException("no verified device handle");
            if (!existsOrFail()) throw new IOException("device identity unavailable");
            byte[] original=readRecord();
            if (!expectedHandle.equals(recordHandle(original))) throw new IOException("device identity changed");
            final boolean[] validatorFault={false}, validIdentity={false};
            IdentityFactory checkedFactory=new IdentityFactory() {
                public byte[] generate() throws Exception { throw new IOException("read-only review"); }
                public boolean validate(byte[] value) throws Exception {
                    try { boolean valid=factory.validate(value); if (valid) validIdentity[0]=true; return valid; }
                    catch (Exception unavailable) { validatorFault[0]=true; throw unavailable; }
                }
            };
            boolean readable=true;
            try { inspect(expectedHandle,checkedFactory,(result,identity,record) -> null); }
            catch (Exception unavailable) { readable=false; }
            if (validatorFault[0]) throw new IOException("identity validator unavailable");
            if (readable || validIdentity[0]) throw new IOException("device identity is readable");
            if (!Arrays.equals(original,readRecord())) throw new IOException("device identity changed");
            String nonce=UUID.randomUUID().toString();
            UnreadableReview review=new UnreadableReview(this,nonce,expectedHandle,digest(original));
            activeUnreadable=review; activeUnreadableNonce=nonce;
            return review;
        }); } finally { release(owner); }
    }
    /** A separate explicit confirmation; a review cannot be consumed twice. */
    void confirmDiscardUnreadable(UnreadableReview review) throws Exception {
        synchronized(GUARD) {
            if (review == null || review.store != this || review.consumed || activeUnreadable != review
                || !review.nonce.equals(activeUnreadableNonce)) throw new IOException("unreadable review changed");
            review.consumed=true; activeUnreadable=null; activeUnreadableNonce=null;
        }
        Owner owner=claim();
        try { locked(() -> {
            if (!existsOrFail()) throw new IOException("device identity unavailable");
            requireIntentRecord(review.reviewedHandle,review.recordHash);
            byte[] wire=ByteBuffer.allocate(INTENT).put(DELETE_MAGIC)
                .put(review.reviewedHandle.getBytes(StandardCharsets.US_ASCII)).put(review.recordHash).array();
            atomicReplace(root,intent,wire,true);
            retireIntentRecord(review.reviewedHandle,review.recordHash);
            return null;
        }); } finally { release(owner); }
    }
    private void retireIntentRecord(String expected,byte[] hash) throws Exception {
        boolean present=exists(state);
        if (present) requireIntentRecord(expected,hash);
        backend.delete(alias(expected));
        if (present) { requireIntentRecord(expected,hash); remover.remove(state); directorySync.sync(root); }
        FINISHING.put(root,expected); Files.delete(intent); directorySync.sync(root);
        FINISHING.remove(root); OBSERVED.remove(root);
        if (expected.equals(verifiedHandle)) verifiedHandle=null;
    }
    void forget(String expected,IdentityFactory factory) throws Exception {
        forgetInternal(expected,null,null,factory);
    }
    /** GUI first-step removal: must match authenticated instance, never resume an old deletion. */
    void forgetExact(String expected,String expectedInstance,IdentityFactory factory) throws Exception {
        handle(expectedInstance);
        forgetInternal(expected,expectedInstance,null,factory);
    }
    /** Resume only an existing exact intent; never starts deletion of a normal record. */
    void recoverPendingDeletion(String expected,String expectedPhase) throws Exception {
        requirePhase(expectedPhase,"record-present","record-removed","finishing");
        forgetInternal(expected,null,expectedPhase,null);
    }
    private void forgetInternal(String expected,String expectedInstance,String expectedPhase,IdentityFactory factory) throws Exception {
        handle(expected); Owner owner=claim();
        try { locked(() -> {
            if (CREATING.containsKey(root) || exists(creation)) throw new IOException("creation requires recovery");
            if (expectedPhase!=null) {
                PendingDeletion pending=pendingDeletionLocked();
                if (pending==null || !expected.equals(pending.handle) || !expectedPhase.equals(pending.phase))
                    throw new IOException("deletion review changed");
            }
            String finishing=FINISHING.get(root);
            if (expectedInstance != null && (finishing != null || exists(intent)))
                throw new IOException("deletion requires separate recovery");
            if (!exists(intent) && finishing != null) {
                if (!expected.equals(finishing) || exists(state)) throw new IOException("device identity changed");
                backend.delete(alias(expected)); directorySync.sync(root); FINISHING.remove(root); OBSERVED.remove(root);
                if (expected.equals(verifiedHandle)) verifiedHandle=null;
                return null;
            }
            byte[] hash;
            if (exists(intent)) hash=readIntent(expected);
            else {
                if (expectedPhase!=null) throw new IOException("deletion intent unavailable");
                if (!existsOrFail()) throw new IOException("device identity unavailable");
                byte[] original=readRecord();
                inspect(expected,factory,(result,identity,verified) -> {
                    if (!Arrays.equals(original,verified) || (expectedInstance != null && !expectedInstance.equals(result.instanceId)))
                        throw new IOException("device state conflict");
                    return null;
                });
                if (!Arrays.equals(original,readRecord())) throw new IOException("device state conflict");
                hash=digest(original);
                byte[] wire=ByteBuffer.allocate(INTENT).put(DELETE_MAGIC).put(expected.getBytes(StandardCharsets.US_ASCII)).put(hash).array();
                atomicReplace(root,intent,wire,true);
            }
            retireIntentRecord(expected,hash); return null;
        }); } finally { release(owner); }
    }
}
