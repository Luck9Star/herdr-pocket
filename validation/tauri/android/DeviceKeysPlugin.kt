package org.herdr.pocket

import android.app.Activity
import android.util.Base64
import app.tauri.annotation.Command
import app.tauri.annotation.InvokeArg
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.JSObject
import app.tauri.plugin.Plugin
import org.herdr.pairing.AndroidDeviceKeyStore

@InvokeArg
class KeyArgs { var handle: String = ""; var payload: String = "" }

// This plugin is registered only for calls from Rust; no seed crosses the bridge.
@TauriPlugin
class DeviceKeysPlugin(private val activity: Activity): Plugin(activity) {
    private fun operation(invoke: Invoke, block: () -> JSObject) {
        try { invoke.resolve(block()) } catch (_: Exception) { invoke.reject("device_key_unavailable") }
    }
    @Command fun privateConfigRoot(invoke: Invoke) = operation(invoke) {
        JSObject().apply { put("path", activity.applicationContext.noBackupFilesDir.absolutePath) }
    }
    @Command fun create(invoke: Invoke) = operation(invoke) {
        val key = AndroidDeviceKeyStore(activity).create()
        JSObject().apply { put("handle", key.handle); put("publicKey", key.publicKey) }
    }
    @Command fun publicKey(invoke: Invoke) = operation(invoke) {
        val args=invoke.parseArgs(KeyArgs::class.java)
        JSObject().apply { put("publicKey", AndroidDeviceKeyStore(activity).publicKey(args.handle)) }
    }
    @Command fun sign(invoke: Invoke) = operation(invoke) {
        val args=invoke.parseArgs(KeyArgs::class.java)
        require(args.payload.length <= 87384)
        val data=Base64.decode(args.payload, Base64.NO_WRAP)
        require(data.size <= AndroidDeviceKeyStore.MAX_MESSAGE_BYTES)
        val sig=AndroidDeviceKeyStore(activity).sign(args.handle, data)
        JSObject().apply { put("signature", Base64.encodeToString(sig, Base64.NO_WRAP)) }
    }
    @Command fun delete(invoke: Invoke) = operation(invoke) {
        val args=invoke.parseArgs(KeyArgs::class.java)
        AndroidDeviceKeyStore(activity).delete(args.handle)
        JSObject()
    }
}
