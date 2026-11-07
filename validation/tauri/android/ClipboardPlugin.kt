package org.herdr.pocket

import android.app.Activity
import android.content.ClipDescription
import android.content.ClipboardManager
import android.content.Context
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.Lifecycle
import app.tauri.annotation.Command
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.JSObject
import app.tauri.plugin.Plugin

/** Explicit foreground read only. No clipboard listener, coercion, write or transport. */
@TauriPlugin
class ClipboardPlugin(private val activity: Activity) : Plugin(activity) {
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

    fun bounded(value: CharSequence): String {
        val units = value.length
        check(units > 0) { "clipboard_empty" }
        // Every UTF-16 unit needs at least one UTF-8 byte. Never copy a huge value.
        check(units <= MAX_BYTES) { "clipboard_too_large" }
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
                    check(bytes <= MAX_BYTES) { "clipboard_too_large" }
                    result.append(ch).append(low)
                }
                ch.isLowSurrogate() -> error("clipboard_unsupported")
                else -> {
                    bytes += if (ch.code < 0x80) 1 else if (ch.code < 0x800) 2 else 3
                    check(bytes <= MAX_BYTES) { "clipboard_too_large" }
                    result.append(ch)
                }
            }
        }
        return result.toString()
    }
}
