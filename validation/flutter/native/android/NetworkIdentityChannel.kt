package dev.herdr.herdr_flutter_probe

import android.app.Activity
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodChannel
import org.herdr.network.AndroidNetworkSecretStore
import org.herdr.network.AndroidTailscaleStateStore
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit

/** Write-only provisioning plus verified public metadata; never expose withSecret. */
class NetworkIdentityChannel(private val activity: Activity, messenger: BinaryMessenger) {
    private val channel = MethodChannel(messenger, "dev.herdr/network-identity")
    private val worker = ThreadPoolExecutor(1, 1, 0L, TimeUnit.MILLISECONDS, ArrayBlockingQueue<Runnable>(8))
    init {
        channel.setMethodCallHandler { call, result ->
            if (call.method !in listOf("create", "status", "delete")) {
                result.notImplemented()
            } else {
                val arguments = call.arguments as? Map<*, *>
                val ts = arguments?.get("provider") == "tailscale"
                val expected = when (call.method) {
                    "create" -> if (ts) setOf("profileId", "provider") else setOf("profileId", "provider", "mode", "secret")
                    "delete" -> setOf("profileId", "provider", "handle")
                    else -> setOf("profileId", "provider")
                }
                val secret = arguments?.get("secret") as? ByteArray
                if (arguments == null || arguments.keys != expected ||
                    arguments["profileId"] !is String || arguments["provider"] !is String ||
                    (call.method == "create" && !ts && (arguments["mode"] !is String || secret == null || secret.size > 1024)) ||
                    (call.method == "delete" && arguments["handle"] !is String)) {
                    secret?.fill(0)
                    result.error("network_identity_invalid", "Invalid local network request", null)
                } else {
                    try {
                        worker.execute {
                            try {
                                val profile = arguments["profileId"] as String
                                val provider = arguments["provider"] as String
                                val value = if (ts) {
                                    val store = AndroidTailscaleStateStore(activity.applicationContext)
                                    when (call.method) {
                                        "status" -> store.status(profile)?.let(::tailscaleResult)
                                        "create" -> tailscaleResult(store.create(profile))
                                        "delete" -> { store.delete(profile, arguments["handle"] as String); null }
                                        else -> error("operation")
                                    }
                                } else {
                                    val store = AndroidNetworkSecretStore(activity.applicationContext)
                                    when (call.method) {
                                        "status" -> store.status(profile, provider)?.let(::publicResult)
                                        "create" -> publicResult(store.create(profile, provider,
                                            AndroidNetworkSecretStore.SecretMode.valueOf(arguments["mode"] as String), secret!!))
                                        "delete" -> { store.delete(profile, provider, arguments["handle"] as String); null }
                                        else -> error("operation")
                                    }
                                }
                                activity.runOnUiThread { result.success(value) }
                            } catch (_: Exception) {
                                val code = if (call.method == "status") "network_identity_unavailable" else "network_identity_write_unknown"
                                activity.runOnUiThread { result.error(code, "Protected local network operation not confirmed", null) }
                            } finally { secret?.fill(0) }
                        }
                    } catch (_: RejectedExecutionException) {
                        secret?.fill(0)
                        result.error("network_identity_busy", "Local network operation not admitted", null)
                    }
                }
            }
        }
    }
    private fun publicResult(value: AndroidNetworkSecretStore.Result): Map<String, String> = mapOf(
        "profileId" to value.profileId, "provider" to value.provider, "handle" to value.handle,
        "instanceId" to value.instanceId, "mode" to value.mode.name)
    private fun tailscaleResult(value: AndroidTailscaleStateStore.Result): Map<String, String> = mapOf(
        "profileId" to value.profileId, "provider" to value.provider, "handle" to value.handle,
        "instanceId" to value.instanceId, "mode" to "DEVICE_STATE")
    fun close() {
        channel.setMethodCallHandler(null)
        // Admitted writes complete once and clear their input, even when the UI goes away.
        worker.shutdown()
    }
}
