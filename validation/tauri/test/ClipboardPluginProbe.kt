package org.herdr.pocket

import android.content.*
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.Lifecycle
import app.tauri.plugin.Invoke

fun main() {
    val activity = AppCompatActivity()
    val manager = ClipboardManager()
    activity.service = manager
    activity.lifecycle.currentState = Lifecycle.State.RESUMED
    val plugin = ClipboardPlugin(activity)
    fun clip(text: CharSequence?, vararg types: String) {
        manager.clip = ClipData(ClipDescription(types), arrayOf(ClipData.Item(text)))
        manager.reads = 0
    }
    fun read(expected: String? = null): String? {
        val invoke = Invoke()
        plugin.readText(invoke)
        check(invoke.result != null)
        check(invoke.result!!["error"] == expected)
        if (expected != null) check(!invoke.result!!.containsKey("text"))
        return invoke.result!!["text"] as? String
    }
    clip("draft", "text/plain")
    check(read() == "draft" && manager.reads == 1)
    clip("local", "text/plain", "text/html")
    check(read() == "local")
    clip("markup", "text/html")
    read("clipboard_unsupported"); check(manager.reads == 0)
    clip("mixed", "text/plain", "image/png")
    read("clipboard_unsupported"); check(manager.reads == 0)
    clip("draft", "text/plain")
    activity.focus = false
    read("clipboard_unfocused"); check(manager.reads == 0)
    activity.focus = true
    activity.lifecycle.currentState = Lifecycle.State.STARTED
    read("clipboard_unfocused"); check(manager.reads == 0)
    activity.lifecycle.currentState = Lifecycle.State.RESUMED
    activity.finishing = true
    read("clipboard_unfocused"); activity.finishing = false
    activity.destroyed = true
    read("clipboard_unfocused"); activity.destroyed = false
    manager.afterRead = Runnable { activity.focus = false }
    read("clipboard_unfocused")
    manager.afterRead = null; activity.focus = true
    manager.clip = null
    read("clipboard_empty")
    clip("", "text/plain"); read("clipboard_empty")
    clip(null, "text/plain"); read("clipboard_unsupported")
    clip("a", "text/plain")
    manager.clip!!.items[0].uri = Any()
    read("clipboard_unsupported")
    manager.clip!!.items[0].uri = null; manager.clip!!.items[0].intent = Any()
    read("clipboard_unsupported")
    manager.clip = ClipData(ClipDescription(arrayOf("text/plain")), emptyArray())
    read("clipboard_empty")
    manager.clip = ClipData(ClipDescription(arrayOf("text/plain")), arrayOf(ClipData.Item(null), ClipData.Item("never read")))
    read("clipboard_unsupported")
    clip("a".repeat(4096), "text/plain"); check(read()!!.length == 4096)
    clip("a".repeat(4097), "text/plain"); read("clipboard_too_large")
    clip("界".repeat(1365) + "a", "text/plain"); check(read()!!.toByteArray().size == 4096)
    clip("界".repeat(1366), "text/plain"); read("clipboard_too_large")
    clip("😀".repeat(1024), "text/plain"); check(read()!!.toByteArray().size == 4096)
    clip("😀".repeat(1025), "text/plain"); read("clipboard_too_large")
    clip("\uD800", "text/plain"); read("clipboard_unsupported")
    clip("\uDC00", "text/plain"); read("clipboard_unsupported")
    clip(object: CharSequence {
        override val length = 10000000
        override fun get(index: Int): Char = error("huge sequence accessed")
        override fun subSequence(startIndex: Int, endIndex: Int): CharSequence = error("copied")
        override fun toString(): String = error("copied")
    }, "text/plain")
    read("clipboard_too_large")
    clip(object: CharSequence {
        override val length = 4
        override fun get(index: Int): Char = "safe"[index]
        override fun subSequence(startIndex: Int, endIndex: Int): CharSequence = error("copied")
        override fun toString(): String = error("do not coerce or copy toString")
    }, "text/plain")
    check(read() == "safe")
    activity.service = null; read("clipboard_unavailable")
    println("ClipboardPlugin: foreground, MIME, first-item, typed errors, UTF-16 preflight and UTF-8 limits passed (synthetic stubs only).")
}
