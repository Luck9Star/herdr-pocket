package dev.herdr.herdr_flutter_probe

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.nio.file.Files
import java.util.Base64

/** JVM probe for production journal and CAS source, with synthetic Android Os stubs. */
object InputJournalProbe {
    @JvmStatic fun main(args: Array<String>) {
        if (args.size == 3 && args[0] == "owner") {
            val journal = InputJournalFile(Context(File(args[1])))
            journal.prepare(String(Base64.getDecoder().decode(args[2]), Charsets.UTF_8))
            println("READY"); System.out.flush(); System.`in`.read(); return
        }
        val base = Files.createTempDirectory("herdr-journal-jvm-").toFile()
        try { run(base) } finally { base.deleteRecursively() }
    }
    private fun run(base: File) {
        val context = Context(base)
        val journal = InputJournalFile(context)
        val sibling = InputJournalFile(Context(File(base, ".")))
        val disk = HostCatalogFile(context, "herdr-input-journal-v1")
        var checks = 0
        fun checkValue(value: Boolean) { check(value); checks++ }
        fun rejects(work: () -> Unit) { var failed = false; try { work() } catch (_: Exception) { failed = true }; checkValue(failed) }
        fun rawWrite(text: String) { val old = disk.load(); disk.save(old.getValue("revision"), text) }
        val fields = JSONObject().put("schemaVersion",1).put("requestId","a".repeat(32)).put("host","host.invalid").put("port",22)
            .put("username","fixture").put("hostFingerprint","SHA256:" + "A".repeat(43)).put("session","probe")
            .put("socketPath","/tmp/fixture/herdr/sessions/probe/herdr.sock").put("paneId","w1:p1")
            .put("terminalId","term_abcd").put("generation",1).put("createdAt","2026-11-05T00:00:00.000Z")
        val original = fields.toString()
        checkValue(journal.readAll().isEmpty()); rawWrite(original)
        checkValue(journal.read() == original && journal.readAll() == listOf(original))
        fields.put("paneId","w1:p2").put("terminalId","term_abce").put("requestId","b".repeat(32))
        val second = fields.toString(); val lease = sibling.prepare(second)
        checkValue(lease.matches(Regex("[a-f0-9]{32}")))
        checkValue(journal.readAll() == listOf(original, second))
        rejects { journal.read() }; rejects { journal.clear(original) }; rejects { journal.resolve(second) }
        val changedRequest = second.replace("b".repeat(32),"c".repeat(32))
        rejects { journal.prepare(changedRequest) }; rejects { journal.complete(changedRequest, lease) }; rejects { journal.abandon(changedRequest, lease) }
        rejects { journal.complete(second, "0".repeat(32)) }; rejects { journal.abandon(second, "0".repeat(32)) }
        journal.resolve(original); sibling.abandon(second, lease)
        checkValue(journal.readAll() == listOf(second)); rejects { journal.prepare(second) }
        rejects { journal.prepare(changedRequest) }; rejects { journal.resolve(changedRequest) }; journal.resolve(second)
        val old = journal.prepare(original); journal.complete(original, old); val new = sibling.prepare(original)
        checkValue(old != new); rejects { journal.complete(original, old) }; rejects { journal.abandon(original, old) }
        journal.complete(original, new)
        val winners = java.util.Collections.synchronizedList(mutableListOf<String>())
        val threads = (0 until 8).map { Thread { try { winners.add(InputJournalFile(Context(base)).prepare(original)) } catch (_: Exception) {} } }
        threads.forEach(Thread::start); threads.forEach(Thread::join)
        checkValue(winners.size == 1); journal.abandon(original,winners.single()); journal.resolve(original)
        fields.put("paneId","w1:p1").put("terminalId","term_abcd").put("requestId","d".repeat(32)).put("username","caf\u00e9")
        val composed = fields.toString()
        fields.put("username","cafe\u0301").put("requestId","e".repeat(32))
        val decomposed = fields.toString()
        val composedLease = journal.prepare(composed); val decomposedLease = sibling.prepare(decomposed)
        checkValue(journal.readAll() == listOf(composed,decomposed))
        val wrongRaw = composed.replace("caf\u00e9","cafe\u0301")
        rejects { journal.complete(wrongRaw,composedLease) }
        journal.abandon(composed,composedLease); sibling.abandon(decomposed,decomposedLease)
        rejects { journal.resolve(wrongRaw) }
        journal.resolve(composed); journal.resolve(decomposed); fields.put("username","fixture")
        fields.put("schemaVersion",2).put("route",JSONObject.NULL).put("paneId","w1:p1").put("terminalId","term_abcd")
        val nullRoute = fields.toString(); val nullLease = journal.prepare(nullRoute)
        rejects { sibling.prepare(original) }; journal.complete(nullRoute, nullLease)
        fields.put("route","easy-tier:0123456789abcdef0123456789abcdef:3:a0000000-0000-4000-8000-000000000001")
        val routed = fields.toString(); val legacyLease = journal.prepare(original); val routedLease = sibling.prepare(routed)
        checkValue(journal.readAll().size == 2); journal.complete(original,legacyLease); sibling.complete(routed,routedLease)
        fields.put("schemaVersion",1).remove("route")
        val leases = mutableListOf<Pair<String,String>>()
        for (i in 0 until 32) {
            fields.put("paneId","w1:p$i").put("terminalId","term_${(i+1).toString(16)}")
            val raw = fields.toString(); leases.add(raw to journal.prepare(raw))
        }
        checkValue(journal.readAll().size == 32)
        fields.put("paneId","w1:p99").put("terminalId","term_ff")
        rejects { journal.prepare(fields.toString()) }
        for ((raw,token) in leases) journal.complete(raw,token)
        checkValue(journal.readAll().isEmpty())
        rejects { journal.prepare(original.replace("\"schemaVersion\":1", "\"schemaVersion\":1.0")) }
        rejects { journal.prepare(original.replace("\"port\":22", "\"port\":22.0")) }
        rejects { journal.prepare("{\"schemaVersion\":1," + original.drop(1)) }
        rawWrite("{\"schemaVersion\":3,\"records\":[],\"records\":[]}"); rejects { journal.readAll() }
        rawWrite("{\"schemaVersion\":3.0,\"records\":[]}"); rejects { journal.readAll() }
        rawWrite("{\"schemaVersion\":4,\"records\":[]}"); rejects { journal.readAll() }
        rawWrite(JSONObject().put("schemaVersion",3).put("records",JSONArray(listOf(original,original))).toString())
        rejects { journal.readAll() }
        rawWrite(JSONObject().put("schemaVersion",3).put("records",JSONArray(listOf(original,original.replace("a".repeat(32),"c".repeat(32))))).toString())
        rejects { journal.readAll() }; rawWrite("{}")
        val revision = disk.load().getValue("revision"); disk.save(revision,"{\"newer\":true}")
        rejects { disk.save(revision,"{}") }; rawWrite("{}")
        val beforeOversize = disk.load(); rejects { disk.save(beforeOversize.getValue("revision"),"x".repeat(262145)) }
        checkValue(disk.load().getValue("contents") == "{}")
        val linkBase = File(base,"symlink"); val linkDir = File(linkBase,"herdr-input-journal-v1"); check(linkDir.mkdirs())
        val target = File(base,"owner-target").also { it.writeText("fixture") }
        Files.createSymbolicLink(File(linkDir,"owner.lock").toPath(),target.toPath())
        rejects { InputJournalFile(Context(linkBase)).readAll() }
        // A file observed by this owner cannot later disappear and become an
        // apparently empty first-run journal.
        val removedBase = File(base,"removed-after-prepare").also { check(it.mkdir()) }
        val removed = InputJournalFile(Context(removedBase)); checkValue(removed.readAll().isEmpty())
        val removedLease = removed.prepare(original); removed.abandon(original,removedLease)
        val removedFile = File(removedBase,"herdr-input-journal-v1/catalog.json"); check(removedFile.delete())
        rejects { removed.readAll() }; rejects { InputJournalFile(Context(removedBase)).readAll() }
        rejects { removed.prepare(original) }; checkValue(!removedFile.exists())
        val readOnlyBase = File(base,"removed-after-legacy-read").also { check(it.mkdir()) }
        val legacyDisk = HostCatalogFile(Context(readOnlyBase),"herdr-input-journal-v1")
        legacyDisk.save("",original)
        val reader = InputJournalFile(Context(readOnlyBase)); checkValue(reader.readAll() == listOf(original))
        check(File(readOnlyBase,"herdr-input-journal-v1/catalog.json").delete()); rejects { reader.readAll() }
        // A real JVM subprocess owns the OS lock; parent must refuse until
        // exit, then see the exact retained pending record.
        val processBase = File(base,"subprocess").also { check(it.mkdir()) }
        val java = File(System.getProperty("java.home"),"bin/java").path
        val child = ProcessBuilder(java,"-cp",System.getProperty("java.class.path"),javaClass.name,
            "owner",processBase.path,Base64.getEncoder().encodeToString(original.toByteArray(Charsets.UTF_8)))
            .redirectError(ProcessBuilder.Redirect.INHERIT).start()
        checkValue(child.inputStream.bufferedReader().readLine() == "READY")
        val recovering = InputJournalFile(Context(processBase)); rejects { recovering.readAll() }
        child.outputStream.write(10); child.outputStream.close(); checkValue(child.waitFor() == 0)
        checkValue(recovering.readAll() == listOf(original)); recovering.resolve(original)
        checkValue(recovering.readAll().isEmpty())
        println("{\"checks\":$checks,\"scope\":\"real Kotlin journal and CAS, temporary files and JVM subprocess; Android Os fsync stubbed; no device\"}")
    }
}
