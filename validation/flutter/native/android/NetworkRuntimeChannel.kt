package dev.herdr.pocket

import android.app.Activity
import android.os.Build
import android.content.Intent
import android.net.Uri
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import org.herdr.network.AndroidEasyTierConfig
import org.herdr.network.AndroidNetworkSecretStore
import org.herdr.network.AndroidTailscaleStateStore
import org.herdr.network.AndroidTailscaleConfig
import org.herdr.network.AndroidZeroTierNative
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/** Epoch admission for user-reviewed login URLs; does not store URL or credentials. */
internal class LoginReviewGate {
    private var foreground = false
    private var epoch = 0L
    private var review: String? = null
    @Synchronized fun foreground(value: Boolean) {
        foreground = value
        if (!value) { epoch++; review = null }
    }
    @Synchronized fun invalidate(): Long { review = null; epoch++; return epoch }
    @Synchronized fun admit(): Long? { if (!foreground) return null; return invalidate() }
    @Synchronized fun active(expected: Long): Boolean = foreground && epoch == expected
    @Synchronized fun install(expected: Long, token: String?): Boolean {
        if (!foreground || epoch != expected) return false
        review = token; return true
    }
    @Synchronized fun capture(token: String): Long? = if (foreground && review == token) epoch else null
    @Synchronized fun valid(expected: Long, token: String): Boolean = foreground && epoch == expected && review == token
}

/** One private native scope per Flutter engine. No scope or config secret comes from Dart. */
class NetworkRuntimeChannel(private val activity: Activity, messenger: BinaryMessenger) {
    companion object {
        @JvmStatic external fun nativeCreateScope(): Long
        @JvmStatic external fun nativeReserveOpen(scope: Long, openId: String): String
        @JvmStatic external fun nativeCall(scope: Long, method: String, argsJson: String, payload: ByteArray?): Array<Any?>
        @JvmStatic external fun nativeCloseScope(scope: Long): String
        private const val MAX_IO = 65536
        private val profilePattern = Regex("[a-f0-9]{32}")
        private val identityPattern = Regex("[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}")
        private val tokenPattern = Regex("[A-Za-z0-9_-]{1,96}")
        private val errorPattern = Regex("[a-z][a-z0-9_]{0,63}")
    }
    private class BridgeFailure(val code: String): Exception()
    private val channel = MethodChannel(messenger, "dev.herdr/network-runtime")
    private val closed = AtomicBoolean(false)
    private val lifecycle = Any()
    @Volatile private var scope: Long = 0
    @Volatile private var easyTierBound = false
    @Volatile private var tailscaleBound = false
    @Volatile private var zeroTierBound = false
    private val loginGate = LoginReviewGate()
    fun setForeground(value: Boolean) { loginGate.foreground(value) }
    private fun pool(name: String, count: Int, capacity: Int) = ThreadPoolExecutor(
        count, count, 0L, TimeUnit.MILLISECONDS, ArrayBlockingQueue<Runnable>(capacity),
        { task -> Thread(task, "pocket-network-$name").apply { isDaemon = true } }
    )
    // Idle reads and starts cannot exhaust the cancellation, write or stop lanes.
    private val fast = pool("control", 1, 32)
    private val starts = pool("start", 2, 8)
    private val statuses = pool("status", 2, 8)
    private val stops = pool("stop", 2, 8)
    private val reads = pool("read", 2, 32)
    private val writes = pool("write", 2, 32)
    private val opens = pool("open", 2, 32)
    private val workers = listOf(fast, starts, statuses, stops, reads, writes, opens)

    init {
        // Library loading and native registration happen off the UI thread.
        fast.execute {
            if (!closed.get() && Build.VERSION.SDK_INT >= 35) {
                // A linked runtime may require both shared libraries; if any DT_NEEDED
                // is absent the runtime itself refuses to load, never a fallback.
                val etLibrary = try { System.loadLibrary("heeler_easytier"); true } catch (_: LinkageError) { false }
                val tsLibrary = try { System.loadLibrary("hp_tailscale"); true } catch (_: LinkageError) { false }
                val ztLibrary = try { System.loadLibrary("hp_zerotier"); true } catch (_: LinkageError) { false }
                try {
                    System.loadLibrary("herdr_flutter_network_runtime")
                    easyTierBound = etLibrary && try { AndroidEasyTierConfig.bindNative(activity.applicationContext) } catch (_: LinkageError) { false } catch (_: Exception) { false }
                    tailscaleBound = tsLibrary && try { AndroidTailscaleConfig.bindNative(activity.applicationContext) } catch (_: LinkageError) { false } catch (_: Exception) { false }
                    zeroTierBound = ztLibrary && try { AndroidZeroTierNative.bindNative(activity.applicationContext) } catch (_: LinkageError) { false } catch (_: Exception) { false }
                    val created = nativeCreateScope()
                    synchronized(lifecycle) {
                        if (closed.get()) { if (created != 0L) nativeCloseScope(created) }
                        else scope = created
                    }
                } catch (_: LinkageError) { /* Required shared library absent. */ }
                  catch (_: Exception) { /* Do not expose exception contents. */ }
            }
        }
        channel.setMethodCallHandler(::handle)
    }

    private fun fail(result: MethodChannel.Result, code: String) {
        activity.runOnUiThread {
            if (!closed.get()) result.error(code, "Native network operation unavailable or interrupted", null)
        }
    }
    private fun succeed(result: MethodChannel.Result, value: Any?) {
        activity.runOnUiThread { if (!closed.get()) result.success(value) }
    }
    private fun submit(executor: ThreadPoolExecutor, result: MethodChannel.Result, payload: ByteArray? = null, work: () -> Any?) {
        if (closed.get()) { payload?.fill(0); return }
        try {
            executor.execute(OwnedTask(result, payload, work))
        } catch (_: RejectedExecutionException) {
            payload?.fill(0)
            fail(result, "network_worker_busy")
        }
    }
    private inner class OwnedTask(private val result: MethodChannel.Result, private val payload: ByteArray?, private val work: () -> Any?): Runnable {
        override fun run() {
            try {
                if (!closed.get()) {
                    val value = work()
                    if (value !== DeferredResult) succeed(result, value)
                }
            } catch (e: BridgeFailure) { fail(result, e.code) }
              catch (_: LinkageError) { fail(result, "overlay_provider_unavailable") }
              catch (_: Exception) { fail(result, "network_native_failed") }
            finally { payload?.fill(0) }
        }
        fun abort() { payload?.fill(0) }
    }
    private fun currentScope(): Long {
        if (closed.get() || scope <= 0L) throw BridgeFailure("overlay_provider_unavailable")
        return scope
    }
    private fun map(value: Any?): Map<String, Any?> {
        val source = value as? Map<*, *> ?: throw BridgeFailure("invalid_network_request")
        if (source.keys.any { it !is String }) throw BridgeFailure("invalid_network_request")
        return source.entries.associate { (key, item) -> key as String to item }
    }
    private fun exact(value: Map<String, Any?>, keys: Set<String>) {
        if (value.keys != keys) throw BridgeFailure("invalid_network_request")
    }
    private fun string(value: Any?, max: Int): String {
        val text = value as? String ?: throw BridgeFailure("invalid_network_request")
        if (text.isEmpty() || text.toByteArray(Charsets.UTF_8).size > max || text.any { it <= '\u001f' || it in '\u007f'..'\u009f' })
            throw BridgeFailure("invalid_network_request")
        return text
    }
    private fun integer(value: Any?, low: Long, high: Long): Long {
        val number = when (value) { is Int -> value.toLong(); is Long -> value; else -> throw BridgeFailure("invalid_network_request") }
        if (number !in low..high) throw BridgeFailure("invalid_network_request")
        return number
    }
    private fun token(value: Any?): String = string(value, 96).also {
        if (!tokenPattern.matches(it)) throw BridgeFailure("invalid_network_request")
    }
    private fun binding(value: Any?): Map<String, Any?> {
        val b = map(value)
        val ts = b["provider"] == "tailscale"
        exact(b, if (ts) setOf("profileId", "profileRevision", "networkName", "identityRef", "provider") else setOf("profileId", "profileRevision", "networkName", "identityRef"))
        if (!profilePattern.matches(string(b["profileId"], 32)) || !identityPattern.matches(string(b["identityRef"], 36)))
            throw BridgeFailure("invalid_network_binding")
        integer(b["profileRevision"], 1, Int.MAX_VALUE.toLong())
        if (string(b["networkName"], 256).isBlank()) throw BridgeFailure("invalid_network_binding")
        return b
    }
    private fun checkTailscaleIdentity(b: Map<String, Any?>) {
        val record = AndroidTailscaleStateStore(activity.applicationContext).status(b["profileId"] as String)
            ?: throw BridgeFailure("network_identity_missing")
        if (record.profileId != b["profileId"] || record.provider != "tailscale" || record.handle != b["identityRef"])
            throw BridgeFailure("network_identity_changed")
    }
    private fun encoded(args: Map<String, Any?>): String = JSONObject(args).toString().also {
        if (it.toByteArray(Charsets.UTF_8).size > MAX_IO) throw BridgeFailure("invalid_network_request")
    }
    private fun envelope(text: String): Any? {
        if (text.toByteArray(Charsets.UTF_8).size > MAX_IO) throw BridgeFailure("network_native_invalid_response")
        val response = JSONObject(text)
        if (!response.has("ok") || response.opt("ok") !is Boolean) throw BridgeFailure("network_native_invalid_response")
        if (!response.getBoolean("ok")) {
            val code = response.opt("error") as? String
            throw BridgeFailure(if (code != null && errorPattern.matches(code)) code else "network_native_invalid_response")
        }
        return publicValue(response.get("value"), 0)
    }
    private fun publicValue(value: Any?, depth: Int): Any? {
        if (depth > 5) throw BridgeFailure("network_native_invalid_response")
        return when (value) {
            null, JSONObject.NULL -> null
            is JSONObject -> value.keys().asSequence().associateWith { publicValue(value.get(it), depth + 1) }
            is JSONArray -> (0 until value.length()).map { publicValue(value.get(it), depth + 1) }
            is String, is Boolean, is Int, is Long -> value
            else -> throw BridgeFailure("network_native_invalid_response")
        }
    }
    private fun callNative(ownedScope: Long, method: String, args: Map<String, Any?>, payload: ByteArray? = null): Any? {
        val response = nativeCall(ownedScope, method, encoded(args), payload)
        if (response.size != 2 || response[0] !is String) throw BridgeFailure("network_native_invalid_response")
        val value = envelope(response[0] as String)
        if (method == "streamRead") {
            val bytes = response[1] as? ByteArray ?: throw BridgeFailure("network_native_invalid_response")
            val maximum = integer(args["maxBytes"], 1, MAX_IO.toLong())
            val result = map(value)
            if (result.keys != setOf("eof") || result["eof"] !is Boolean || bytes.size > maximum || (result["eof"] == true && bytes.isNotEmpty()))
                throw BridgeFailure("network_native_invalid_response")
            return result + ("bytes" to bytes)
        }
        if (response[1] != null) throw BridgeFailure("network_native_invalid_response")
        return value
    }
    private fun handle(call: MethodCall, result: MethodChannel.Result) {
        if (closed.get()) return
        try {
            val args = if (call.arguments == null) emptyMap() else map(call.arguments)
            when (call.method) {
                "available" -> {
                    if (args.isNotEmpty()) { exact(args, setOf("provider")); if (args["provider"] != "tailscale") throw BridgeFailure("invalid_network_request") }
                    submit(fast, result) {
                        val bound = if (args["provider"] == "tailscale") tailscaleBound else easyTierBound
                        if (scope == 0L || closed.get() || !bound) mapOf("available" to false, "reason" to "overlay_provider_unavailable")
                        else callNative(currentScope(), "available", args)
                    }
                }
                "nodeStatus" -> {
                    if (args.containsKey("provider")) { exact(args, setOf("profileId", "provider")); if (args["provider"] != "tailscale") throw BridgeFailure("invalid_network_request") } else exact(args, setOf("profileId"))
                    if (!profilePattern.matches(string(args["profileId"], 32))) throw BridgeFailure("invalid_network_request")
                    submit(statuses, result) {
                        if (scope == 0L) mapOf("state" to "unavailable", "binding" to null)
                        else callNative(currentScope(), call.method, args)
                    }
                }
                "nodeStart" -> {
                    val b = binding(args["binding"]); val ts = b["provider"] == "tailscale"
                    if (ts) {
                        exact(args, setOf("binding", "settings"))
                        val settings = map(args["settings"]); exact(settings, setOf("controlUrl", "hostname"))
                        string(settings["controlUrl"], 4096); string(settings["hostname"], 63)
                    } else {
                        exact(args, setOf("binding", "peers"))
                        val peers = args["peers"] as? List<*> ?: throw BridgeFailure("invalid_network_request")
                        if (peers.size !in 1..16 || peers.any { string(it, 2048).any { char -> char.code !in 33..126 } })
                            throw BridgeFailure("invalid_network_request")
                    }
                    loginGate.invalidate()
                    submit(starts, result) {
                        val owned = currentScope()
                        if (ts) {
                            if (!tailscaleBound) throw BridgeFailure("overlay_provider_unavailable")
                            checkTailscaleIdentity(b)
                        } else {
                            if (!easyTierBound) throw BridgeFailure("overlay_provider_unavailable")
                            val record = AndroidNetworkSecretStore(activity.applicationContext).status(b["profileId"] as String, "easytier")
                                ?: throw BridgeFailure("network_identity_missing")
                            if (record.handle != b["identityRef"]) throw BridgeFailure("network_identity_changed")
                            if (record.mode != AndroidNetworkSecretStore.SecretMode.PRIVATE) throw BridgeFailure("network_public_mode_unsupported")
                        }
                        callNative(owned, call.method, args)
                    }
                }
                "nodeLogin", "nodeLoginStatus" -> {
                    exact(args, setOf("binding")); val b = binding(args["binding"])
                    if (b["provider"] != "tailscale") throw BridgeFailure("invalid_network_binding")
                    val epoch = loginGate.admit() ?: throw BridgeFailure("network_login_changed")
                    submit(statuses, result) {
                        if (!loginGate.active(epoch)) throw BridgeFailure("network_login_changed")
                        checkTailscaleIdentity(b)
                        if (!loginGate.active(epoch)) throw BridgeFailure("network_login_changed")
                        val value = callNative(currentScope(), call.method, args)
                        val response = map(value)
                        val url = response["authUrl"]; val review = response["reviewToken"]
                        if ((url == null) != (review == null) || (review != null && review !is String))
                            throw BridgeFailure("network_native_invalid_response")
                        if (closed.get() || !loginGate.install(epoch, review as? String)) throw BridgeFailure("network_login_changed")
                        value
                    }
                }
                "openLogin" -> {
                    exact(args, setOf("binding", "url", "reviewToken")); val b = binding(args["binding"])
                    if (b["provider"] != "tailscale") throw BridgeFailure("invalid_network_binding")
                    val url = string(args["url"], 4096); val reviewToken = token(args["reviewToken"])
                    val epoch = loginGate.capture(reviewToken) ?: throw BridgeFailure("network_login_changed")
                    submit(statuses, result) {
                        val owned = currentScope()
                        checkTailscaleIdentity(b)
                        val current = map(callNative(owned, "nodeAuthorizeOpen", mapOf("binding" to b, "url" to url, "reviewToken" to reviewToken)))
                        if (current != mapOf("reviewed" to true)) throw BridgeFailure("network_login_changed")
                        activity.runOnUiThread {
                            if (closed.get() || scope != owned || !loginGate.valid(epoch, reviewToken)) {
                                fail(result, "network_login_changed")
                            } else {
                                try { activity.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))); succeed(result, mapOf("opened" to true)) }
                                catch (_: Exception) { fail(result, "network_login_unavailable") }
                            }
                        }
                        DeferredResult
                    }
                }
                "nodeStop" -> {
                    exact(args, setOf("binding")); binding(args["binding"])
                    loginGate.invalidate()
                    submit(stops, result) { callNative(currentScope(), call.method, args) }
                }
                "streamOpen" -> {
                    exact(args, setOf("binding", "host", "port", "openId")); binding(args["binding"])
                    string(args["host"], 253); integer(args["port"], 1, 65535)
                    val id = string(args["openId"], 19)
                    if (!Regex("[1-9][0-9]{0,18}").matches(id) || id.toLongOrNull() == null) throw BridgeFailure("invalid_network_request")
                    submit(fast, result) {
                        val owned = currentScope(); envelope(nativeReserveOpen(owned, id))
                        try {
                            opens.execute {
                                try { if (!closed.get()) succeed(result, callNative(owned, call.method, args)) }
                                catch (e: BridgeFailure) { fail(result, e.code) }
                                catch (_: LinkageError) { fail(result, "overlay_provider_unavailable") }
                                catch (_: Exception) { fail(result, "network_native_failed") }
                            }
                        } catch (_: RejectedExecutionException) {
                            callNative(owned, "cancelOpen", mapOf("openId" to id))
                            throw BridgeFailure("network_worker_busy")
                        }
                        // This task posts its own result after the blocking open.
                        DeferredResult
                    }
                }
                "cancelOpen" -> {
                    exact(args, setOf("openId")); string(args["openId"], 19)
                    submit(fast, result) { callNative(currentScope(), call.method, args) }
                }
                "streamRead" -> {
                    exact(args, setOf("streamId", "maxBytes")); token(args["streamId"]); integer(args["maxBytes"], 1, MAX_IO.toLong())
                    submit(reads, result) { callNative(currentScope(), call.method, args) }
                }
                "streamWrite" -> {
                    exact(args, setOf("streamId", "bytes")); token(args["streamId"])
                    val payload = args["bytes"] as? ByteArray ?: throw BridgeFailure("invalid_network_request")
                    if (payload.size > MAX_IO) { payload.fill(0); throw BridgeFailure("invalid_network_request") }
                    submit(writes, result, payload) { callNative(currentScope(), call.method, mapOf("streamId" to args["streamId"]), payload) }
                }
                "streamFlush", "streamShutdown" -> {
                    exact(args, setOf("streamId")); token(args["streamId"])
                    submit(writes, result) { callNative(currentScope(), call.method, args) }
                }
                "streamClose" -> {
                    exact(args, setOf("streamId")); token(args["streamId"])
                    submit(fast, result) { callNative(currentScope(), call.method, args) }
                }
                else -> result.notImplemented()
            }
        } catch (e: BridgeFailure) {
            if (call.method == "streamWrite") ((call.arguments as? Map<*, *>)?.get("bytes") as? ByteArray)?.fill(0)
            fail(result, e.code)
        } catch (_: Exception) {
            if (call.method == "streamWrite") ((call.arguments as? Map<*, *>)?.get("bytes") as? ByteArray)?.fill(0)
            fail(result, "invalid_network_request")
        }
    }
    private object DeferredResult

    /** Retire only this engine scope. Native cleanup remains accounted until confirmed. */
    fun close() {
        if (!closed.compareAndSet(false, true)) return
        loginGate.foreground(false)
        channel.setMethodCallHandler(null)
        val owned = synchronized(lifecycle) { val value = scope; scope = 0; value }
        // Native retirement is nonblocking, but still never call JNI on the UI thread.
        if (owned != 0L) Thread({ try { nativeCloseScope(owned) } catch (_: LinkageError) {} catch (_: Exception) {} }, "pocket-network-detach").apply { isDaemon = true; start() }
        workers.forEach { executor -> executor.shutdownNow().forEach { if (it is OwnedTask) it.abort() } }
    }
}
