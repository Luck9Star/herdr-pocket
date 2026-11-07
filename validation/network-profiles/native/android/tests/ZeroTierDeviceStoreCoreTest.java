package org.herdr.network;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.security.SecureRandom;
import java.util.Arrays;
import java.util.Comparator;
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;

/** Synthetic JCE and identity only; never uses AndroidKeyStore or a real node. */
public final class ZeroTierDeviceStoreCoreTest {
    private static int checks;
    private static void check(boolean value,String message) { if(!value) throw new AssertionError(message); checks++; }
    interface Attempt { void run() throws Exception; }
    private static void rejects(Attempt work,String message) throws Exception {
        try { work.run(); } catch (Exception expected) { checks++; return; }
        throw new AssertionError(message);
    }
    private static boolean wiped(byte[] bytes) { if(bytes == null) return false; for(byte b:bytes) if(b!=0) return false; return true; }
    private static final class Factory implements ZeroTierDeviceStoreCore.IdentityFactory {
        int generated, validated, size=270; boolean valid=true, mutate=false, throwValidation=false, throwError=false; byte[] lastGenerated,lastValidated;
        public byte[] generate() { generated++; lastGenerated=new byte[size]; Arrays.fill(lastGenerated,(byte)'X'); if(size>1) lastGenerated[1]=(byte)generated; return lastGenerated; }
        public boolean validate(byte[] input) throws Exception { validated++; lastValidated=input; if(throwError) throw new AssertionError("synthetic validator error"); if(throwValidation) throw new IOException("synthetic validator failure"); if(mutate) input[2]++; return valid && input.length==270 && input[0]=='X'; }
    }
    private static final class Proof implements ZeroTierDeviceStoreCore.DrainVerifier {
        String handle, instance, lease; boolean allow, fail;
        public boolean retireExact(String h,String i,String l) throws Exception {
            if(fail) throw new IOException("synthetic verifier failure");
            return allow && h.equals(handle) && i.equals(instance) && l.equals(lease);
        }
        void bind(ZeroTierDeviceStoreCore.RuntimeLease owner) {
            handle=owner.identity.handle; instance=owner.identity.instanceId; lease=owner.leaseId();
        }
    }
    private static ZeroTierDeviceStoreCore.RuntimeLease acquire(ZeroTierDeviceStoreCore core,String handle,Factory factory,Proof proof) throws Exception {
        ZeroTierDeviceStoreCore.RuntimeLease lease=core.acquire(handle,factory,proof); proof.bind(lease); return lease;
    }
    private static final class JceBackend implements ZeroTierDeviceStoreCore.Backend {
        private static final byte[] KEY = new byte[32];
        final Set<String> revoked=new HashSet<>(); boolean failDelete, failOpen, duplicateOpen, wrongKey; int deletes; byte[] lastPlain, duplicateA, duplicateB;
        public byte[] create(String handle,byte[] aad,byte[] plaintext) throws Exception {
            revoked.remove(handle); byte[] iv=new byte[12]; new SecureRandom().nextBytes(iv);
            Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.ENCRYPT_MODE,new SecretKeySpec(KEY,"AES"),new GCMParameterSpec(128,iv));
            cipher.updateAAD(aad); byte[] enc=cipher.doFinal(plaintext); return ByteBuffer.allocate(iv.length+enc.length).put(iv).put(enc).array();
        }
        public void open(String handle,byte[] aad,byte[] envelope,ZeroTierDeviceStoreCore.PlainOperation op) throws Exception {
            if(failOpen || revoked.contains(handle)) throw new IOException("synthetic key unavailable");
            byte[] key=KEY.clone(); if(wrongKey) key[0]=1;
            Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.DECRYPT_MODE,new SecretKeySpec(key,"AES"),new GCMParameterSpec(128,envelope,0,12)); Arrays.fill(key,(byte)0);
            cipher.updateAAD(aad); lastPlain=cipher.doFinal(envelope,12,envelope.length-12);
            try {
                if (!duplicateOpen) op.run(lastPlain);
                else {
                    duplicateA=lastPlain.clone(); duplicateB=lastPlain.clone();
                    try { op.run(duplicateA); } catch(Exception ignored) { }
                    try { op.run(duplicateB); } catch(Exception ignored) { }
                }
            } finally { Arrays.fill(lastPlain,(byte)0); }
        }
        public void delete(String handle) throws Exception { deletes++; if(failDelete) throw new IOException("synthetic key delete"); revoked.add(handle); }
    }
    public static void main(String[] args) throws Exception {
        if(args.length==3 && args[0].equals("crash-forget")) {
            ZeroTierDeviceStoreCore core=new ZeroTierDeviceStoreCore(Paths.get(args[1]),new JceBackend(),
                (r,d,b,c) -> { throw new IOException("not used"); }, p -> Runtime.getRuntime().halt(0), r -> {});
            core.forget(args[2],new Factory()); throw new AssertionError("halt did not occur");
        }
        if(args.length==2 && args[0].equals("crash-create")) {
            ZeroTierDeviceStoreCore core=new ZeroTierDeviceStoreCore(Paths.get(args[1]),new JceBackend(),
                (r,d,b,c) -> Runtime.getRuntime().halt(0), Files::delete, r -> {});
            core.create(new Factory()); throw new AssertionError("halt did not occur");
        }
        if(args.length==2 && args[0].equals("data-lock")) {
            Path lock=Paths.get(args[1],"herdr-zerotier-device-v1",".data.lock");
            try(java.nio.channels.FileChannel f=java.nio.channels.FileChannel.open(lock,java.nio.file.StandardOpenOption.CREATE,java.nio.file.StandardOpenOption.WRITE);
                java.nio.channels.FileLock held=f.lock()) {
                if (!held.isValid()) throw new IOException("synthetic data lock unavailable");
                System.out.println("READY"); System.out.flush(); System.in.read();
            }
            return;
        }
        if(args.length==3 && args[0].equals("owner")) {
            ZeroTierDeviceStoreCore core=new ZeroTierDeviceStoreCore(Paths.get(args[1]),new JceBackend());
            core.acquire(args[2],new Factory(),new Proof()); System.out.println("READY"); System.out.flush(); System.in.read(); return;
        }
        Path base=Files.createTempDirectory("zerotier-device-test-");
        try { run(base); System.out.println("PASS: "+checks+" checks; temporary JCE and synthetic identity, no AndroidKeyStore/node"); }
        finally { try (java.util.stream.Stream<Path> paths=Files.walk(base)) {
            paths.sorted(Comparator.reverseOrder()).forEach(path -> { try { Files.deleteIfExists(path); } catch(Exception e) { throw new RuntimeException(e); } });
        } }
    }
    private static void run(Path base) throws Exception {
        JceBackend backend=new JceBackend(); Factory factory=new Factory();
        ZeroTierDeviceStoreCore first=new ZeroTierDeviceStoreCore(base,backend), second=new ZeroTierDeviceStoreCore(base.resolve("."),backend);
        check(first.status(factory)==null,"first missing");
        rejects(() -> first.acquire("11111111-1111-4111-8111-111111111111",factory,new Proof()),"missing must not regenerate");
        check(factory.generated==0,"no implicit generate");
        ZeroTierDeviceStoreCore.PublicRecord created=first.create(factory);
        check(wiped(factory.lastGenerated) && wiped(factory.lastValidated),"generation and validation buffers wiped");
        check(!created.handle.equals(created.instanceId),"separate opaque identity references");
        check(ZeroTierDeviceStoreCore.alias(created.handle).equals("org.herdr.pocket.zerotier-device.v1."+created.handle),"independent provider alias");
        check(second.status(factory).handle.equals(created.handle),"shared device metadata");
        factory.throwError=true; boolean validatorError=false;
        try { first.acquire(created.handle,factory,new Proof()); } catch(AssertionError expected) { validatorError=true; }
        factory.throwError=false;
        check(validatorError && wiped(factory.lastValidated),"validator Error wipes temporary input");
        Proof errorProof=new Proof(); ZeroTierDeviceStoreCore.RuntimeLease errorRecovery=acquire(first,created.handle,factory,errorProof);
        errorProof.allow=true; errorRecovery.confirmDrained(); check(true,"validator Error releases unadmitted owner");
        byte[] disk=Files.readAllBytes(base.resolve("herdr-zerotier-device-v1/device.state"));
        check(!new String(disk,StandardCharsets.ISO_8859_1).contains("X".repeat(32)),"device identity encrypted");
        Proof liveProof=new Proof();
        ZeroTierDeviceStoreCore.RuntimeLease live=acquire(first,created.handle,factory,liveProof);
        rejects(() -> second.acquire(created.handle,factory,new Proof()),"second runtime denied");
        rejects(() -> second.create(factory),"create blocked while runtime owned");
        rejects(() -> second.forget(created.handle,factory),"network leave must not release node owner");
        check(second.status(factory).handle.equals(created.handle),"status read while node active");
        AtomicReference<byte[]> borrowed=new AtomicReference<>();
        CountDownLatch entered=new CountDownLatch(1), resume=new CountDownLatch(1); AtomicReference<Throwable> failure=new AtomicReference<>();
        Thread thread=new Thread(() -> { try { live.withIdentity(bytes -> { borrowed.set(bytes); entered.countDown(); if(!resume.await(5,TimeUnit.SECONDS)) throw new IOException("fixture timeout"); }); } catch(Throwable e) { failure.set(e); } });
        thread.start(); check(entered.await(5,TimeUnit.SECONDS),"native init entered");
        check(borrowed.get().length==270 && borrowed.get()[0]=='X',"validated identity borrowed for synchronous init");
        rejects(live::confirmDrained,"pending init cannot release owner");
        rejects(() -> second.forget(created.handle,factory),"pending init prevents forget");
        resume.countDown(); thread.join(5000); check(!thread.isAlive() && failure.get()==null,"init finished");
        check(wiped(borrowed.get()) && wiped(backend.lastPlain),"borrowed and decrypted arrays wiped");
        rejects(() -> live.withIdentity(bytes -> {}),"lease init cannot repeat");
        rejects(() -> second.forget(created.handle,factory),"returned init does not imply node drained");
        rejects(live::confirmDrained,"native stop timeout retains owner");
        liveProof.allow=true; liveProof.handle="11111111-1111-4111-8111-111111111111";
        rejects(live::confirmDrained,"wrong identity proof cannot retire");
        liveProof.handle=created.handle; liveProof.instance="11111111-1111-4111-8111-111111111111";
        rejects(live::confirmDrained,"wrong instance proof cannot retire");
        liveProof.instance=created.instanceId; liveProof.lease="11111111-1111-4111-8111-111111111111";
        rejects(live::confirmDrained,"old attempt proof cannot retire");
        rejects(() -> second.forget(created.handle,factory),"bad proof retains owner");
        liveProof.lease=live.leaseId(); live.confirmDrained(); rejects(live::confirmDrained,"lease cannot retire twice");
        rejects(() -> second.forget("11111111-1111-4111-8111-111111111111",factory),"stale handle denied");
        check(first.status(factory).handle.equals(created.handle),"stale forget retained record");
        Proof swappedProof=new Proof(); ZeroTierDeviceStoreCore.RuntimeLease swapped=acquire(first,created.handle,factory,swappedProof);
        Path swapPath=base.resolve("herdr-zerotier-device-v1/device.state"); byte[] beforeSwap=Files.readAllBytes(swapPath);
        byte[] alternate=new byte[270]; Arrays.fill(alternate,(byte)'X'); alternate[3]='Y';
        byte[] replacementPlain=ByteBuffer.allocate(306).put(created.instanceId.getBytes(StandardCharsets.US_ASCII)).put(alternate).array();
        byte[] encrypted=backend.create(ZeroTierDeviceStoreCore.alias(created.handle),("herdr-zerotier-device:1:"+created.handle).getBytes(StandardCharsets.US_ASCII),replacementPlain);
        byte[] replacementRecord=ByteBuffer.allocate(beforeSwap.length).put(beforeSwap,0,40).put(encrypted).array(); Files.write(swapPath,replacementRecord);
        rejects(() -> swapped.withIdentity(bytes -> { throw new AssertionError("changed identity reached init"); }),"record replacement before init rejected");
        rejects(() -> second.forget(created.handle,factory),"failed init retains node lease");
        Files.write(swapPath,beforeSwap); swappedProof.allow=true; swapped.confirmDrained();
        Arrays.fill(alternate,(byte)0); Arrays.fill(replacementPlain,(byte)0);
        java.util.List<ZeroTierDeviceStoreCore.RuntimeLease> winners=java.util.Collections.synchronizedList(new java.util.ArrayList<>());
        Proof concurrentProof=new Proof();
        Thread[] contenders=new Thread[8];
        for(int i=0;i<contenders.length;i++) {
            ZeroTierDeviceStoreCore candidate=(i%2==0) ? first : second;
            contenders[i]=new Thread(() -> { try { winners.add(candidate.acquire(created.handle,factory,concurrentProof)); } catch(Exception ignored) {} });
        }
        for(Thread contender:contenders) contender.start(); for(Thread contender:contenders) contender.join();
        check(winners.size()==1,"only one concurrent owner"); concurrentProof.bind(winners.get(0)); concurrentProof.allow=true; winners.get(0).confirmDrained();
        Proof failedProof=new Proof();
        ZeroTierDeviceStoreCore.RuntimeLease failed=acquire(second,created.handle,factory,failedProof);
        AtomicReference<byte[]> exceptionBytes=new AtomicReference<>();
        rejects(() -> failed.withIdentity(bytes -> { exceptionBytes.set(bytes); throw new IOException("synthetic init failure"); }),"init failure");
        check(wiped(exceptionBytes.get()),"failed init buffer wiped");
        rejects(() -> first.forget(created.handle,factory),"unknown init retains lease");
        failedProof.fail=true; rejects(failed::confirmDrained,"verifier error retains owner");
        rejects(() -> first.forget(created.handle,factory),"verifier error blocks forget");
        failedProof.fail=false; failedProof.allow=true; failed.confirmDrained();
        byte[] saved=Files.readAllBytes(base.resolve("herdr-zerotier-device-v1/device.state"));
        byte[] corrupt=saved.clone(); corrupt[corrupt.length-1]^=1;
        Files.write(base.resolve("herdr-zerotier-device-v1/device.state"),corrupt);
        rejects(() -> first.status(factory),"corrupt not missing");
        rejects(() -> first.acquire(created.handle,factory,new Proof()),"corrupt cannot start");
        rejects(() -> first.create(factory),"corrupt cannot regenerate");
        check(factory.generated==1,"corrupt did not regenerate");
        Files.write(base.resolve("herdr-zerotier-device-v1/device.state"),saved);
        Proof duplicateProof=new Proof(); ZeroTierDeviceStoreCore.RuntimeLease duplicate=acquire(first,created.handle,factory,duplicateProof);
        backend.duplicateOpen=true; factory.throwValidation=true; int validations=factory.validated;
        rejects(() -> duplicate.withIdentity(bytes -> { throw new AssertionError("duplicate plaintext reached native init"); }),"swallowed callback failure cannot retry validation");
        check(factory.validated==validations+1,"backend duplicate callback did not reenter validator");
        check(wiped(backend.duplicateA) && wiped(backend.duplicateB),"duplicate callback buffers wiped");
        backend.duplicateOpen=false; factory.throwValidation=false; duplicateProof.allow=true; duplicate.confirmDrained();
        backend.failOpen=true; rejects(() -> first.status(factory),"missing key not missing record");
        rejects(() -> first.acquire(created.handle,factory,new Proof()),"missing key cannot start"); backend.failOpen=false;
        factory.mutate=true; rejects(() -> first.acquire(created.handle,factory,new Proof()),"validator mutation rejected");
        check(wiped(factory.lastValidated),"validator buffer wiped on error"); factory.mutate=false;
        // Cross-process per-operation lock never waits unboundedly.
        String javaExecutable=Paths.get(System.getProperty("java.home"),"bin","java").toString();
        Process dataOwner=new ProcessBuilder(javaExecutable,"-cp",System.getProperty("java.class.path"),ZeroTierDeviceStoreCoreTest.class.getName(),"data-lock",base.toString()).redirectErrorStream(true).start();
        check("READY".equals(dataOwner.inputReader().readLine()),"subprocess acquired data lock");
        long startTime=System.nanoTime(); rejects(() -> first.status(factory),"busy data lock fails closed");
        check(TimeUnit.NANOSECONDS.toMillis(System.nanoTime()-startTime)<1000,"busy data lock returns bounded");
        dataOwner.getOutputStream().write(10); dataOwner.getOutputStream().close();
        check(dataOwner.waitFor(5,TimeUnit.SECONDS) && dataOwner.exitValue()==0,"data owner exits");
        // Cross-process owner lock remains held until actual process exit.
        // Reuse the same local JVM executable; no native libraries are loaded.
        Process child=new ProcessBuilder(javaExecutable,"-cp",System.getProperty("java.class.path"),ZeroTierDeviceStoreCoreTest.class.getName(),
            "owner",base.toString(),created.handle).redirectErrorStream(true).start();
        check("READY".equals(child.inputReader().readLine()),"subprocess acquired owner");
        rejects(() -> first.acquire(created.handle,factory,new Proof()),"cross-process owner denied");
        rejects(() -> first.forget(created.handle,factory),"cross-process forget denied");
        child.getOutputStream().write(10); child.getOutputStream().close();
        check(child.waitFor(5,TimeUnit.SECONDS) && child.exitValue()==0,"process exit unlocks owner");
        Proof restoredProof=new Proof();
        ZeroTierDeviceStoreCore.RuntimeLease restored=acquire(first,created.handle,factory,restoredProof); restoredProof.allow=true; restored.confirmDrained();
        // A key removed before an unlink failure must be recoverable by exact intent.
        final boolean[] failRemove={true};
        ZeroTierDeviceStoreCore interrupted=new ZeroTierDeviceStoreCore(base,backend,
            (r,d,b,c) -> { throw new AssertionError("not used"); },
            p -> { if(failRemove[0]) throw new IOException("synthetic unlink failure"); Files.delete(p); },
            r -> { try(java.nio.channels.FileChannel f=java.nio.channels.FileChannel.open(r,java.nio.file.StandardOpenOption.READ)) { f.force(true); } });
        rejects(() -> interrupted.forget(created.handle,factory),"unlink failure surfaced");
        byte[] oldIntent=Files.readAllBytes(base.resolve("herdr-zerotier-device-v1/device.delete"));
        rejects(() -> first.status(factory),"deletion intent blocks status");
        ZeroTierDeviceStoreCore.PendingDeletion pendingDelete=first.pendingDeletionStatus();
        check(pendingDelete!=null && pendingDelete.handle.equals(created.handle) && pendingDelete.phase.equals("record-present"),"deletion recovery returns exact opaque handle");
        rejects(() -> first.recoverPendingDeletion(created.handle,"record-removed"),"stale deletion phase rejected");
        rejects(() -> first.recoverPendingDeletion("11111111-1111-4111-8111-111111111111",pendingDelete.phase),"wrong recovery handle rejected");
        rejects(() -> first.create(factory),"deletion intent blocks create");
        failRemove[0]=false;
        ZeroTierDeviceStoreCore reopened=new ZeroTierDeviceStoreCore(base,backend,
            (r,d,b,c) -> { throw new AssertionError("not used"); },
            p -> Files.delete(p), r -> { try(java.nio.channels.FileChannel f=java.nio.channels.FileChannel.open(r,java.nio.file.StandardOpenOption.READ)) { f.force(true); } });
        reopened.recoverPendingDeletion(created.handle,pendingDelete.phase);
        check(first.status(factory)==null && first.pendingDeletionStatus()==null,"completed deletion is absence");
        ZeroTierDeviceStoreCore.PublicRecord replacement=first.create(factory);
        check(!replacement.handle.equals(created.handle) && !replacement.instanceId.equals(created.instanceId),"replacement is new device identity");
        rejects(() -> first.recoverPendingDeletion(created.handle,pendingDelete.phase),"old deletion recovery cannot delete replacement");
        rejects(() -> first.recoverPendingDeletion(replacement.handle,pendingDelete.phase),"recovery cannot start first deletion of normal device");
        Files.write(base.resolve("herdr-zerotier-device-v1/device.delete"),oldIntent);
        int deletedBefore=backend.deletes;
        rejects(() -> first.pendingDeletionStatus(),"old intent cannot describe replacement");
        rejects(() -> first.forget(created.handle,factory),"old intent cannot delete replacement");
        check(backend.deletes==deletedBefore,"hash mismatch checked before key deletion");
        Files.delete(base.resolve("herdr-zerotier-device-v1/device.delete"));
        check(first.status(factory).handle.equals(replacement.handle),"replacement retained");
        backend.failDelete=true; rejects(() -> first.forget(replacement.handle,factory),"key deletion failure surfaced");
        rejects(() -> first.status(factory),"failed deletion blocks status"); backend.failDelete=false;
        first.forget(replacement.handle,factory); check(first.status(factory)==null,"key deletion retry converges");
        ZeroTierDeviceStoreCore.PublicRecord lost=first.create(factory);
        Files.delete(base.resolve("herdr-zerotier-device-v1/device.state"));
        rejects(() -> first.status(factory),"seen record missing fails closed");
        rejects(() -> second.create(factory),"missing observed device does not regenerate");
        check(factory.generated==3,"missing observed store did not call generator");
        Path failureBase=Files.createDirectory(base.resolve("atomic-failures"));
        JceBackend failureBackend=new JceBackend(); Factory failureFactory=new Factory();
        ZeroTierDeviceStoreCore failedCreate=new ZeroTierDeviceStoreCore(failureBase,failureBackend,
            (r,d,b,c) -> { throw new IOException("before atomic rename"); }, Files::delete, r -> {});
        rejects(() -> failedCreate.create(failureFactory),"creation write failure surfaced");
        check(wiped(failureFactory.lastGenerated),"failed creation secret wiped");
        check(failureBackend.deletes==1,"uncommitted key retired");
        check(failedCreate.status(failureFactory)==null,"failed create never grants identity");
        failureFactory.valid=false;
        rejects(() -> failedCreate.create(failureFactory),"invalid generated identity rejected");
        check(wiped(failureFactory.lastGenerated) && wiped(failureFactory.lastValidated),"invalid generated buffers wiped");
        failureFactory.valid=true; failureFactory.size=269;
        rejects(() -> failedCreate.create(failureFactory),"short generated identity rejected");
        check(wiped(failureFactory.lastGenerated),"short generated identity wiped");
        failureFactory.size=271;
        rejects(() -> failedCreate.create(failureFactory),"long generated identity rejected");
        check(wiped(failureFactory.lastGenerated),"long generated identity wiped");
        failureFactory.size=270; failureFactory.throwValidation=true;
        rejects(() -> failedCreate.create(failureFactory),"validator error surfaced");
        check(wiped(failureFactory.lastGenerated) && wiped(failureFactory.lastValidated),"validator exception buffers wiped");
        failureFactory.throwValidation=false;
        ZeroTierDeviceStoreCore uncertainCreate=new ZeroTierDeviceStoreCore(failureBase,failureBackend,
            (r,d,b,c) -> { Files.write(d,b); throw new IOException("after rename uncertainty"); }, Files::delete, r -> {});
        rejects(() -> uncertainCreate.create(failureFactory),"post-rename uncertainty surfaced");
        ZeroTierDeviceStoreCore.PendingCreation uncertainPending=uncertainCreate.pendingStatus();
        check(uncertainPending!=null && uncertainPending.phase.equals("record-present"),"possibly committed device exposes pending status");
        rejects(() -> uncertainCreate.status(failureFactory),"uncertain create remains unavailable");
        rejects(() -> uncertainCreate.recoverPendingCreateExact(uncertainPending.handle,"finishing",failureFactory),"stale creation phase rejected");
        rejects(() -> uncertainCreate.discardPendingCreateExact(uncertainPending.handle,"record-present"),"discard rejects installed phase");
        ZeroTierDeviceStoreCore.PublicRecord recovered=uncertainCreate.recoverPendingCreateExact(uncertainPending.handle,uncertainPending.phase,failureFactory);
        check(recovered!=null,"possibly committed device recovered explicitly");
        rejects(() -> uncertainCreate.recoverPendingCreateExact(uncertainPending.handle,uncertainPending.phase,failureFactory),"completed create recovery cannot repeat");
        rejects(() -> uncertainCreate.create(failureFactory),"uncertain create not replayed");
        uncertainCreate.forget(recovered.handle,failureFactory);
        // A real process dies after durable create intent, before installing the record.
        Path crashBase=Files.createDirectory(base.resolve("crash-create"));
        new ZeroTierDeviceStoreCore(crashBase,new JceBackend());
        Process crashing=new ProcessBuilder(javaExecutable,"-cp",System.getProperty("java.class.path"),ZeroTierDeviceStoreCoreTest.class.getName(),"crash-create",crashBase.toString()).redirectErrorStream(true).start();
        check(crashing.waitFor(5,TimeUnit.SECONDS) && crashing.exitValue()==0,"child crashed after intent before record");
        ZeroTierDeviceStoreCore recovery=new ZeroTierDeviceStoreCore(crashBase,new JceBackend());
        ZeroTierDeviceStoreCore.PendingCreation pending=recovery.pendingStatus();
        check(pending!=null && pending.phase.equals("record-pending"),"pending creation is visible as opaque metadata");
        Path pendingPath=crashBase.resolve("herdr-zerotier-device-v1/device.create"); byte[] validPending=Files.readAllBytes(pendingPath);
        Files.write(pendingPath,new byte[]{1,2,3});
        rejects(() -> recovery.pendingStatus(),"corrupt creation intent unavailable");
        rejects(() -> recovery.discardPendingCreate(pending.handle),"corrupt intent cannot delete alias");
        Files.write(pendingPath,validPending);
        rejects(() -> recovery.status(failureFactory),"pending without record not absence");
        rejects(() -> recovery.create(failureFactory),"pending cannot regenerate");
        rejects(() -> recovery.discardPendingCreate("11111111-1111-4111-8111-111111111111"),"wrong pending handle rejected");
        rejects(() -> recovery.discardPendingCreateExact(pending.handle,"finishing"),"stale discard phase rejected");
        rejects(() -> recovery.recoverPendingCreateExact(pending.handle,pending.phase,failureFactory),"uninstalled creation cannot be recovered");
        final boolean[] discardSyncFail={true};
        ZeroTierDeviceStoreCore discarding=new ZeroTierDeviceStoreCore(crashBase,new JceBackend(),
            (r,d,b,c) -> { throw new AssertionError("discard must not generate"); },Files::delete,
            r -> { if(discardSyncFail[0]) throw new IOException("synthetic discard sync failure"); });
        rejects(() -> discarding.discardPendingCreateExact(pending.handle,pending.phase),"discard final sync uncertainty surfaced");
        check(discarding.pendingStatus().phase.equals("finishing"),"discard without installed record keeps finishing latch");
        rejects(() -> discarding.discardPendingCreateExact(pending.handle,pending.phase),"old discard phase cannot continue after transition");
        rejects(() -> discarding.recoverPendingCreateExact(pending.handle,"finishing",failureFactory),"finishing without record cannot recover creation");
        discardSyncFail[0]=false;
        discarding.discardPendingCreateExact(pending.handle,"finishing");
        check(recovery.pendingStatus()==null && recovery.status(failureFactory)==null,"explicit exact discard restores absence");
        ZeroTierDeviceStoreCore.PublicRecord next=recovery.create(failureFactory);
        check(!next.handle.equals(pending.handle),"only explicit fresh create changes identity");
        recovery.forget(next.handle,failureFactory);
        // Renamed record plus failed directory sync cannot grant a lease until authenticated recovery sync.
        Path syncBase=Files.createDirectory(base.resolve("create-sync")); JceBackend syncBackend=new JceBackend(); Factory syncFactory=new Factory();
        final boolean[] syncFail={true};
        ZeroTierDeviceStoreCore syncing=new ZeroTierDeviceStoreCore(syncBase,syncBackend,
            (r,d,b,c) -> Files.write(d,b), Files::delete,
            r -> { if(syncFail[0]) throw new IOException("synthetic fsync failure"); try(java.nio.channels.FileChannel f=java.nio.channels.FileChannel.open(r,java.nio.file.StandardOpenOption.READ)) { f.force(true); } });
        rejects(() -> syncing.create(syncFactory),"failed sync cannot grant identity");
        ZeroTierDeviceStoreCore.PendingCreation syncPending=syncing.pendingStatus();
        check(syncPending!=null && syncPending.phase.equals("record-present"),"installed record awaiting sync is visible");
        rejects(() -> syncing.status(syncFactory),"pending status cannot fake durability");
        rejects(() -> syncing.acquire(syncPending.handle,syncFactory,new Proof()),"pending sync cannot grant lease");
        rejects(() -> syncing.discardPendingCreate(syncPending.handle),"installed record cannot be discarded as absent");
        check(syncFactory.generated==1,"failed sync did not regenerate");
        syncFail[0]=false;
        rejects(() -> syncing.recoverPendingCreate("11111111-1111-4111-8111-111111111111",syncFactory),"wrong recovery handle rejected");
        ZeroTierDeviceStoreCore.PublicRecord syncRecovered=syncing.recoverPendingCreate(syncPending.handle,syncFactory);
        check(syncRecovered.handle.equals(syncPending.handle),"authenticated explicit recovery keeps same identity");
        check(syncing.pendingStatus()==null,"recovered create intent retired");
        syncing.forget(syncRecovered.handle,syncFactory);
        // The intent was removed but its directory sync failed; the in-process
        // finishing latch preserves the exact handle until explicit recovery.
        Path finishingBase=Files.createDirectory(base.resolve("create-finishing")); JceBackend finishingBackend=new JceBackend(); Factory finishingFactory=new Factory();
        final int[] syncCalls={0}; final boolean[] finishFail={true};
        ZeroTierDeviceStoreCore finishing=new ZeroTierDeviceStoreCore(finishingBase,finishingBackend,
            (r,d,b,c) -> Files.write(d,b),Files::delete,
            r -> { syncCalls[0]++; if(finishFail[0] && syncCalls[0]>=2) throw new IOException("synthetic final sync failure");
                try(java.nio.channels.FileChannel f=java.nio.channels.FileChannel.open(r,java.nio.file.StandardOpenOption.READ)) { f.force(true); } });
        rejects(() -> finishing.create(finishingFactory),"intent unlink sync failure surfaced");
        ZeroTierDeviceStoreCore.PendingCreation finishingPending=finishing.pendingStatus();
        check(finishingPending!=null && finishingPending.phase.equals("finishing"),"in-memory finishing latch visible");
        rejects(() -> finishing.status(finishingFactory),"finishing state cannot authorize use");
        rejects(() -> finishing.recoverPendingCreate(finishingPending.handle,finishingFactory),"failed retry remains pending");
        finishFail[0]=false;
        rejects(() -> finishing.discardPendingCreateExact(finishingPending.handle,"finishing"),"finishing with installed record cannot discard");
        ZeroTierDeviceStoreCore.PublicRecord finished=finishing.recoverPendingCreateExact(finishingPending.handle,"finishing",finishingFactory);
        check(finished.handle.equals(finishingPending.handle) && finishing.pendingStatus()==null,"explicit fsync retry preserves same identity");
        finishing.forget(finished.handle,finishingFactory);
        // A separate process dies after key delete but before state unlink.
        Path crashDeleteBase=Files.createDirectory(base.resolve("crash-forget")); JceBackend crashDeleteBackend=new JceBackend(); Factory crashDeleteFactory=new Factory();
        ZeroTierDeviceStoreCore crashDelete=new ZeroTierDeviceStoreCore(crashDeleteBase,crashDeleteBackend);
        ZeroTierDeviceStoreCore.PublicRecord crashIdentity=crashDelete.create(crashDeleteFactory);
        Process crashingDelete=new ProcessBuilder(javaExecutable,"-cp",System.getProperty("java.class.path"),ZeroTierDeviceStoreCoreTest.class.getName(),"crash-forget",crashDeleteBase.toString(),crashIdentity.handle).redirectErrorStream(true).start();
        check(crashingDelete.waitFor(5,TimeUnit.SECONDS) && crashingDelete.exitValue()==0,"child crashed after key deletion before record unlink");
        ZeroTierDeviceStoreCore.PendingDeletion crashPending=crashDelete.pendingDeletionStatus();
        check(crashPending!=null && crashPending.handle.equals(crashIdentity.handle),"crashed delete exposes exact opaque handle");
        crashDeleteBackend.failOpen=true; // emulate key absent in a real persistent keystore
        rejects(() -> crashDelete.status(crashDeleteFactory),"interrupted delete is not empty");
        crashDelete.recoverPendingDeletion(crashPending.handle,crashPending.phase);
        check(crashDelete.pendingDeletionStatus()==null && crashDelete.status(crashDeleteFactory)==null,"interrupted delete converges without decrypting absent key");
        exactDeletionRecoveryCases(base);
        unreadableCases(base);
    }

    private static void exactDeletionRecoveryCases(Path base) throws Exception {
        for(String phase:new String[]{"record-present","record-removed","finishing"}) {
            Path directory=Files.createDirectory(base.resolve("exact-delete-"+phase));
            JceBackend backend=new JceBackend(); Factory factory=new Factory();
            final boolean[] deleting={false},fail={true};
            ZeroTierDeviceStoreCore core=new ZeroTierDeviceStoreCore(directory,backend,
                (r,d,b,c) -> Files.write(d,b),
                p -> { if(deleting[0] && fail[0] && phase.equals("record-present")) throw new IOException("synthetic unlink"); Files.delete(p); },
                r -> {
                    if(deleting[0] && fail[0] && !Files.exists(r.resolve("device.state")) &&
                        (phase.equals("record-removed") && Files.exists(r.resolve("device.delete")) ||
                         phase.equals("finishing") && !Files.exists(r.resolve("device.delete"))))
                        throw new IOException("synthetic deletion sync");
                });
            ZeroTierDeviceStoreCore.PublicRecord device=core.create(factory);
            for(String supplied:new String[]{null,"record-present","record-removed","finishing","unknown"})
                rejects(() -> core.recoverPendingDeletion(device.handle,supplied),"recovery cannot initiate deletion");
            check(core.status(factory).instanceId.equals(device.instanceId) && backend.deletes==0,"normal record unchanged after recovery rejection");
            deleting[0]=true;
            rejects(() -> core.forgetExact(device.handle,device.instanceId,factory),"exact first removal reports injected fault");
            ZeroTierDeviceStoreCore.Snapshot snapshot=core.snapshot(factory);
            check(snapshot.device==null && snapshot.creation==null && snapshot.deletion.phase.equals(phase),"coherent exact pending deletion phase");
            int deletes=backend.deletes;
            for(String supplied:new String[]{"record-present","record-removed","finishing"}) if(!phase.equals(supplied))
                rejects(() -> core.recoverPendingDeletion(device.handle,supplied),"changed pending phase rejected before mutation");
            rejects(() -> core.forgetExact(device.handle,device.instanceId,factory),"normal removal cannot silently resume pending intent");
            check(backend.deletes==deletes && core.pendingDeletionStatus().phase.equals(phase),"stale review leaves pending state intact");
            fail[0]=false;
            core.recoverPendingDeletion(device.handle,phase);
            check(core.status(factory)==null && core.pendingDeletionStatus()==null,"exact reviewed deletion finishes");
            rejects(() -> core.recoverPendingDeletion(device.handle,phase),"completed deletion recovery cannot repeat");
            ZeroTierDeviceStoreCore.PublicRecord next=core.create(factory);
            rejects(() -> core.recoverPendingDeletion(device.handle,phase),"old completed intent cannot remove replacement");
            check(core.status(factory).instanceId.equals(next.instanceId) && factory.generated==2,"recovery never generates replacement");
            core.forgetExact(next.handle,next.instanceId,factory);
        }
    }

    private static void unreadableCases(Path base) throws Exception {
        Path missingBase=Files.createDirectory(base.resolve("unreadable-missing"));
        JceBackend missingBackend=new JceBackend(); Factory factory=new Factory();
        ZeroTierDeviceStoreCore missing=new ZeroTierDeviceStoreCore(missingBase,missingBackend);
        ZeroTierDeviceStoreCore.PublicRecord identity=missing.create(factory);
        rejects(() -> missing.beginDiscardUnreadable(identity.handle,factory),"readable record cannot be discarded as unreadable");
        factory.throwValidation=true;
        rejects(() -> missing.beginDiscardUnreadable(identity.handle,factory),"validator error cannot authorize discard");
        factory.throwValidation=false;
        missingBackend.revoked.add(ZeroTierDeviceStoreCore.alias(identity.handle));
        rejects(() -> missing.forget(identity.handle,factory),"normal forget still requires authentication");
        ZeroTierDeviceStoreCore.UnreadableReview review=missing.beginDiscardUnreadable(identity.handle,factory);
        check(review.handle().equals(identity.handle) && review.state().equals("unreadable"),"review exposes only public identity and state");
        for(java.lang.reflect.Field field:review.getClass().getDeclaredFields())
            check(java.lang.reflect.Modifier.isPrivate(field.getModifiers()),"review internals remain private");
        check(missingBackend.deletes==0,"review does not delete key");
        missing.confirmDiscardUnreadable(review);
        check(missing.status(factory)==null && missingBackend.deletes==1,"explicit confirmation retires exact missing-key record");
        rejects(() -> missing.confirmDiscardUnreadable(review),"review cannot be consumed twice");
        ZeroTierDeviceStoreCore.PublicRecord newIdentity=missing.create(factory);
        check(!newIdentity.handle.equals(identity.handle),"replacement requires explicit creation");
        missing.forget(newIdentity.handle,factory);

        Path wrongBase=Files.createDirectory(base.resolve("unreadable-wrong-key"));
        JceBackend wrongBackend=new JceBackend(); ZeroTierDeviceStoreCore wrong=new ZeroTierDeviceStoreCore(wrongBase,wrongBackend);
        ZeroTierDeviceStoreCore.PublicRecord wrongIdentity=wrong.create(factory); wrongBackend.wrongKey=true;
        rejects(() -> wrong.forget(wrongIdentity.handle,factory),"wrong key cannot pass normal forget");
        ZeroTierDeviceStoreCore.UnreadableReview wrongReview=wrong.beginDiscardUnreadable(wrongIdentity.handle,factory);
        wrong.confirmDiscardUnreadable(wrongReview); wrongBackend.wrongKey=false;
        check(wrong.status(factory)==null,"wrong-key record discarded explicitly");

        Path retryBase=Files.createDirectory(base.resolve("unreadable-retry")); JceBackend retryBackend=new JceBackend();
        ZeroTierDeviceStoreCore retry=new ZeroTierDeviceStoreCore(retryBase,retryBackend);
        ZeroTierDeviceStoreCore.PublicRecord retryIdentity=retry.create(factory); retryBackend.failOpen=true;
        ZeroTierDeviceStoreCore.UnreadableReview retryReview=retry.beginDiscardUnreadable(retryIdentity.handle,factory);
        retryBackend.failDelete=true;
        rejects(() -> retry.confirmDiscardUnreadable(retryReview),"key deletion failure is surfaced");
        check(retry.pendingDeletionStatus().handle.equals(retryIdentity.handle),"confirmed deletion remains recoverable by exact intent");
        rejects(() -> retry.confirmDiscardUnreadable(retryReview),"failed confirmed review cannot be replayed");
        retryBackend.failDelete=false; retry.forget(retryIdentity.handle,factory);
        check(retry.pendingDeletionStatus()==null && retry.status(factory)==null,"exact intent retry finishes without decrypting");

        Path damagedBase=Files.createDirectory(base.resolve("unreadable-damaged"));
        JceBackend damagedBackend=new JceBackend();
        ZeroTierDeviceStoreCore damaged=new ZeroTierDeviceStoreCore(damagedBase,damagedBackend), other=new ZeroTierDeviceStoreCore(damagedBase,damagedBackend);
        ZeroTierDeviceStoreCore.PublicRecord damagedIdentity=damaged.create(factory);
        check(other.status(factory).handle.equals(damagedIdentity.handle),"second instance authenticates before damage");
        Path state=damagedBase.resolve("herdr-zerotier-device-v1/device.state");
        byte[] original=Files.readAllBytes(state), corrupt=original.clone(); corrupt[corrupt.length-1]^=1; Files.write(state,corrupt);
        ZeroTierDeviceStoreCore.UnreadableReview stale=damaged.beginDiscardUnreadable(damagedIdentity.handle,factory);
        ZeroTierDeviceStoreCore.UnreadableReview current=damaged.beginDiscardUnreadable(damagedIdentity.handle,factory);
        rejects(() -> damaged.confirmDiscardUnreadable(stale),"superseded review rejected");
        rejects(() -> other.confirmDiscardUnreadable(current),"review belongs to original store instance");
        byte[] replaced=corrupt.clone(); replaced[replaced.length-2]^=1; Files.write(state,replaced);
        rejects(() -> damaged.confirmDiscardUnreadable(current),"review cannot discard changed ciphertext");
        check(damagedBackend.deletes==0 && Arrays.equals(Files.readAllBytes(state),replaced),"changed record and key retained");
        Files.write(state,corrupt);
        rejects(() -> damaged.confirmDiscardUnreadable(current),"failed review cannot be reused after restoration");
        ZeroTierDeviceStoreCore.UnreadableReview finalReview=damaged.beginDiscardUnreadable(damagedIdentity.handle,factory);
        damaged.confirmDiscardUnreadable(finalReview);
        check(damaged.status(factory)==null,"fresh review can retire exact corrupt ciphertext");

        Path headerBase=Files.createDirectory(base.resolve("unreadable-header")); JceBackend headerBackend=new JceBackend();
        ZeroTierDeviceStoreCore header=new ZeroTierDeviceStoreCore(headerBase,headerBackend);
        ZeroTierDeviceStoreCore.PublicRecord headerIdentity=header.create(factory);
        Path headerState=headerBase.resolve("herdr-zerotier-device-v1/device.state"); byte[] valid=Files.readAllBytes(headerState);
        byte[] invalid=valid.clone(); invalid[0]^=1; Files.write(headerState,invalid);
        rejects(() -> header.beginDiscardUnreadable(headerIdentity.handle,factory),"invalid header blocked");
        String forged="11111111-1111-4111-8111-111111111111";
        byte[] forgedRecord=valid.clone(); System.arraycopy(forged.getBytes(StandardCharsets.US_ASCII),0,forgedRecord,4,36); Files.write(headerState,forgedRecord);
        rejects(() -> header.beginDiscardUnreadable(forged,factory),"valid forged header cannot establish trusted handle");
        rejects(() -> header.beginDiscardUnreadable(headerIdentity.handle,factory),"trusted handle cannot authorize a different header");
        check(headerBackend.deletes==0,"forged header never deletes arbitrary alias");
        Files.write(headerState,valid);
        ZeroTierDeviceStoreCore unverified=new ZeroTierDeviceStoreCore(headerBase,headerBackend); headerBackend.failOpen=true;
        rejects(() -> unverified.beginDiscardUnreadable(headerIdentity.handle,factory),"new instance cannot trust an unauthenticated header");
        headerBackend.failOpen=false; header.forget(headerIdentity.handle,factory);

        Path leaseBase=Files.createDirectory(base.resolve("unreadable-live")); JceBackend leaseBackend=new JceBackend();
        ZeroTierDeviceStoreCore leaseStore=new ZeroTierDeviceStoreCore(leaseBase,leaseBackend);
        ZeroTierDeviceStoreCore.PublicRecord leaseIdentity=leaseStore.create(factory);
        Proof proof=new Proof(); ZeroTierDeviceStoreCore.RuntimeLease live=acquire(leaseStore,leaseIdentity.handle,factory,proof);
        leaseBackend.failOpen=true;
        rejects(() -> leaseStore.beginDiscardUnreadable(leaseIdentity.handle,factory),"live lease blocks review");
        proof.allow=true; live.confirmDrained();
        ZeroTierDeviceStoreCore.UnreadableReview leaseReview=leaseStore.beginDiscardUnreadable(leaseIdentity.handle,factory);
        leaseBackend.failOpen=false; Proof proof2=new Proof(); ZeroTierDeviceStoreCore.RuntimeLease liveAgain=acquire(leaseStore,leaseIdentity.handle,factory,proof2);
        rejects(() -> leaseStore.confirmDiscardUnreadable(leaseReview),"new live lease blocks confirmation");
        check(leaseBackend.deletes==0,"live lease preserved identity");
        proof2.allow=true; liveAgain.confirmDrained(); leaseBackend.failOpen=true;
        rejects(() -> leaseStore.confirmDiscardUnreadable(leaseReview),"busy confirmation consumes old review");
        leaseStore.confirmDiscardUnreadable(leaseStore.beginDiscardUnreadable(leaseIdentity.handle,factory));
        check(leaseStore.status(factory)==null,"new review after drain retires identity");
    }
}
