package org.herdr.pocket

import android.os.SystemClock
import android.view.inputmethod.InputMethodManager
import android.webkit.WebView
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.Lifecycle
import app.tauri.plugin.Invoke

fun main() {
    val activity = AppCompatActivity()
    val ime = InputMethodManager()
    val view = WebView()
    val plugin = TerminalKeyboardPlugin(activity)
    val token = "0123456789abcdef".repeat(2)
    activity.service = ime
    activity.lifecycle.currentState = Lifecycle.State.RESUMED
    plugin.load(view)
    val root = android.view.View().also { it.y = 100 }
    view.root = root
    activity.windowManager.metrics.bounds.top = 100
    view.y = 100
    view.insets.top = 56
    fun topInset(): Int {
        val request = Invoke()
        plugin.topInset(request)
        return request.result["overlapPx"] as Int
    }
    check(topInset() == 56)
    view.y = 156
    check(topInset() == 0)
    android.os.Build.VERSION.SDK_INT = 29
    view.y = 120
    view.visibleTop = 156
    check(topInset() == 36)
    android.os.Build.VERSION.SDK_INT = 35
    fun imeInsets() = Invoke().also { plugin.topInset(it) }.result
    activity.windowManager.metrics.bounds.bottom = 2440
    view.y = 100
    check(imeInsets()["imeVisible"] == false)
    check("imeOverlapPx" !in imeInsets())
    view.insets.imeVisible = true
    view.insets.imeBottom = 900
    check(imeInsets()["imeOverlapPx"] == 900 && imeInsets()["viewHeightPx"] == 2340)
    view.height = 1440
    check(imeInsets()["imeOverlapPx"] == 0 && imeInsets()["viewHeightPx"] == 1440)
    view.height = 2340
    view.y = 0
    check(imeInsets()["imeOverlapPx"] == 800)
    view.insets.imeBottom = 0
    check(imeInsets()["imeVisible"] == true && "imeOverlapPx" !in imeInsets())
    view.insets.imeBottom = 900
    activity.focus = false
    check("imeVisible" !in imeInsets())
    activity.focus = true
    android.os.Build.VERSION.SDK_INT = 29
    check("imeVisible" !in imeInsets())
    android.os.Build.VERSION.SDK_INT = 35
    check(ime.shown == 0 && ime.hidden == 0)
    fun send(action: String, ticket: String = token): Invoke {
        val request = Invoke()
        request.args = TerminalKeyboardArgs().also { it.action = action; it.ticket = ticket }
        plugin.request(request)
        return request
    }
    fun answer(value: String) = view.callbacks.removeAt(0).onReceiveValue(value)

    check(send("show").result != null && ime.shown == 0)
    check(view.script.contains("'$token','show'"))
    answer("true")
    check(ime.shown == 1 && ime.view === view)
    send("hide"); answer("true")
    check(ime.hidden == 1 && ime.token === view.windowToken)
    check(send("show", "not a ticket").rejection == "keyboard_invalid_gesture")
    check(send("input").rejection == "keyboard_invalid_gesture")
    view.focus = false
    check(send("show").rejection == "keyboard_unfocused")
    view.focus = true
    send("show"); answer("false")
    send("show"); view.attached = false; answer("true"); view.attached = true
    send("show"); activity.focus = false; answer("true"); activity.focus = true
    send("show"); plugin.onPause(activity); answer("true")
    send("show"); SystemClock.now += 2000; answer("true")
    send("show"); send("hide")
    view.callbacks.removeAt(1).onReceiveValue("true")
    answer("true")
    check(ime.shown == 1 && ime.hidden == 2)
    send("show"); plugin.load(WebView()); answer("true")
    check(ime.shown == 1 && view.callbacks.isEmpty())
    println("PASS: explicit show/hide, gesture, order, focus, timeout, pause and WebView replacement")
}
