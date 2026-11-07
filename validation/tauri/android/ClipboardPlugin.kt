package org.herdr.pocket

import android.app.Activity
import android.content.ClipData
import android.content.ClipDescription
import android.content.ClipboardManager
import android.content.Context
import android.os.SystemClock
import android.webkit.WebView
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.Lifecycle
import app.tauri.annotation.Command
import app.tauri.annotation.InvokeArg
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.JSObject
import app.tauri.plugin.Plugin

@InvokeArg
class PairingRequestCopyArgs {
    var text: String = ""
    var issuedAt: Long = 0
    var expiresAt: Long = 0
}

/** Explicit foreground read or native public-request copy. No listener or retry. */
@TauriPlugin
class ClipboardPlugin(private val activity: Activity) : Plugin(activity) {
    @Volatile private var webView: WebView? = null
    @Volatile private var foreground = 0L

    override fun load(view: WebView) { foreground++; webView = view }
    override fun onPause(activity: AppCompatActivity) { foreground++ }

    private fun present(view: WebView): Boolean = webView === view && focused() &&
        view.hasWindowFocus() && view.hasFocus() && view.isAttachedToWindow

    @Command fun copyPairingRequest(invoke: Invoke) {
        val created = SystemClock.elapsedRealtime()
        val generation = foreground
        val args = try { invoke.parseArgs(PairingRequestCopyArgs::class.java) } catch (_: Exception) {
            invoke.resolve(JSObject().also { it.put("error", "clipboard_unsupported") }); return
        }
        activity.runOnUiThread {
            val reply = JSObject()
            try {
                val view = webView ?: error("clipboard_unfocused")
                fun reviewed() {
                    check(generation == foreground && present(view) &&
                        SystemClock.elapsedRealtime() - created in 0L until 2000L) { "clipboard_unfocused" }
                    val now = System.currentTimeMillis() / 1000
                    check(args.issuedAt >= 0 && args.expiresAt > args.issuedAt && args.expiresAt - args.issuedAt <= 600 &&
                        now in args.issuedAt until args.expiresAt) { "pairing_copy_expired" }
                }
                reviewed()
                val text = ClipboardText.bounded(args.text, 2048)
                val manager = activity.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
                    ?: error("clipboard_unavailable")
                val clip = ClipData.newPlainText("herdr-pocket public pairing request", text)
                reviewed()
                // One write, no clipboard read and no retry after any failure.
                manager.setPrimaryClip(clip)
                reply.put("copied", true)
            } catch (failure: Exception) {
                val code = failure.message
                reply.put("error", if (code in ClipboardText.ERRORS || code == "pairing_copy_expired") code else "clipboard_unavailable")
            }
            invoke.resolve(reply)
        }
    }

    private fun focused(): Boolean = !activity.isFinishing && !activity.isDestroyed &&
        activity.hasWindowFocus() && (activity as? AppCompatActivity)?.lifecycle?.currentState
            ?.isAtLeast(Lifecycle.State.RESUMED) == true

    @Command fun readText(invoke: Invoke) {
        activity.runOnUiThread {
            val reply = JSObject()
            try {
                check(focused()) { "clipboard_unfocused" }
                val manager = activity.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
                    ?: error("clipboard_unavailable")
                val description = manager.primaryClipDescription ?: error("clipboard_empty")
                check(plainText(description)) { "clipboard_unsupported" }
                // Fetch exactly once, then recheck its description in case the clip changed.
                val clip = manager.primaryClip ?: error("clipboard_empty")
                check(focused()) { "clipboard_unfocused" }
                check(plainText(clip.description)) { "clipboard_unsupported" }
                check(clip.itemCount > 0) { "clipboard_empty" }
                val item = clip.getItemAt(0)
                check(item.uri == null && item.intent == null) { "clipboard_unsupported" }
                val value = item.text ?: error("clipboard_unsupported")
                val text = ClipboardText.bounded(value)
                check(focused()) { "clipboard_unfocused" }
                reply.put("text", text)
            } catch (failure: Exception) {
                val code = failure.message
                reply.put("error", if (code in ClipboardText.ERRORS) code else "clipboard_unavailable")
            }
            invoke.resolve(reply)
        }
    }

    private fun plainText(description: ClipDescription): Boolean =
        description.hasMimeType("text/plain") && (0 until description.mimeTypeCount).all {
            description.getMimeType(it) in setOf("text/plain", "text/html")
        }
}

internal object ClipboardText {
    const val MAX_BYTES = 4096
    val ERRORS = setOf("clipboard_empty", "clipboard_unsupported", "clipboard_unfocused",
        "clipboard_too_large", "clipboard_unavailable")

    fun bounded(value: CharSequence, limit: Int = MAX_BYTES): String {
        val units = value.length
        check(units > 0) { "clipboard_empty" }
        // Every UTF-16 unit needs at least one UTF-8 byte. Never copy a huge value.
        check(units <= limit) { "clipboard_too_large" }
        val result = StringBuilder(units)
        var bytes = 0
        var index = 0
        while (index < units) {
            val ch = value[index++]
            when {
                ch.isHighSurrogate() -> {
                    check(index < units) { "clipboard_unsupported" }
                    val low = value[index++]
                    check(low.isLowSurrogate()) { "clipboard_unsupported" }
                    bytes += 4
                    check(bytes <= limit) { "clipboard_too_large" }
                    result.append(ch).append(low)
                }
                ch.isLowSurrogate() -> error("clipboard_unsupported")
                else -> {
                    bytes += if (ch.code < 0x80) 1 else if (ch.code < 0x800) 2 else 3
                    check(bytes <= limit) { "clipboard_too_large" }
                    result.append(ch)
                }
            }
        }
        return result.toString()
    }
}
