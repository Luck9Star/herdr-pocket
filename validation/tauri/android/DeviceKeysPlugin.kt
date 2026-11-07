package org.herdr.pocket

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.webkit.WebView
import android.util.Base64
import app.tauri.annotation.Command
import app.tauri.annotation.InvokeArg
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.JSObject
import app.tauri.plugin.Plugin
import org.herdr.pairing.AndroidDeviceKeyStore
import org.herdr.network.AndroidNetworkSecretStore
import org.herdr.network.AndroidEasyTierConfig
import org.herdr.network.AndroidTailscaleConfig
import org.herdr.network.AndroidTailscaleStateStore
import org.herdr.network.AndroidZeroTierDeviceService
import org.json.JSONObject
import java.util.concurrent.SynchronousQueue
import java.util.concurrent.atomic.AtomicLong
import androidx.lifecycle.Lifecycle
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit
import java.util.concurrent.RejectedExecutionException
import androidx.appcompat.app.AppCompatActivity

@InvokeArg
class NetworkIdentityArgs { var profileId: String = ""; var provider: String = ""; var mode: String = ""; var secret: String = ""; var expectedHandle: String = "" }

@InvokeArg
class ZeroTierDeviceArgs { var action: String = ""; var handle: String? = null; var instanceId: String? = null; var expectedPhase: String? = null; var operationId: Long = 0 }

@InvokeArg
class ZeroTierFenceArgs { var operationId: Long = 0 }

@InvokeArg
class NetworkAuthArgs { var url: String = "" }

@InvokeArg
class KeyArgs { var handle: String = ""; var payload: String = "" }

// The Rust host is the sole serial producer. The watermark permanently seals
// every earlier ID, including a dispatch that arrives after its fence.
internal class ZeroTierCompletion {
    private var watermark:Long=0
    private var active:Long=0
    private var finished:Boolean=false
    @Synchronized fun register(id:Long):Boolean {
        if(id<=watermark || active!=0L)return false
        active=id;finished=false;return true
    }
    @Synchronized fun finish(id:Long) {if(active==id)finished=true}
    @Synchronized fun fence(id:Long):Boolean {
        if(id<=0)return false
        if(active!=0L && active!=id)return false
        if(active==id && !finished)return false
        if(active==id){active=0;finished=false}
        if(id>watermark)watermark=id
        return true
    }
}

// This plugin is registered only for calls from Rust; no seed crosses the bridge.
@TauriPlugin
class DeviceKeysPlugin(private val activity: Activity): Plugin(activity) {
    override fun load(webView: WebView) {
        super.load(webView)
        synchronized(this) {
            if (!zeroTierClosed && !zeroTierPaused && (activity as? AppCompatActivity)?.lifecycle?.currentState?.isAtLeast(Lifecycle.State.RESUMED)==true) {
                zeroTierEpoch.incrementAndGet();zeroTierForeground=true
            }
        }
        // Context registration only. No identity read, engine start or retry loop.
        try { AndroidEasyTierConfig.bindNative(activity.applicationContext) } catch (_:LinkageError) {} catch (_:Exception) {}
        try { AndroidTailscaleConfig.bindNative(activity.applicationContext) } catch (_:LinkageError) {} catch (_:Exception) {}
    }
    // No queued writes: background and destroyed activities invalidate each dispatch.
    private val zeroTierExecutor = ThreadPoolExecutor(1,1,0L,TimeUnit.MILLISECONDS,SynchronousQueue<Runnable>())
    private val zeroTierEpoch = AtomicLong(0)
    @Volatile private var zeroTierForeground = false
    @Volatile private var zeroTierClosed = false
    private var zeroTierPaused = false
    companion object {
        // Process lifetime, independent of Activity/plugin instances.
        private val zeroTierCompletion = ZeroTierCompletion()
    }
    override fun onResume(activity: AppCompatActivity) { super.onResume(activity);synchronized(this){zeroTierEpoch.incrementAndGet();zeroTierPaused=false;if(!zeroTierClosed)zeroTierForeground=true} }
    override fun onPause(activity: AppCompatActivity) { synchronized(this){zeroTierEpoch.incrementAndGet();zeroTierPaused=true;zeroTierForeground=false};super.onPause(activity) }
    private fun zeroTierOperation(invoke: Invoke, finished:()->Unit = {}, block:()->JSObject) {
        val epoch=zeroTierEpoch.get()
        fun live() = !zeroTierClosed && zeroTierForeground && zeroTierEpoch.get()==epoch && !activity.isFinishing && !activity.isDestroyed
        if(!live()) {finished();invoke.reject("zerotier_device_unavailable");return}
        try {zeroTierExecutor.execute {
            try {val reply=try {if(!live())throw IllegalStateException();block()} finally {finished()};if(!live())throw IllegalStateException();invoke.resolve(reply)}
            catch (_:Exception) {invoke.reject("zerotier_device_result_unknown")}
            catch (_:LinkageError) {invoke.reject("zerotier_device_unavailable")}
        }} catch (_:RejectedExecutionException) {finished();invoke.reject("zerotier_device_unavailable")}
    }
    @Command fun zeroTierDeviceStatus(invoke:Invoke) = zeroTierOperation(invoke) {
        val snapshot=AndroidZeroTierDeviceService.status()
        val payload=JSONObject()
        for(key in listOf("available","device","pendingCreation","pendingDeletion")) {
            require(snapshot.containsKey(key))
            val value=snapshot[key]
            payload.put(key,if(value is Map<*,*>) JSONObject(value) else value ?: JSONObject.NULL)
        }
        JSObject().apply {put("payload",payload)}
    }
    @Command fun zeroTierDeviceWrite(invoke:Invoke) {
        val args=invoke.parseArgs(ZeroTierDeviceArgs::class.java)
        if(!zeroTierCompletion.register(args.operationId)) {invoke.reject("zerotier_device_unavailable");return}
        zeroTierOperation(invoke,{zeroTierCompletion.finish(args.operationId)}) {
            val result=AndroidZeroTierDeviceService.write(args.action,args.handle,args.instanceId,args.expectedPhase)
            JSObject().apply {put("present",result!=null);if(result!=null)put("device",JSONObject(result))}
        }
    }
    @Command fun zeroTierDeviceFence(invoke:Invoke) {
        val args=invoke.parseArgs(ZeroTierFenceArgs::class.java)
        if(args.operationId<=0) {invoke.reject("zerotier_device_unavailable");return}
        try {invoke.resolve(JSObject().apply {put("finished",zeroTierCompletion.fence(args.operationId))})} catch (_:Exception) {invoke.reject("zerotier_device_unavailable")}
    }
    private val networkExecutor = ThreadPoolExecutor(1,1,0L,TimeUnit.MILLISECONDS,ArrayBlockingQueue<Runnable>(1))
    private class NetworkTask(val invoke:Invoke,val args:NetworkIdentityArgs,val block:()->JSObject):Runnable {
        override fun run() { try { val result=try {block()} finally {args.secret=""}; invoke.resolve(result) } catch (_:Exception) { args.secret="";invoke.reject("network_identity_unavailable") } }
        fun abort() { args.secret=""; try { invoke.reject("network_identity_unavailable") } catch (_:Exception) {} }
    }
    private fun networkOperation(invoke: Invoke,args:NetworkIdentityArgs,block: () -> JSObject) {
        val task=NetworkTask(invoke,args,block)
        try { networkExecutor.execute(task) } catch (_:RejectedExecutionException) { task.abort() }
    }
    override fun onDestroy(activity: AppCompatActivity) {
        synchronized(this){zeroTierClosed=true;zeroTierForeground=false;zeroTierEpoch.incrementAndGet()};zeroTierExecutor.shutdown()
        for (task in networkExecutor.shutdownNow()) { if (task is NetworkTask) task.abort() }
        super.onDestroy(activity)
    }
    private fun metadata(result: AndroidNetworkSecretStore.Result?): JSObject = JSObject().apply {
        put("present", result != null)
        if (result != null) { put("provider",result.provider);put("profileId",result.profileId);put("mode", result.mode.name); put("handle", result.handle); put("instanceId", result.instanceId) }
    }
    private fun tailscaleMetadata(result: AndroidTailscaleStateStore.Result?): JSObject = JSObject().apply {
        put("present",result != null)
        if (result != null) {put("provider",result.provider);put("profileId",result.profileId);put("mode","DEVICE_STATE");put("handle",result.handle);put("instanceId",result.instanceId)}
    }
    @Command fun networkIdentityStatus(invoke: Invoke) {
        val args=invoke.parseArgs(NetworkIdentityArgs::class.java)
        networkOperation(invoke,args) {
            require(args.mode.isEmpty() && args.secret.isEmpty() && args.expectedHandle.isEmpty())
            if (Build.VERSION.SDK_INT < 35) JSObject().apply {put("supported", false);put("present", false)}
            else when(args.provider) {
                "easytier" -> metadata(AndroidNetworkSecretStore(activity.applicationContext).status(args.profileId,args.provider))
                "tailscale" -> tailscaleMetadata(AndroidTailscaleStateStore(activity.applicationContext).status(args.profileId))
                else -> throw IllegalArgumentException()
            }
        }
    }
    @Command fun networkIdentityCreate(invoke: Invoke) {
        val args=invoke.parseArgs(NetworkIdentityArgs::class.java)
        networkOperation(invoke,args) {
            require(args.expectedHandle.isEmpty())
            if(args.provider=="tailscale") {
                require(args.mode=="DEVICE_STATE" && args.secret.isEmpty())
                tailscaleMetadata(AndroidTailscaleStateStore(activity.applicationContext).create(args.profileId))
            } else {
                require(args.provider=="easytier")
                val bytes=args.secret.toByteArray(Charsets.UTF_8); args.secret=""
                try {metadata(AndroidNetworkSecretStore(activity.applicationContext).create(args.profileId,args.provider,AndroidNetworkSecretStore.SecretMode.valueOf(args.mode),bytes))} finally {bytes.fill(0)}
            }
        }
    }
    @Command fun networkIdentityDelete(invoke: Invoke) {
        val args=invoke.parseArgs(NetworkIdentityArgs::class.java)
        networkOperation(invoke,args) {
            require(args.mode.isEmpty() && args.secret.isEmpty())
            when(args.provider) {
                "easytier" -> AndroidNetworkSecretStore(activity.applicationContext).delete(args.profileId,args.provider,args.expectedHandle)
                "tailscale" -> AndroidTailscaleStateStore(activity.applicationContext).delete(args.profileId,args.expectedHandle)
                else -> throw IllegalArgumentException()
            }; JSObject()
        }
    }
    // Rust alone calls this after validating the catalog, original node attempt,
    // current auth URL and ephemeral review token. No generic opener is exposed.
    @Command fun openNetworkAuthUrl(invoke:Invoke) {
        val args=invoke.parseArgs(NetworkAuthArgs::class.java)
        try {
            require(NetworkAuthReview.validUrl(args.url))
            val uri=Uri.parse(args.url)
            activity.runOnUiThread {
                try {require(!activity.isFinishing && !activity.isDestroyed);activity.startActivity(Intent(Intent.ACTION_VIEW,uri));invoke.resolve(JSObject())}
                catch (_:Exception) {invoke.reject("network_auth_open_unavailable")}
            }
        } catch (_:Exception) {invoke.reject("network_auth_open_unavailable")}
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
