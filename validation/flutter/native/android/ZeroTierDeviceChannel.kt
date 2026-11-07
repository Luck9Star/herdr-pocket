package dev.herdr.herdr_flutter_probe

import android.app.Activity
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import org.herdr.network.AndroidZeroTierDeviceService
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit

/** Queue admission is revoked by pause/close. Claimed native writes finish once;
 * their late reply is unknown, never a reason to replay the request. */
internal class ZeroTierDeviceGate {
    private var foreground = false
    private var closed = false
    private var epoch = 0L
    @Synchronized fun foreground(value: Boolean) { if (!closed) { foreground = value; if (!value) epoch++ } }
    @Synchronized fun capture(): Long? = if (foreground && !closed) epoch else null
    @Synchronized fun current(expected: Long): Boolean = foreground && !closed && expected == epoch
    @Synchronized fun close() { closed = true; foreground = false; epoch++ }
}

/** Public device metadata only. No identity bytes, node startup or library load. */
class ZeroTierDeviceChannel(private val activity: Activity, messenger: BinaryMessenger) {
    private val channel = MethodChannel(messenger, "dev.herdr/zerotier-device")
    private val gate = ZeroTierDeviceGate()
    private val worker = ThreadPoolExecutor(1, 1, 0L, TimeUnit.MILLISECONDS, ArrayBlockingQueue<Runnable>(8),
        { task -> Thread(task, "pocket-zerotier-device").apply { isDaemon = true } })
    private val uuid = Regex("[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}")
    private val id = Regex("[a-f0-9]{32}")
    private data class Request(val revision: String, val profiles: Set<String>, val hosts: Set<String>, val handle: String?, val instance: String?, val phase: String?)
    init { channel.setMethodCallHandler(::handle) }
    fun setForeground(value: Boolean) { gate.foreground(value) }
    private fun ids(value: Any?): Set<String> {
        val items = value as? List<*> ?: error("invalid request")
        // Matches maxNetworkProfiles/maxHostProfiles in the current catalog.
        check(items.size <= 32)
        val result = items.map { item -> (item as? String ?: error("invalid request")).also { check(id.matches(it)) } }.toSet()
        check(result.size == items.size); return result
    }
    private fun request(method: String, value: Any?): Request {
        val args = value as? Map<*, *> ?: error("invalid request")
        val identityFields = when (method) { "create" -> emptySet(); "forget" -> setOf("handle", "instanceId"); else -> setOf("handle", "expectedPhase") }
        check(args.keys == setOf("catalogRevision", "profileIds", "hostIds") + identityFields)
        val revision = args["catalogRevision"] as? String ?: error("invalid request")
        check(revision.matches(Regex("(?:[a-f0-9]{64})?")))
        fun identity(name: String): String? = if (name !in identityFields) null else
            (args[name] as? String ?: error("invalid request")).also { check(uuid.matches(it)) }
        val phase = if ("expectedPhase" !in identityFields) null else (args["expectedPhase"] as? String ?: error("invalid request")).also {
            val allowed = when (method) {
                "recoverPendingCreation" -> setOf("record-present", "finishing")
                "discardPendingCreation" -> setOf("record-pending", "finishing")
                "recoverPendingDeletion" -> setOf("record-present", "record-removed", "finishing")
                else -> emptySet()
            }
            check(it in allowed)
        }
        return Request(revision, ids(args["profileIds"]), ids(args["hostIds"]), identity("handle"), identity("instanceId"), phase)
    }
    private fun device(value: Any?): Map<String, String> {
        val map = value as? Map<*, *> ?: error("invalid native response")
        check(map.keys == setOf("handle", "instanceId"))
        return mapOf("handle" to (map["handle"] as? String ?: error("invalid native response")),
            "instanceId" to (map["instanceId"] as? String ?: error("invalid native response"))).also { check(it.values.all(uuid::matches)) }
    }
    private fun pending(value: Any?, creation: Boolean): Map<String, String>? {
        if (value == null) return null
        val map = value as? Map<*, *> ?: error("invalid native response")
        check(map.keys == setOf("handle", "phase"))
        val handle = map["handle"] as? String ?: error("invalid native response")
        val phase = map["phase"] as? String ?: error("invalid native response")
        check(uuid.matches(handle) && phase in if (creation) setOf("record-present", "record-pending", "finishing") else setOf("record-present", "record-removed", "finishing"))
        return mapOf("handle" to handle, "phase" to phase)
    }
    private fun status(): Map<String, Any?> {
        val raw = AndroidZeroTierDeviceService.status()
        check(raw.keys == setOf("available", "device", "pendingCreation", "pendingDeletion"))
        val available = raw["available"] as? Boolean ?: error("invalid native response")
        val device = raw["device"]?.let(::device)
        val creation = pending(raw["pendingCreation"], true); val deletion = pending(raw["pendingDeletion"], false)
        check((creation == null || deletion == null) && (device == null || (creation == null && deletion == null)))
        check(available || (device == null && creation == null && deletion == null))
        return mapOf("available" to available, "device" to device, "pendingCreation" to creation, "pendingDeletion" to deletion)
    }
    private fun reply(result: MethodChannel.Result, epoch: Long, write: Boolean, value: Any?, code: String?) {
        activity.runOnUiThread {
            val failure = if (!gate.current(epoch)) { if (write) "zerotier_device_write_unknown" else "zerotier_device_unavailable" } else code
            if (failure == null) result.success(value) else result.error(failure, "Device operation unavailable, changed or not confirmed", null)
        }
    }
    private fun handle(call: MethodCall, result: MethodChannel.Result) {
        val write = call.method != "status"
        if (call.method !in setOf("status", "create", "forget", "recoverPendingCreation", "discardPendingCreation", "recoverPendingDeletion")) { result.notImplemented(); return }
        val request = try {
            if (!write) { check(call.arguments == null); null } else request(call.method, call.arguments)
        } catch (_: Exception) { result.error("zerotier_device_invalid", "Invalid device request", null); return }
        val epoch = gate.capture()
        if (epoch == null) { result.error("zerotier_device_unavailable", "Device operation requires foreground", null); return }
        try {
            worker.execute {
                var dispatched = false
                try {
                    check(gate.current(epoch))
                    val value = if (!write) status() else HostCatalogFile(activity.applicationContext)
                        .runWithExpectedRevision(request!!.revision, request.profiles, request.hosts) {
                            // The epoch check is the dispatch admission point. A later
                            // pause never cancels or repeats a claimed synchronous write.
                            check(gate.current(epoch)); dispatched = true
                            val native = AndroidZeroTierDeviceService.write(call.method, request.handle, request.instance, request.phase)
                            if (call.method in setOf("create", "recoverPendingCreation")) device(native).also {
                                if (call.method == "recoverPendingCreation") check(it["handle"] == request.handle)
                            }
                            else { check(native == null); null }
                        }
                    reply(result, epoch, write, value, null)
                } catch (_: LinkageError) {
                    val absentBridge = mapOf("available" to false, "device" to null, "pendingCreation" to null, "pendingDeletion" to null)
                    reply(result, epoch, write, if (write) null else absentBridge, if (write) "zerotier_device_write_unknown" else null)
                } catch (_: Exception) {
                    reply(result, epoch, write, null, if (dispatched) "zerotier_device_write_unknown" else "zerotier_device_unavailable")
                }
            }
        } catch (_: RejectedExecutionException) { result.error("zerotier_device_busy", "Device queue is full or closed", null) }
    }
    fun close() { gate.close(); channel.setMethodCallHandler(null); worker.shutdown() }
}
