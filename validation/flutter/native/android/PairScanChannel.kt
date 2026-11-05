package dev.herdr.herdr_flutter_probe

import android.app.Activity
import android.content.Intent
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodChannel
import org.herdr.pairing.camera.PairScan

class PairScanChannel(private val activity: Activity, messenger: BinaryMessenger) {
    private var pending: MethodChannel.Result? = null
    private val channel = MethodChannel(messenger, "herdr.pocket/pair_scan")
    init {
        channel.setMethodCallHandler { call, answer ->
            when {
                call.method != "scan" -> answer.notImplemented()
                pending != null -> answer.error("scan_busy", null, null)
                else -> {
                    pending = answer
                    try { activity.startActivityForResult(PairScan.intent(activity), REQUEST) }
                    catch (_: RuntimeException) { pending = null; answer.error("camera_unavailable", null, null) }
                }
            }
        }
    }
    fun handle(code: Int, result: Int, data: Intent?): Boolean {
        if (code != REQUEST) return false
        val answer = pending ?: return true
        pending = null
        try { answer.success(PairScan.result(result, data)) }
        catch (e: IllegalStateException) { answer.error(e.message ?: "scan_failed", null, null) }
        return true
    }
    fun close() { channel.setMethodCallHandler(null); pending?.error("scan_cancelled", null, null); pending = null }
    companion object { private const val REQUEST = 0x4850 }
}
