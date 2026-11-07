package org.herdr.pocket

import android.content.*
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.Lifecycle
import android.os.SystemClock
import android.webkit.WebView
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
    activity.service = manager
    val view = WebView()
    plugin.load(view)
    manager.reads = 0
    fun copy(text: String = "synthetic public request", expiry: Long = System.currentTimeMillis() / 1000 + 60, issued: Long = System.currentTimeMillis() / 1000 - 1): Invoke {
        val request = Invoke()
        request.args = PairingRequestCopyArgs().also { it.text = text; it.issuedAt = issued; it.expiresAt = expiry }
        plugin.copyPairingRequest(request)
        return request
    }
    fun failure(code: String, request: Invoke = copy()) {
        check(request.result!!["error"] == code) { "copy: expected $code got ${request.result}" }
        check(!request.result!!.containsKey("copied"))
    }
    check(copy().result!!["copied"] == true)
    check(manager.writes == 1 && manager.writeCalls == 1 && manager.reads == 0)
    check(manager.clip!!.getItemAt(0).text == "synthetic public request")
    failure("clipboard_too_large",copy("a".repeat(2049)))
    failure("clipboard_too_large",copy("界".repeat(683)))
    failure("clipboard_unsupported",copy("\uD800"))
    failure("pairing_copy_expired",copy(expiry=System.currentTimeMillis() / 1000))
    failure("pairing_copy_expired",copy(issued=System.currentTimeMillis() / 1000 + 10))
    failure("pairing_copy_expired",copy(expiry=System.currentTimeMillis() / 1000 + 601))
    check(manager.writeCalls == 1 && manager.reads == 0)
    for (mode in 0..6) {
        when(mode) {0->activity.focus=false;1->activity.finishing=true;2->activity.destroyed=true;
            3->activity.lifecycle.currentState=Lifecycle.State.STARTED;4->view.focus=false;5->view.windowFocus=false;6->view.attached=false}
        failure("clipboard_unfocused")
        activity.focus=true;activity.finishing=false;activity.destroyed=false;activity.lifecycle.currentState=Lifecycle.State.RESUMED
        view.focus=true;view.windowFocus=true;view.attached=true
    }
    activity.queued = true
    val paused = copy(); plugin.onPause(activity); activity.flush(); failure("clipboard_unfocused",paused)
    val late = copy(); SystemClock.now += 2000; activity.flush(); failure("clipboard_unfocused",late)
    val replaced = copy(); plugin.load(WebView()); activity.flush(); failure("clipboard_unfocused",replaced)
    activity.queued = false; plugin.load(view)
    activity.onService = Runnable { activity.focus=false }
    failure("clipboard_unfocused"); activity.onService=null; activity.focus=true
    check(manager.writeCalls == 1 && manager.reads == 0)
    activity.service=null; failure("clipboard_unavailable"); activity.service=manager
    manager.failWrites=true; failure("clipboard_unavailable");manager.failWrites=false
    check(manager.writeCalls == 2 && manager.writes == 1 && manager.reads == 0)
    check(copy("a".repeat(2048)).result!!["copied"] == true)
    check(manager.writeCalls == 3 && manager.writes == 2 && manager.reads == 0)
    println("ClipboardPlugin: read regressions and native pairing copy bounds, focus, presence, expiry, pause, replacement and exactly-one-write/no-read passed (synthetic stubs only).")
}
