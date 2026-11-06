package dev.herdr.herdr_flutter_probe

import android.app.Activity
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import org.herdr.network.AndroidTailscaleStateStore
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Channel probe uses only fake Android classes and a synthetic identity store. */
fun main() {
    val channel = NetworkIdentityChannel(Activity(), object: BinaryMessenger {})
    var checks = 0
    fun check(value: Boolean) { if (!value) error("identity assertion $checks"); checks++ }
    fun invoke(method: String, args: Map<String, Any>): Pair<Any?, String?> {
        val done = CountDownLatch(1)
        var value: Any? = null; var error: String? = null
        MethodChannel.fire("dev.herdr/network-identity", MethodCall(method,args), object: MethodChannel.Result {
            override fun success(v: Any?) { value=v; done.countDown() }
            override fun error(code: String, message: String, details: Any?) { error=code; done.countDown() }
            override fun notImplemented() { error="notImplemented"; done.countDown() }
        })
        check(done.await(3,TimeUnit.SECONDS))
        return value to error
    }
    val base = mapOf("profileId" to "a".repeat(32), "provider" to "tailscale")
    val (created, createError) = invoke("create",base)
    check(createError == null && (created as Map<*, * >)["mode"] == "DEVICE_STATE")
    check(AndroidTailscaleStateStore.creates == 1)
    val secret = byteArrayOf(1,2,3)
    check(invoke("create",base + mapOf("mode" to "PRIVATE", "secret" to secret)).second == "network_identity_invalid")
    check(secret.all { it == 0.toByte() } && AndroidTailscaleStateStore.creates == 1)
    val record = invoke("status",base).first as Map<*, *>
    check(record["provider"] == "tailscale" && record["handle"] == "11111111-1111-4111-8111-111111111111")
    check(invoke("delete",base + ("handle" to "wrong")).second == "network_identity_write_unknown")
    check(AndroidTailscaleStateStore.deletes == 0)
    check(invoke("delete",base + ("handle" to record["handle"]!!)).second == null)
    check(AndroidTailscaleStateStore.deletes == 1)
    channel.close()
    println("Kotlin identity channel: $checks checks passed; synthetic store only")
}
