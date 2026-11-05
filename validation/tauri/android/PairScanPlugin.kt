package org.herdr.pocket

import android.app.Activity
import androidx.activity.result.ActivityResult
import app.tauri.annotation.ActivityCallback
import app.tauri.annotation.Command
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.JSObject
import app.tauri.plugin.Plugin
import java.util.concurrent.atomic.AtomicBoolean
import org.herdr.pairing.camera.PairScan

@TauriPlugin
class PairScanPlugin(private val activity: Activity) : Plugin(activity) {
    private val busy = AtomicBoolean(false)
    @Command fun scan(invoke: Invoke) {
        if (!busy.compareAndSet(false, true)) { invoke.reject("scan_busy"); return }
        try { startActivityForResult(invoke, PairScan.intent(activity), "completed") }
        catch (_: RuntimeException) { busy.set(false); invoke.reject("camera_unavailable") }
    }
    @ActivityCallback fun completed(invoke: Invoke, result: ActivityResult) {
        busy.set(false)
        try { invoke.resolve(JSObject().apply { put("text", PairScan.result(result.resultCode, result.data)) }) }
        catch (e: IllegalStateException) { invoke.reject(e.message ?: "scan_cancelled") }
    }
}
