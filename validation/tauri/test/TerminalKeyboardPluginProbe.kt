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
