package org.herdr.network;
import java.nio.file.attribute.PosixFilePermissions;

import java.io.IOException;
import java.io.ByteArrayOutputStream;
import java.io.DataOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** Temporary JCE fixture only; never loads a real key or network identity. */
public final class TailscaleStateStoreCoreTest {
    static final class MemoryBackend implements TailscaleStateStoreCore.Backend {
        final Map<String,SecretKey> keys = new HashMap<>();
        boolean locked, failSeal, failDelete;
        Runnable duringSeal;
        public byte[] create(String handle,byte[] aad,byte[] payload) throws Exception {
            if (locked || keys.containsKey(handle)) throw new IOException("unavailable");
            KeyGenerator generator = KeyGenerator.getInstance("AES"); generator.init(256);
            keys.put(handle,generator.generateKey()); return seal(handle,aad,payload);
        }
        public byte[] seal(String handle,byte[] aad,byte[] payload) throws Exception {
            if (locked || failSeal || !keys.containsKey(handle)) throw new IOException("key unavailable");
            if (duringSeal != null) { Runnable action = duringSeal; duringSeal = null; action.run(); }
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.ENCRYPT_MODE,keys.get(handle)); cipher.updateAAD(aad);
            byte[] encrypted = cipher.doFinal(payload), iv = cipher.getIV();
            byte[] result = Arrays.copyOf(iv,iv.length + encrypted.length);
            System.arraycopy(encrypted,0,result,iv.length,encrypted.length); return result;
        }
        public void open(String handle,byte[] aad,byte[] envelope,TailscaleStateStoreCore.PayloadOperation operation) throws Exception {
            if (locked || !keys.containsKey(handle)) throw new IOException("key unavailable");
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE,keys.get(handle),new GCMParameterSpec(128,envelope,0,12)); cipher.updateAAD(aad);
            byte[] payload = cipher.doFinal(envelope,12,envelope.length-12);
            try { operation.run(payload); } finally { Arrays.fill(payload,(byte)0); }
        }
        public void delete(String handle) throws Exception {
            if (failDelete) throw new IOException("injected key deletion failure"); keys.remove(handle);
        }
    }
    // Predictable test-only key allows independent JVMs to exercise the real
    // filesystem lock. Never used by the Android implementation.
    static final class SharedFixtureBackend implements TailscaleStateStoreCore.Backend {
        private SecretKey key(String handle) throws Exception {
            byte[] bytes = java.security.MessageDigest.getInstance("SHA-256").digest(("isolated-fixture:"+handle).getBytes(StandardCharsets.UTF_8));
            return new javax.crypto.spec.SecretKeySpec(bytes,"AES");
        }
        public byte[] create(String handle,byte[] aad,byte[] payload) throws Exception { return seal(handle,aad,payload); }
        public byte[] seal(String handle,byte[] aad,byte[] payload) throws Exception {
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.ENCRYPT_MODE,key(handle)); cipher.updateAAD(aad);
            byte[] encrypted = cipher.doFinal(payload), iv = cipher.getIV(), out = Arrays.copyOf(iv,iv.length+encrypted.length);
            System.arraycopy(encrypted,0,out,iv.length,encrypted.length); return out;
        }
        public void open(String handle,byte[] aad,byte[] envelope,TailscaleStateStoreCore.PayloadOperation operation) throws Exception {
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.DECRYPT_MODE,key(handle),new GCMParameterSpec(128,envelope,0,12));
            cipher.updateAAD(aad); byte[] plain = cipher.doFinal(envelope,12,envelope.length-12);
            try { operation.run(plain); } finally { Arrays.fill(plain,(byte)0); }
        }
        public void delete(String handle) { }
    }
    interface Checked { void run() throws Exception; }
    static int checks;
    static void check(boolean value,String message) { checks++; if (!value) throw new AssertionError(message); }
    static void fails(Checked work,String message) throws Exception {
        checks++; try { work.run(); } catch (Exception expected) { return; } throw new AssertionError(message);
    }
    static void failsNotMissing(Checked work,String message) throws Exception {
        checks++; try { work.run(); } catch (TailscaleStateStoreCore.NotFound wrong) { throw new AssertionError(message + " misreported as missing",wrong); }
        catch (Exception expected) { return; } throw new AssertionError(message);
    }
    static void missing(Checked work) throws Exception {
        checks++; try { work.run(); } catch (TailscaleStateStoreCore.NotFound expected) { return; }
        throw new AssertionError("expected distinct missing key");
    }
    static String profile(int n) { return String.format("%032x",n); }
    static byte[] bytes(String s) { return s.getBytes(StandardCharsets.UTF_8); }
    public static void main(String[] args) throws Exception {
        if (args.length == 3 && args[0].equals("binary-reopen")) {
            TailscaleStateStoreCore reopened = new TailscaleStateStoreCore(Paths.get(args[1]),new SharedFixtureBackend());
            if (!Arrays.equals(reopened.readStateBytes(profile(1),args[2],new byte[]{(byte)0xff,0,1}),bytes("persistent")))
                throw new AssertionError("binary key did not survive JVM restart");
            return;
        }
        if (args.length == 4 && args[0].equals("worker")) {
            TailscaleStateStoreCore worker = new TailscaleStateStoreCore(Paths.get(args[1]),new SharedFixtureBackend());
            for (int i=0;i<8;i++) worker.writeState(profile(1),args[2],"process/"+args[3]+"/"+i,bytes("v"+i));
            return;
        }
        Path base = Files.createTempDirectory("tailscale-state-jvm-");
        Files.setPosixFilePermissions(base, PosixFilePermissions.fromString("rwxrwx--x"));
        try { run(base); check(Files.getPosixFilePermissions(base).equals(PosixFilePermissions.fromString("rwxrwx--x")), "framework base remains 0771"); System.out.println("PASS: " + checks + " checks (temporary JCE keys; no AndroidKeyStore/device/network)"); }
        finally { try (java.util.stream.Stream<Path> paths = Files.walk(base)) {
            paths.sorted(Comparator.reverseOrder()).forEach(path -> { try { Files.deleteIfExists(path); } catch (Exception e) { throw new RuntimeException(e); } });
        } }
    }
    // Install a legacy-format UTF-8 record independently of the new encoder.
    static void installFixture(Path base, MemoryBackend backend, String profile, TailscaleStateStoreCore.Result id,
            byte[][] keys, byte[][] values) throws Exception {
        ByteArrayOutputStream plain = new ByteArrayOutputStream();
        try (DataOutputStream out = new DataOutputStream(plain)) {
            out.write(bytes(id.instanceId)); out.writeInt(keys.length);
            for (int i = 0; i < keys.length; i++) {
                out.writeInt(keys[i].length); out.write(keys[i]); out.writeInt(values[i].length); out.write(values[i]);
            }
        }
        byte[] aad = bytes("herdr-tailscale-state:1:tailscale:" + profile + ":" + id.handle);
        byte[] envelope = backend.seal(id.handle,aad,plain.toByteArray());
        ByteArrayOutputStream record = new ByteArrayOutputStream();
        record.write(new byte[]{'H','T','S',1}); record.write(bytes(id.handle)); record.write(envelope);
        Files.write(base.resolve("herdr-tailscale-state-v1").resolve(profile + ".state"),record.toByteArray());
    }
    static void binaryKeys(Path base) throws Exception {
        Path fixture = base.resolve("binary-keys"); Files.createDirectory(fixture);
        MemoryBackend backend = new MemoryBackend();
        TailscaleStateStoreCore store = new TailscaleStateStoreCore(fixture,backend);
        String profile = profile(900); TailscaleStateStoreCore.Result id = store.create(profile);
        installFixture(fixture,backend,profile,id,new byte[][]{bytes("节点/🔒\u0000"),bytes("")},
            new byte[][]{bytes("legacy"),bytes("empty")});
        check(Arrays.equals(store.readStateBytes(profile,id.handle,bytes("节点/🔒\u0000")),bytes("legacy")),"legacy UTF8 record to binary API");
        check(Arrays.equals(store.readState(profile,id.handle,""),bytes("empty")),"legacy empty string record");
        store.writeState(profile,id.handle,"string/é",bytes("from-string"));
        check(Arrays.equals(store.readStateBytes(profile,id.handle,bytes("string/é")),bytes("from-string")),"string write binary read");
        store.writeStateBytes(profile,id.handle,bytes("string/é"),bytes("from-bytes"));
        check(Arrays.equals(store.readState(profile,id.handle,"string/é"),bytes("from-bytes")),"binary write string read");
        byte[] binary = {(byte)0xff,0,1}, value = {4,5};
        store.writeStateBytes(profile,id.handle,binary,value); binary[0] = 0; value[0] = 0;
        store.writeStateBytes(profile,id.handle,new byte[]{0},bytes("nul"));
        store.writeStateBytes(profile,id.handle,new byte[]{(byte)0xff,0,2},bytes("different"));
        store.writeStateBytes(profile,id.handle,new byte[0],new byte[0]);
        TailscaleStateStoreCore reopened = new TailscaleStateStoreCore(fixture,backend);
        check(Arrays.equals(reopened.readStateBytes(profile,id.handle,new byte[]{(byte)0xff,0,1}),new byte[]{4,5}),"invalid UTF8 key and inputs detached after reopen");
        check(Arrays.equals(reopened.readStateBytes(profile,id.handle,new byte[]{0}),bytes("nul")),"NUL distinct");
        check(Arrays.equals(reopened.readStateBytes(profile,id.handle,new byte[]{(byte)0xff,0,2}),bytes("different")),"binary keys distinct");
        check(reopened.readState(profile,id.handle,"").length == 0,"empty key and empty value across APIs");
        byte[] max = new byte[TailscaleStateStoreCore.MAX_KEY]; Arrays.fill(max,(byte)0xff);
        store.writeStateBytes(profile,id.handle,max,bytes("max"));
        check(Arrays.equals(reopened.readStateBytes(profile,id.handle,max),bytes("max")),"maximum key accepted");
        fails(() -> store.writeStateBytes(profile,id.handle,new byte[TailscaleStateStoreCore.MAX_KEY+1],new byte[0]),"binary key bound");
        fails(() -> store.readStateBytes(profile,id.handle,null),"null key rejected");
        store.writeStateBytes(profile,id.handle,new byte[]{0},null);
        missing(() -> reopened.readStateBytes(profile,id.handle,new byte[]{0}));
        installFixture(fixture,backend,profile,id,new byte[][]{new byte[]{(byte)0xff},new byte[]{(byte)0xff}},
            new byte[][]{bytes("a"),bytes("b")});
        failsNotMissing(() -> reopened.readStateBytes(profile,id.handle,new byte[]{(byte)0xff}),"duplicate binary keys rejected");
        installFixture(fixture,backend,profile,id,new byte[][]{new byte[TailscaleStateStoreCore.MAX_KEY+1]},new byte[][]{new byte[0]});
        failsNotMissing(() -> reopened.status(profile),"oversize stored key rejected");
    }
    static void run(Path base) throws Exception {
        binaryKeys(base);
        MemoryBackend backend = new MemoryBackend();
        TailscaleStateStoreCore first = new TailscaleStateStoreCore(base,backend);
        TailscaleStateStoreCore second = new TailscaleStateStoreCore(base,backend);
        String p = profile(1);
        check(first.status(p) == null,"new profile absent");
        TailscaleStateStoreCore.Result created = first.create(p);
        check(!created.handle.equals(created.instanceId),"independent identities");
        check(second.status(p).handle.equals(created.handle),"restart reference");
        missing(() -> first.readState(p,created.handle,""));
        first.writeState(p,created.handle,"",new byte[0]);
        check(second.readState(p,created.handle,"").length == 0,"empty key and value retained");
        first.writeState(p,created.handle,"/current/user",bytes("fake-state"));
        first.writeState(p,created.handle,"节点/🔒\u0000",new byte[]{0,1,(byte)255});
        check(Arrays.equals(second.readState(p,created.handle,"节点/🔒\u0000"),new byte[]{0,1,(byte)255}),"opaque key and bytes");
        first.writeState(p,created.handle,"",null);
        missing(() -> first.readState(p,created.handle,""));
        check(Arrays.equals(first.readState(p,created.handle,"/current/user"),bytes("fake-state")),"unrelated key preserved");
        first.writeState(p,created.handle,"never-there",null);
        fails(() -> first.readState(p,UUID.randomUUID().toString(),"/current/user"),"wrong handle");
        fails(() -> first.writeState(p,created.handle,"x".repeat(1025),new byte[0]),"key bound");
        fails(() -> first.writeState(p,created.handle,"bad\ud800",new byte[0]),"malformed UTF16 key");
        fails(() -> first.writeState(p,created.handle,"large",new byte[TailscaleStateStoreCore.MAX_VALUE+1]),"value bound");
        byte[] detached = first.readState(p,created.handle,"/current/user"); detached[0] = 0;
        check(first.readState(p,created.handle,"/current/user")[0] == 'f',"returned bytes detached");
        Path root = base.resolve("herdr-tailscale-state-v1"), path = root.resolve(p + ".state");
        byte[] plain = bytes("fake-state");
        check(!new String(Files.readAllBytes(path),StandardCharsets.ISO_8859_1).contains(new String(plain,StandardCharsets.US_ASCII)),"encrypted bytes");
        String runtime = first.runtimeDirectory(p,created.handle);
        check(Paths.get(runtime).startsWith(root.resolve("runtime")) && Files.isDirectory(Paths.get(runtime)),"native runtime directory");
        java.util.Set<java.nio.file.attribute.PosixFilePermission> privateMode = java.nio.file.attribute.PosixFilePermissions.fromString("rwx------");
        for (Path directory : new Path[] {root, root.resolve("runtime"), Paths.get(runtime)})
            check(Files.getPosixFilePermissions(directory).equals(privateMode), "created directory mode 0700");
        for (Path directory : new Path[] {root, root.resolve("runtime"), Paths.get(runtime)}) {
            Files.setPosixFilePermissions(directory, PosixFilePermissions.fromString("rwxr-x---"));
            fails(() -> first.runtimeDirectory(p,created.handle), "existing broad directory rejected");
            check(!Files.getPosixFilePermissions(directory).equals(privateMode), "unsafe directory not chmodded");
            Files.setPosixFilePermissions(directory, privateMode);
        }
        fails(() -> first.runtimeDirectory(p,UUID.randomUUID().toString()),"runtime handle guard");
        byte[] saved = Files.readAllBytes(path), tampered = saved.clone(); tampered[tampered.length-1] ^= 1; Files.write(path,tampered);
        fails(() -> first.status(p),"tampered is not missing");
        failsNotMissing(() -> first.readState(p,created.handle,"/current/user"),"tampered read"); Files.write(path,saved);
        Path copied = root.resolve(profile(2) + ".state"); Files.copy(path,copied);
        fails(() -> first.status(profile(2)),"profile AAD"); Files.delete(copied);
        SecretKey removed = backend.keys.remove(created.handle);
        fails(() -> first.status(p),"missing key not absent"); fails(() -> first.create(p),"missing key not recreated");
        failsNotMissing(() -> first.readState(p,created.handle,"/current/user"),"missing cryptographic key");
        backend.keys.put(created.handle,removed); backend.locked = true;
        fails(() -> first.status(p),"locked not absent"); failsNotMissing(() -> first.readState(p,created.handle,"/current/user"),"locked read");
        fails(() -> first.writeState(p,created.handle,"x",new byte[0]),"locked not write"); backend.locked = false;
        TailscaleStateStoreCore failing = new TailscaleStateStoreCore(base,backend,(r,d,record,creating) -> { throw new IOException("injected atomic failure"); });
        fails(() -> failing.writeState(p,created.handle,"atomic",bytes("not committed")),"atomic write failure");
        missing(() -> first.readState(p,created.handle,"atomic"));
        check(Arrays.equals(Files.readAllBytes(path),saved),"atomic failure retained bytes");
        int beforeCreate = backend.keys.size();
        fails(() -> failing.create(profile(3)),"create fails before install");
        check(first.status(profile(3)) == null && backend.keys.size() == beforeCreate,"pre-install failure removes generated key");
        TailscaleStateStoreCore uncertain = new TailscaleStateStoreCore(base,backend,(r,d,record,creating) -> {
            if (!creating) throw new IOException("unexpected update");
            Files.write(d,record,StandardOpenOption.CREATE_NEW); throw new IOException("after install");
        });
        fails(() -> uncertain.create(profile(4)),"create failure after install");
        TailscaleStateStoreCore.Result uncertainResult = first.status(profile(4));
        check(uncertainResult != null && backend.keys.containsKey(uncertainResult.handle),"unknown create preserves record and key");
        fails(() -> first.create(profile(4)),"unknown create is not replayed");
        first.delete(profile(4),uncertainResult.handle);
        backend.failSeal = true; fails(() -> first.writeState(p,created.handle,"seal",bytes("x")),"seal failure"); backend.failSeal = false;
        check(Arrays.equals(Files.readAllBytes(path),saved),"seal failure retained bytes");
        byte[] alien = saved.clone(); alien[alien.length-1] ^= 1;
        backend.duringSeal = () -> { try { Files.write(path,alien); } catch (IOException e) { throw new RuntimeException(e); } };
        fails(() -> first.writeState(p,created.handle,"conflict",bytes("x")),"CAS conflict");
        check(Arrays.equals(Files.readAllBytes(path),alien),"CAS never overwrites changed record"); Files.write(path,saved);
        TailscaleStateStoreCore uncertainUpdate = new TailscaleStateStoreCore(base,backend,(r,d,record,creating) -> {
            Path pending = Files.createTempFile(r,"fixture-", ".tmp"); Files.write(pending,record);
            Files.move(pending,d,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
            throw new IOException("after replacement");
        });
        fails(() -> uncertainUpdate.writeState(p,created.handle,"after-replace",bytes("observed")),"unknown write result");
        check(Arrays.equals(first.readState(p,created.handle,"after-replace"),bytes("observed")),"installed update retained after reported error");
        first.writeState(p,created.handle,"after-replace",null);
        // Different writer instances share the same process and OS lock.
        ExecutorService pool = Executors.newFixedThreadPool(12); CountDownLatch start = new CountDownLatch(1);
        List<Future<?>> tasks = new ArrayList<>();
        for (int i=0;i<48;i++) { final int n = i; tasks.add(pool.submit(() -> {
            start.await(); (n % 2 == 0 ? first : second).writeState(p,created.handle,"worker/"+n,bytes("v"+n)); return null;
        })); }
        start.countDown(); for (Future<?> task : tasks) task.get(); pool.shutdown();
        for (int i=0;i<48;i++) check(Arrays.equals(first.readState(p,created.handle,"worker/"+i),bytes("v"+i)),"concurrent update "+i);
        for (int i=0;i<48;i++) first.writeState(p,created.handle,"worker/"+i,null);
        for (int i=0;i<254;i++) first.writeState(p,created.handle,"slot/"+i,new byte[0]);
        fails(() -> first.writeState(p,created.handle,"overflow",new byte[0]),"key capacity");
        missing(() -> first.readState(p,created.handle,"overflow"));
        check(Arrays.equals(first.readState(p,created.handle,"/current/user"),bytes("fake-state")),"capacity no eviction");
        for (int i=0;i<254;i++) first.writeState(p,created.handle,"slot/"+i,null);
        byte[] block = new byte[TailscaleStateStoreCore.MAX_VALUE]; Arrays.fill(block,(byte)7);
        int inserted = 0;
        try { for (;inserted<20;inserted++) first.writeState(p,created.handle,"block/"+inserted,block); }
        catch (IOException expected) { }
        check(inserted > 0 && inserted < 20,"total plaintext bound");
        final int missingBlock = inserted;
        missing(() -> first.readState(p,created.handle,"block/"+missingBlock));
        check(first.readState(p,created.handle,"block/0").length == block.length,"total bound no eviction");
        for (int i=0;i<inserted;i++) first.writeState(p,created.handle,"block/"+i,null);
        fails(() -> first.delete(p,UUID.randomUUID().toString()),"wrong delete handle");
        first.delete(p,created.handle); check(!backend.keys.containsKey(created.handle),"delete destroys key");
        check(!Files.exists(Paths.get(runtime)),"empty old runtime retired");
        check(first.status(p) == null,"deleted identity absent");
        TailscaleStateStoreCore.Result recreated = first.create(p);
        check(!created.handle.equals(recreated.handle) && !created.instanceId.equals(recreated.instanceId),"rebuild new identity");
        missing(() -> first.readState(p,recreated.handle,"/current/user"));
        fails(() -> first.readState(p,created.handle,"/current/user"),"old handle cannot read new identity");
        String rebuiltRuntime = first.runtimeDirectory(p,recreated.handle);
        check(!runtime.equals(rebuiltRuntime),"runtime dir changes on rebuild");
        Files.write(Paths.get(rebuiltRuntime).resolve("synthetic-tsnet-output"),new byte[]{1});
        first.delete(p,recreated.handle);
        check(Files.exists(Paths.get(rebuiltRuntime).resolve("synthetic-tsnet-output")),"nonempty old runtime retained");
        TailscaleStateStoreCore.Result third = first.create(p);
        check(!third.handle.equals(recreated.handle),"repeated create still new handle");
        Files.delete(path); fails(() -> first.status(p),"previously observed file missing is not absent");
        failsNotMissing(() -> first.readState(p,third.handle,"/current/user"),"missing identity file");
        fails(() -> first.create(p),"missing observed identity not silently rebuilt");
        // Durable delete intent: key deleted but unlink failed. A fresh core
        // must retry exactly that original handle without decrypting it again.
        Path recoveryBase = base.resolve("delete-recovery"); Files.createDirectory(recoveryBase);
        TailscaleStateStoreCore recover = new TailscaleStateStoreCore(recoveryBase,backend);
        String recoveryProfile = profile(80);
        TailscaleStateStoreCore.Result doomed = recover.create(recoveryProfile);
        TailscaleStateStoreCore unlinkFail = new TailscaleStateStoreCore(recoveryBase,backend,(TailscaleStateStoreCore.RecordRemover) record -> { throw new IOException("injected unlink failure"); });
        fails(() -> unlinkFail.delete(recoveryProfile,doomed.handle),"delete unlink failure");
        check(!backend.keys.containsKey(doomed.handle),"key deletion occurred before injected unlink failure");
        fails(() -> recover.status(recoveryProfile),"pending deletion is not absent");
        fails(() -> recover.create(recoveryProfile),"pending deletion blocks recreate");
        fails(() -> recover.delete(recoveryProfile,UUID.randomUUID().toString()),"wrong handle cannot resume delete");
        TailscaleStateStoreCore reopened = new TailscaleStateStoreCore(recoveryBase,backend);
        reopened.delete(recoveryProfile,doomed.handle);
        check(reopened.status(recoveryProfile) == null,"new instance resumes exact delete");
        TailscaleStateStoreCore.Result successor = reopened.create(recoveryProfile);
        check(!successor.handle.equals(doomed.handle),"successor receives new handle");
        fails(() -> reopened.delete(recoveryProfile,doomed.handle),"old handle cannot delete successor");
        check(reopened.status(recoveryProfile).handle.equals(successor.handle),"successor survives old handle");

        // The key deletion itself can fail; the persisted intent blocks all
        // other operations and retry keeps the same handle.
        String keyFailureProfile = profile(81);
        TailscaleStateStoreCore.Result keyFailure = reopened.create(keyFailureProfile);
        backend.failDelete = true; fails(() -> reopened.delete(keyFailureProfile,keyFailure.handle),"key deletion failure");
        check(backend.keys.containsKey(keyFailure.handle),"failed key deletion retained key");
        fails(() -> reopened.status(keyFailureProfile),"intent blocks status after key failure");
        backend.failDelete = false; new TailscaleStateStoreCore(recoveryBase,backend).delete(keyFailureProfile,keyFailure.handle);
        check(reopened.status(keyFailureProfile) == null,"key deletion retry recovered");

        // Retry after unlink succeeded but its caller observed failure.
        String absentProfile = profile(82);
        TailscaleStateStoreCore.Result absent = reopened.create(absentProfile);
        TailscaleStateStoreCore afterUnlink = new TailscaleStateStoreCore(recoveryBase,backend,(TailscaleStateStoreCore.RecordRemover) record -> {
            Files.delete(record); throw new IOException("after unlink");
        });
        fails(() -> afterUnlink.delete(absentProfile,absent.handle),"uncertain unlink result");
        new TailscaleStateStoreCore(recoveryBase,backend).delete(absentProfile,absent.handle);
        check(reopened.status(absentProfile) == null,"absent original record completes intent");

        // The final intent unlink can succeed while its directory fsync fails.
        // Same-process retry must retain and check the exact finishing handle.
        String syncProfile = profile(85);
        TailscaleStateStoreCore.Result syncId = reopened.create(syncProfile);
        String syncRuntime = reopened.runtimeDirectory(syncProfile,syncId.handle);
        java.util.concurrent.atomic.AtomicInteger syncCalls = new java.util.concurrent.atomic.AtomicInteger();
        TailscaleStateStoreCore finalSync = new TailscaleStateStoreCore(recoveryBase,backend,
            (TailscaleStateStoreCore.RecordRemover) Files::delete, directory -> {
                if (syncCalls.incrementAndGet() == 2) throw new IOException("injected final directory sync failure");
                try (java.nio.channels.FileChannel fd = java.nio.channels.FileChannel.open(directory,StandardOpenOption.READ)) { fd.force(true); }
            });
        fails(() -> finalSync.delete(syncProfile,syncId.handle),"final intent sync failure");
        check(!Files.exists(recoveryBase.resolve("herdr-tailscale-state-v1").resolve(syncProfile+".delete")),"intent unlinked before injected failure");
        fails(() -> reopened.status(syncProfile),"finishing deletion is not empty");
        fails(() -> reopened.create(syncProfile),"finishing deletion blocks recreate");
        fails(() -> reopened.delete(syncProfile,UUID.randomUUID().toString()),"finishing deletion requires same handle");
        new TailscaleStateStoreCore(recoveryBase,backend).delete(syncProfile,syncId.handle);
        check(reopened.status(syncProfile) == null,"final sync retry completed");
        check(!Files.exists(Paths.get(syncRuntime)),"final sync retry retires empty runtime");

        // A stale intent must check the original ciphertext before touching
        // either old or replacement key, even when given the old handle.
        String changedProfile = profile(83);
        TailscaleStateStoreCore.Result oldIdentity = reopened.create(changedProfile);
        backend.failDelete = true; fails(() -> reopened.delete(changedProfile,oldIdentity.handle),"leave old intent and key");
        backend.failDelete = false;
        Path replacementBase = base.resolve("replacement-fixture"); Files.createDirectory(replacementBase);
        TailscaleStateStoreCore replacement = new TailscaleStateStoreCore(replacementBase,backend);
        TailscaleStateStoreCore.Result newIdentity = replacement.create(changedProfile);
        Path oldPath = recoveryBase.resolve("herdr-tailscale-state-v1").resolve(changedProfile+".state");
        Path newPath = replacementBase.resolve("herdr-tailscale-state-v1").resolve(changedProfile+".state");
        byte[] newBytes = Files.readAllBytes(newPath); Files.write(oldPath,newBytes);
        fails(() -> reopened.delete(changedProfile,oldIdentity.handle),"old intent rejects changed record");
        check(backend.keys.containsKey(oldIdentity.handle) && backend.keys.containsKey(newIdentity.handle),"hash mismatch preserves both keys");
        check(Arrays.equals(Files.readAllBytes(oldPath),newBytes),"hash mismatch preserves replacement bytes");
        fails(() -> reopened.status(changedProfile),"stale intent blocks status");

        Path badIntentBase = base.resolve("bad-intent"); Files.createDirectory(badIntentBase);
        TailscaleStateStoreCore badIntent = new TailscaleStateStoreCore(badIntentBase,backend);
        String badIntentProfile = profile(86); TailscaleStateStoreCore.Result badIntentId = badIntent.create(badIntentProfile);
        Path badIntentRoot = badIntentBase.resolve("herdr-tailscale-state-v1"), badIntentPath = badIntentRoot.resolve(badIntentProfile+".delete");
        Files.write(badIntentPath,new byte[105]);
        fails(() -> badIntent.status(badIntentProfile),"oversized intent blocks status");
        fails(() -> badIntent.delete(badIntentProfile,badIntentId.handle),"oversized intent blocks deletion");
        check(backend.keys.containsKey(badIntentId.handle),"oversized intent keeps key");
        Files.delete(badIntentPath); Path symlinkTarget = base.resolve("intent-target"); Files.write(symlinkTarget,new byte[]{4,5});
        Files.createSymbolicLink(badIntentPath,symlinkTarget);
        fails(() -> badIntent.status(badIntentProfile),"intent symlink blocks status");
        fails(() -> badIntent.delete(badIntentProfile,badIntentId.handle),"intent symlink blocks deletion");
        check(backend.keys.containsKey(badIntentId.handle) && Arrays.equals(Files.readAllBytes(symlinkTarget),new byte[]{4,5}),"intent symlink keeps key and target");

        Path pendingBase = base.resolve("pending-cap"); Files.createDirectory(pendingBase);
        TailscaleStateStoreCore pendingStore = new TailscaleStateStoreCore(pendingBase,backend);
        Path pendingRoot = pendingBase.resolve("herdr-tailscale-state-v1");
        for (int i=0;i<32;i++) Files.write(pendingRoot.resolve(".pending-"+i+".tmp"),new byte[]{1});
        int beforePending = backend.keys.size();
        fails(() -> pendingStore.create(profile(84)),"pending temp capacity");
        check(backend.keys.size() == beforePending && Files.exists(pendingRoot.resolve(".pending-0.tmp")),"pending cap neither leaks key nor evicts files");

        Path processBase = base.resolve("process-fixture"); Files.createDirectory(processBase);
        TailscaleStateStoreCore processStore = new TailscaleStateStoreCore(processBase,new SharedFixtureBackend());
        TailscaleStateStoreCore.Result processId = processStore.create(profile(1));
        processStore.writeStateBytes(profile(1),processId.handle,new byte[]{(byte)0xff,0,1},bytes("persistent"));
        List<Process> children = new ArrayList<>();
        String java = Paths.get(System.getProperty("java.home"),"bin","java").toString();
        Process binaryReopen = new ProcessBuilder(java,"-cp",System.getProperty("java.class.path"),
            TailscaleStateStoreCoreTest.class.getName(),"binary-reopen",processBase.toString(),processId.handle)
            .redirectErrorStream(true).start();
        check(binaryReopen.waitFor(30,TimeUnit.SECONDS),"binary reopen child terminates");
        String binaryOutput = new String(binaryReopen.getInputStream().readAllBytes(),StandardCharsets.UTF_8);
        check(binaryReopen.exitValue() == 0,"binary reopen child failed: "+binaryOutput);
        for (int i=0;i<4;i++) children.add(new ProcessBuilder(java,"-cp",System.getProperty("java.class.path"),
            TailscaleStateStoreCoreTest.class.getName(),"worker",processBase.toString(),processId.handle,Integer.toString(i))
            .redirectErrorStream(true).start());
        for (Process child : children) {
            check(child.waitFor(30,TimeUnit.SECONDS),"child process terminates");
            String output = new String(child.getInputStream().readAllBytes(),StandardCharsets.UTF_8);
            check(child.exitValue() == 0,"child process failed: "+output);
        }
        for (int i=0;i<4;i++) for (int j=0;j<8;j++)
            check(Arrays.equals(processStore.readState(profile(1),processId.handle,"process/"+i+"/"+j),bytes("v"+j)),"cross-process update");
        Path capBase = base.resolve("runtime-cap-fixture"); Files.createDirectory(capBase);
        TailscaleStateStoreCore cap = new TailscaleStateStoreCore(capBase,backend);
        TailscaleStateStoreCore.Result capId = cap.create(profile(9));
        Path capRuntime = capBase.resolve("herdr-tailscale-state-v1/runtime"); Files.createDirectory(capRuntime, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        for (int i=0;i<32;i++) Files.createDirectory(capRuntime.resolve("retained-"+i));
        fails(() -> cap.runtimeDirectory(profile(9),capId.handle),"retained runtime cap");
        check(Files.exists(capRuntime.resolve("retained-0")),"runtime cap no eviction");
        Files.delete(capRuntime.resolve("retained-0"));
        check(Files.isDirectory(Paths.get(cap.runtimeDirectory(profile(9),capId.handle))),"runtime cap recover after explicit cleanup");
        for (int i=10;i<42;i++) first.create(profile(i));
        fails(() -> first.create(profile(42)),"32 profile cap");
    }
}
