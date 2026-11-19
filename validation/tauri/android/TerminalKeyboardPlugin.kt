package org.herdr.pocket

import android.app.Activity
import android.content.Context
import android.os.SystemClock
import android.os.Build
import android.graphics.Rect
import android.view.WindowInsets
import android.view.inputmethod.InputMethodManager
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
class TerminalKeyboardArgs {
    var ticket: String = ""
    var action: String = ""
}

@TauriPlugin
class TerminalKeyboardPlugin(private val activity: Activity) : Plugin(activity) {
    private var webView: WebView? = null
    private var foreground = 0L
    private var issued = 0L
    private var applied = 0L

    override fun load(webView: WebView) {
        foreground++
        this.webView = webView
    }

    override fun onPause(activity: AppCompatActivity) {
        foreground++
    }

    private fun active(view: WebView): Boolean =
        webView === view && !activity.isFinishing && !activity.isDestroyed &&
            (activity as? AppCompatActivity)?.lifecycle?.currentState?.isAtLeast(Lifecycle.State.RESUMED) == true &&
            activity.hasWindowFocus() && view.hasWindowFocus() && view.isAttachedToWindow && view.hasFocus()

    @Command
    fun topInset(invoke: Invoke) {
        activity.runOnUiThread {
            val view = webView
            val insets = view?.rootWindowInsets
            if (view == null || insets == null) {
                invoke.reject("insets_unavailable")
                return@runOnUiThread
            }
            @Suppress("DEPRECATION")
            val status = if (Build.VERSION.SDK_INT >= 30) insets.getInsets(WindowInsets.Type.statusBars()).top else insets.systemWindowInsetTop
            val stableStatus = if (Build.VERSION.SDK_INT >= 30) insets.getInsetsIgnoringVisibility(WindowInsets.Type.statusBars()).top else insets.stableInsetTop
            val cutout = if (Build.VERSION.SDK_INT >= 30) insets.getInsets(WindowInsets.Type.displayCutout()).top else 0
            val caption = if (Build.VERSION.SDK_INT >= 30) insets.getInsets(WindowInsets.Type.captionBar()).top else 0
            val stableCaption = if (Build.VERSION.SDK_INT >= 30) insets.getInsetsIgnoringVisibility(WindowInsets.Type.captionBar()).top else 0
            val top = maxOf(status, stableStatus, cutout, caption, stableCaption)
            val location = IntArray(2)
            view.getLocationOnScreen(location)
            val windowBounds = if (Build.VERSION.SDK_INT >= 30) activity.windowManager.currentWindowMetrics.bounds else null
            val windowTop = windowBounds?.top
            val safeTop = if (windowTop != null) windowTop + top else Rect().also { view.getWindowVisibleDisplayFrame(it) }.top
            val overlap = (safeTop - location[1]).coerceAtLeast(0)
            invoke.resolve(JSObject().apply {
                put("overlapPx", overlap); put("systemBottomPx", safeTop); put("viewY", location[1])
                put("statusPx", status); put("stableStatusPx", stableStatus)
                if (windowTop != null) {
                    put("windowTopPx", windowTop); put("cutoutPx", cutout)
                    put("captionPx", caption); put("stableCaptionPx", stableCaption)
                }
                if (Build.VERSION.SDK_INT >= 30 && windowBounds != null && view.height > 0 && active(view)) {
                    val ime = WindowInsets.Type.ime()
                    val visible = insets.isVisible(ime)
                    put("imeVisible", visible)
                    val bottom = insets.getInsets(ime).bottom
                    if (visible && bottom in 1..windowBounds.height()) {
                        val imeTop = windowBounds.bottom - bottom
                        put("imeOverlapPx", (location[1] + view.height - imeTop).coerceIn(0, view.height))
                        put("viewHeightPx", view.height)
                    }
                }
            })
        }
    }

    @Command
    fun request(invoke: Invoke) {
        val args = invoke.parseArgs(TerminalKeyboardArgs::class.java)
        val show = args.action == "show"
        if ((!show && args.action != "hide") || !args.ticket.matches(Regex("[0-9a-f]{32}"))) {
            invoke.reject("keyboard_invalid_gesture")
            return
        }
        val created = SystemClock.elapsedRealtime()
        activity.runOnUiThread {
            val view = webView
            if (view == null || !active(view)) {
                invoke.reject("keyboard_unfocused")
                return@runOnUiThread
            }
            val generation = foreground
            val order = ++issued
            val check = "globalThis.__herdrPocketKeyboardGesture?.('${args.ticket}','${args.action}') === true"
            view.evaluateJavascript(check) { accepted ->
                if (accepted == "true" && generation == foreground && order > applied &&
                    SystemClock.elapsedRealtime() - created < 2000 && active(view)) {
                    applied = order
                    val ime = activity.getSystemService(Context.INPUT_METHOD_SERVICE) as? InputMethodManager
                    if (show) ime?.showSoftInput(view, 0)
                    else ime?.hideSoftInputFromWindow(view.windowToken, 0)
                }
            }
            // Only the OS/insets can confirm visibility. The call has been queued.
            invoke.resolve(JSObject())
        }
    }
}
