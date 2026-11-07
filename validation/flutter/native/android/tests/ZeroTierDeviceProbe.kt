package dev.herdr.herdr_flutter_probe

import android.app.Activity
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import org.herdr.network.AndroidZeroTierDeviceService as Service
import java.nio.file.Files
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/** Real Kotlin channel/catalog, synthetic Android/Flutter/service. No JNI or keys. */
fun main() {
    var checks = 0
    fun verify(value: Boolean) { check(value) { "device channel check $checks" }; checks++ }
    val root = Files.createTempDirectory("zt-device-channel-").toFile()
    val activity = Activity(root)
    val disk = HostCatalogFile(activity)
    val network = "a".repeat(32); val host = "b".repeat(32); val legacy = "c".repeat(32)
    val contents = """{"schemaVersion":4,"profiles":[{"id":"$host","provider":"direct","networkProfileId":"$network","enabled":false,"retired":true},{"id":"$legacy","provider":"zerotier","networkProfileId":null}],"pendingCreation":null,"networkProfiles":[{"id":"$network","provider":"zerotier","enabled":false}]}"""
    val revision = disk.save("", contents)
    val review = mapOf("catalogRevision" to revision, "profileIds" to listOf(network), "hostIds" to listOf(host,legacy))
    val handle = "a0000000-0000-4000-8000-000000000001"; val instance = "b0000000-0000-4000-8000-000000000002"
    class Reply: MethodChannel.Result {
        val done = CountDownLatch(1); val calls = AtomicInteger()
        var value: Any? = null; var code: String? = null
        override fun success(value: Any?) { this.value = value; calls.incrementAndGet(); done.countDown() }
        override fun error(code: String, message: String?, details: Any?) { this.code = code; calls.incrementAndGet(); done.countDown() }
        override fun notImplemented() { code = "notImplemented"; calls.incrementAndGet(); done.countDown() }
        fun await(): Reply { verify(done.await(5, TimeUnit.SECONDS)); verify(calls.get() == 1); return this }
    }
    fun fire(method: String, args: Any? = null): Reply = Reply().also {
        MethodChannel.fire("dev.herdr/zerotier-device", MethodCall(method,args), it)
    }
    val channel = ZeroTierDeviceChannel(activity, object: BinaryMessenger {})
    try {
        verify(fire("create",review).await().code == "zerotier_device_unavailable")
        channel.setForeground(true)
        val absent = fire("status").await().value as Map<*, *>
        verify(absent["available"] == false && absent["device"] == null)
        verify(fire("status",emptyMap<String,String>()).await().code == "zerotier_device_invalid")
        verify(fire("export").await().code == "notImplemented")
        for (bad in listOf(review + ("secret" to "forbidden"), review - "hostIds", review + ("profileIds" to listOf(network,network)),
            review + ("hostIds" to listOf("wrong")),review + ("catalogRevision" to "bad"),review + ("hostIds" to List(33) { host }))) {
            verify(fire("create",bad).await().code == "zerotier_device_invalid")
        }
        Service.available = true
        for (bad in listOf(review + ("catalogRevision" to "f".repeat(64)),review + ("hostIds" to listOf(host)),review + ("profileIds" to emptyList<String>()))) {
            verify(fire("create",bad).await().code == "zerotier_device_unavailable")
        }
        verify(Service.writes == 0)
        verify(fire("create",review).await().code == null); verify(Service.writes == 1)
        verify(Service.threadName == "pocket-zerotier-device")
        verify(fire("forget",review + mapOf("handle" to handle)).await().code == "zerotier_device_invalid")
        verify(fire("forget",review + mapOf("handle" to handle,"instanceId" to instance.uppercase())).await().code == "zerotier_device_invalid")
        verify(fire("forget",review + mapOf("handle" to handle,"instanceId" to instance)).await().code == null)
        Service.pendingHandle = handle; Service.pendingPhase = "record-present"
        Service.recoverWrongHandle = true
        verify(fire("recoverPendingCreation",review + mapOf("handle" to handle,"expectedPhase" to "record-present")).await().code == "zerotier_device_write_unknown")
        Service.recoverWrongHandle = false
        for ((action,phases) in listOf(
            "recoverPendingCreation" to listOf("record-present","finishing"),
            "discardPendingCreation" to listOf("record-pending","finishing"),
            "recoverPendingDeletion" to listOf("record-present","record-removed","finishing"))) {
            for (phase in phases) {
                Service.pendingPhase = phase
                verify(fire(action,review + mapOf("handle" to handle,"expectedPhase" to phase)).await().code == null)
            }
            verify(fire(action,review + ("handle" to handle)).await().code == "zerotier_device_invalid")
            verify(fire(action,review + mapOf("handle" to handle,"expectedPhase" to "invented")).await().code == "zerotier_device_invalid")
            verify(fire(action,review + mapOf("handle" to handle,"expectedPhase" to phases.first(),"instanceId" to instance)).await().code == "zerotier_device_invalid")
        }
        for ((action,phase) in listOf("recoverPendingCreation" to "record-pending","discardPendingCreation" to "record-present","recoverPendingDeletion" to "record-pending")) {
            verify(fire(action,review + mapOf("handle" to handle,"expectedPhase" to phase)).await().code == "zerotier_device_invalid")
        }
        val beforeStale = Service.writes
        Service.pendingPhase = "finishing"
        verify(fire("recoverPendingCreation",review + mapOf("handle" to handle,"expectedPhase" to "record-present")).await().code == "zerotier_device_write_unknown")
        verify(fire("recoverPendingDeletion",review + mapOf("handle" to "d0000000-0000-4000-8000-000000000004","expectedPhase" to "finishing")).await().code == "zerotier_device_write_unknown")
        verify(Service.writes == beforeStale)
        Service.pendingPhase = null; Service.pendingHandle = null
        val writesBeforeQueue = Service.writes
        Service.entered = CountDownLatch(1); Service.release = CountDownLatch(1)
        val blockedRead = fire("status"); verify(Service.entered.await(3,TimeUnit.SECONDS))
        val queued = fire("create",review)
        channel.setForeground(false); Service.release.countDown()
        verify(blockedRead.await().code == "zerotier_device_unavailable")
        verify(queued.await().code == "zerotier_device_write_unknown"); verify(Service.writes == writesBeforeQueue)
        channel.setForeground(true)
        Service.entered = CountDownLatch(1); Service.release = CountDownLatch(1)
        val first = fire("status"); verify(Service.entered.await(3,TimeUnit.SECONDS))
        val waiting = (0 until 8).map { fire("status") }
        verify(fire("status").await().code == "zerotier_device_busy")
        Service.release.countDown(); verify(first.await().code == null); waiting.forEach { verify(it.await().code == null) }
        Service.entered = CountDownLatch(1); Service.release = CountDownLatch(1)
        val lateWrite = fire("create",review); verify(Service.entered.await(3,TimeUnit.SECONDS))
        val saved = CountDownLatch(1)
        val saver = Thread { disk.save(revision,contents + " "); saved.countDown() }.apply { start() }
        verify(!saved.await(100,TimeUnit.MILLISECONDS)) // Same catalog file lock spans service.write.
        channel.setForeground(false); Service.release.countDown()
        verify(lateWrite.await().code == "zerotier_device_write_unknown"); verify(saved.await(3,TimeUnit.SECONDS)); saver.join()
        channel.setForeground(true)
        verify(fire("create",review).await().code == "zerotier_device_unavailable")
        val revised = disk.load()["revision"]!!
        val revisedReview = review + ("catalogRevision" to revised)
        Service.entered = CountDownLatch(1); Service.release = CountDownLatch(1)
        val closeRead = fire("status"); verify(Service.entered.await(3,TimeUnit.SECONDS))
        val closeQueued = fire("create",revisedReview); channel.close(); channel.setForeground(true); Service.release.countDown()
        verify(closeRead.await().code == "zerotier_device_unavailable")
        verify(closeQueued.await().code == "zerotier_device_write_unknown")
        val malformed = contents.replace("\"provider\":\"zerotier\",\"enabled\"", "\"provider\":\"zerotier\",\"pro\\u0076ider\":\"direct\",\"enabled\"")
        val malformedRevision = disk.save(revised,malformed)
        var ran = false
        try { disk.runWithExpectedRevision(malformedRevision,setOf(network),setOf(host,legacy)) { ran = true }; error("accepted duplicate") }
        catch (_: IllegalStateException) { verify(!ran) }
    } finally { Service.release.countDown(); channel.close(); root.deleteRecursively() }
    println("Kotlin ZeroTier device channel: $checks checks passed; synthetic Android/Flutter/service only")
}
