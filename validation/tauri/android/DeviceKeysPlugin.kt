package org.herdr.pocket

import android.app.Activity
import android.os.Build
import android.util.Base64
import app.tauri.annotation.Command
import app.tauri.annotation.InvokeArg
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.JSObject
import app.tauri.plugin.Plugin
import org.herdr.pairing.AndroidDeviceKeyStore
import org.herdr.network.AndroidNetworkSecretStore
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit
import java.util.concurrent.RejectedExecutionException
import androidx.appcompat.app.AppCompatActivity

@InvokeArg
class NetworkIdentityArgs { var profileId: String = ""; var provider: String = ""; var mode: String = ""; var secret: String = ""; var expectedHandle: String = "" }

@InvokeArg
class KeyArgs { var handle: String = ""; var payload: String = "" }

// This plugin is registered only for calls from Rust; no seed crosses the bridge.
@TauriPlugin
class DeviceKeysPlugin(private val activity: Activity): Plugin(activity) {
    private val networkExecutor = ThreadPoolExecutor(1,1,0L,TimeUnit.MILLISECONDS,ArrayBlockingQueue<Runnable>(1))
    private class NetworkTask(val invoke:Invoke,val args:NetworkIdentityArgs,val block:()->JSObject):Runnable {
        override fun run() { try { invoke.resolve(block()) } catch (_:Exception) { invoke.reject("network_identity_unavailable") } finally { args.secret="" } }
        fun abort() { args.secret=""; try { invoke.reject("network_identity_unavailable") } catch (_:Exception) {} }
    }
    private fun networkOperation(invoke: Invoke,args:NetworkIdentityArgs,block: () -> JSObject) {
        val task=NetworkTask(invoke,args,block)
        try { networkExecutor.execute(task) } catch (_:RejectedExecutionException) { task.abort() }
    }
    override fun onDestroy(activity: AppCompatActivity) {
        for (task in networkExecutor.shutdownNow()) { if (task is NetworkTask) task.abort() }
        super.onDestroy(activity)
    }
    private fun metadata(result: AndroidNetworkSecretStore.Result?): JSObject = JSObject().apply {
        put("present", result != null)
        if (result != null) { put("mode", result.mode.name); put("handle", result.handle); put("instanceId", result.instanceId) }
    }
    @Command fun networkIdentityStatus(invoke: Invoke) {
        val args=invoke.parseArgs(NetworkIdentityArgs::class.java)
        networkOperation(invoke,args) { if (Build.VERSION.SDK_INT < 35) JSObject().apply {put("supported", false);put("present", false)} else metadata(AndroidNetworkSecretStore(activity.applicationContext).status(args.profileId,args.provider)) }
    }
    @Command fun networkIdentityCreate(invoke: Invoke) {
        val args=invoke.parseArgs(NetworkIdentityArgs::class.java)
        networkOperation(invoke,args) {
            val bytes=args.secret.toByteArray(Charsets.UTF_8); args.secret=""
            try {
                val mode=AndroidNetworkSecretStore.SecretMode.valueOf(args.mode)
                metadata(AndroidNetworkSecretStore(activity.applicationContext).create(args.profileId,args.provider,mode,bytes))
            } finally { bytes.fill(0) }
        }
    }
    @Command fun networkIdentityDelete(invoke: Invoke) {
        val args=invoke.parseArgs(NetworkIdentityArgs::class.java)
        networkOperation(invoke,args) {
            val store=AndroidNetworkSecretStore(activity.applicationContext)
            store.delete(args.profileId,args.provider,args.expectedHandle); JSObject()
        }
    }
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
