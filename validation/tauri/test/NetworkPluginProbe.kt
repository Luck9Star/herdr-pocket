package org.herdr.pocket
import app.tauri.plugin.Invoke
import org.herdr.network.AndroidTailscaleStateStore
import org.herdr.network.AndroidTailscaleConfig
import org.herdr.network.AndroidEasyTierConfig
import org.herdr.network.AndroidZeroTierDeviceService

fun main() {
    var checks=0
    var sequence=0
    fun ztArgs()=ZeroTierDeviceArgs().apply{operationId=(++sequence).toLong()}
    fun verify(condition:Boolean){check(condition);checks++}
    fun awaitWrite(plugin:DeviceKeysPlugin,call:Invoke) {call.await();val args=call.args as ZeroTierDeviceArgs;val fence=Invoke(ZeroTierFenceArgs().apply{operationId=args.operationId});plugin.zeroTierDeviceFence(fence);fence.await();check(fence.result["finished"]==true)}
    val completion=ZeroTierCompletion()
    verify(!completion.register(0));verify(completion.register(1));verify(!completion.fence(2));verify(!completion.fence(1));completion.finish(1);verify(completion.fence(1));verify(!completion.register(1));verify(completion.fence(2));verify(!completion.register(2))
    val collision=ZeroTierCompletion();verify(collision.register(11));verify(!collision.fence(12));collision.finish(11);verify(collision.fence(11));verify(collision.register(12));collision.finish(11);verify(!collision.fence(12));collision.finish(12);verify(collision.fence(12));verify(collision.fence(20));verify(!collision.register(20));verify(!collision.register(19));verify(collision.register(21))
    for(id in 3L..1100L){verify(completion.register(id));completion.finish(id);verify(completion.fence(id));verify(!completion.register(id))}
    val activity=androidx.appcompat.app.AppCompatActivity()
    val plugin=DeviceKeysPlugin(activity)
    try {
        plugin.load(android.webkit.WebView())
        verify(AndroidTailscaleConfig.binds==1 && AndroidEasyTierConfig.binds==1)
        fun args(mode:String="DEVICE_STATE",secret:String="",handle:String="")=NetworkIdentityArgs().apply {profileId="a".repeat(32);provider="tailscale";this.mode=mode;this.secret=secret;expectedHandle=handle}
        val create=Invoke(args());plugin.networkIdentityCreate(create);create.await()
        verify(create.error==null && create.result["mode"]=="DEVICE_STATE" && create.result["provider"]=="tailscale" && create.result["profileId"]=="a".repeat(32))
        for(arg in listOf(args(secret="not-an-auth-key"),args(mode="PRIVATE"),args(handle=AndroidTailscaleStateStore.HANDLE))) {
            val rejected=Invoke(arg);plugin.networkIdentityCreate(rejected);rejected.await();verify(rejected.error=="network_identity_unavailable");verify(arg.secret.isEmpty())
        }
        verify(AndroidTailscaleStateStore.creates==1)
        val wrong=Invoke(args(mode="",handle="22222222-2222-4222-8222-222222222222"));plugin.networkIdentityDelete(wrong);wrong.await();verify(wrong.error!=null && AndroidTailscaleStateStore.deletes==0)
        val delete=Invoke(args(mode="",handle=AndroidTailscaleStateStore.HANDLE));plugin.networkIdentityDelete(delete);delete.await();verify(delete.error==null && AndroidTailscaleStateStore.deletes==1)
        for(url in listOf("http://login.test","https://user:pass@login.test","https://login.test#fragment","https://login.test/\\x","https://login.test/\n","https://login.test/"+"x".repeat(4096))) {
            verify(!NetworkAuthReview.validUrl(url));val call=Invoke(NetworkAuthArgs().apply{this.url=url});plugin.openNetworkAuthUrl(call);call.await();verify(call.error!=null)
        }
        verify(activity.opens==0)
        val open=Invoke(NetworkAuthArgs().apply {url="https://login.test/authorize?token=opaque"});plugin.openNetworkAuthUrl(open);open.await();verify(open.error==null && activity.opens==1)
        val background=Invoke(ztArgs().apply{action="create"});plugin.zeroTierDeviceWrite(background);awaitWrite(plugin,background);verify(background.error!=null && AndroidZeroTierDeviceService.writes==0)
        plugin.onResume(activity)
        val status=Invoke(null);plugin.zeroTierDeviceStatus(status);status.await();verify(status.error==null);val statusJson=org.json.JSONObject((status.result["payload"] as org.json.JSONObject).toString());verify(statusJson.length()==4 && !statusJson.getBoolean("available") && statusJson.has("device") && statusJson.isNull("device") && statusJson.has("pendingCreation") && statusJson.isNull("pendingCreation") && statusJson.has("pendingDeletion") && statusJson.isNull("pendingDeletion"))
        val noStore=Invoke(ztArgs().apply{action="create"});plugin.zeroTierDeviceWrite(noStore);awaitWrite(plugin,noStore);verify(noStore.error!=null && AndroidZeroTierDeviceService.writes==0)
        AndroidZeroTierDeviceService.available=true
        val old=Invoke(ztArgs().apply{action="forget";handle="11111111-1111-4111-8111-111111111111";instanceId="33333333-3333-4333-8333-333333333333"});plugin.zeroTierDeviceWrite(old);awaitWrite(plugin,old);verify(old.error!=null)
        AndroidZeroTierDeviceService.expectedPhase="record-removed"
        val wrongPhase=Invoke(ztArgs().apply{action="recoverPendingDeletion";handle="11111111-1111-4111-8111-111111111111";expectedPhase="record-present"});plugin.zeroTierDeviceWrite(wrongPhase);awaitWrite(plugin,wrongPhase);verify(wrongPhase.error!=null && AndroidZeroTierDeviceService.lastPhase=="record-present")
        val recovery=Invoke(ztArgs().apply{action="recoverPendingDeletion";handle="11111111-1111-4111-8111-111111111111";expectedPhase="record-removed"});plugin.zeroTierDeviceWrite(recovery);awaitWrite(plugin,recovery);verify(recovery.error==null && recovery.result["present"]==false && AndroidZeroTierDeviceService.lastPhase=="record-removed")
        AndroidZeroTierDeviceService.expectedPhase=null
        AndroidZeroTierDeviceService.entered=java.util.concurrent.CountDownLatch(1);AndroidZeroTierDeviceService.release=java.util.concurrent.CountDownLatch(1)
        val pendingArgs=ztArgs().apply{action="create"};val pending=Invoke(pendingArgs);plugin.zeroTierDeviceWrite(pending);verify(AndroidZeroTierDeviceService.entered.await(5,java.util.concurrent.TimeUnit.SECONDS))
        val pendingFence=Invoke(ZeroTierFenceArgs().apply{operationId=pendingArgs.operationId});plugin.zeroTierDeviceFence(pendingFence);pendingFence.await();verify(pendingFence.result["finished"]==false)
        val secondActivity=androidx.appcompat.app.AppCompatActivity();val secondPlugin=DeviceKeysPlugin(secondActivity);secondPlugin.onResume(secondActivity)
        val concurrent=Invoke(ztArgs().apply{action="create"});secondPlugin.zeroTierDeviceWrite(concurrent);concurrent.await();verify(concurrent.error!=null)
        plugin.onPause(activity);AndroidZeroTierDeviceService.release.countDown();pending.await();verify(pending.error!=null)
        val doneFence=Invoke(ZeroTierFenceArgs().apply{operationId=pendingArgs.operationId});plugin.zeroTierDeviceFence(doneFence);doneFence.await();verify(doneFence.result["finished"]==true)
        AndroidZeroTierDeviceService.entered=null;AndroidZeroTierDeviceService.release=null
        val afterOtherActivity=Invoke(ztArgs().apply{action="create"});secondPlugin.zeroTierDeviceWrite(afterOtherActivity);awaitWrite(secondPlugin,afterOtherActivity);verify(afterOtherActivity.error==null);secondPlugin.onDestroy(secondActivity)
        val lateArgs=ztArgs().apply{action="create"};val absentFence=Invoke(ZeroTierFenceArgs().apply{operationId=lateArgs.operationId});plugin.zeroTierDeviceFence(absentFence);absentFence.await();verify(absentFence.result["finished"]==true)
        val late=Invoke(lateArgs);plugin.zeroTierDeviceWrite(late);late.await();verify(late.error!=null)
        val paused=Invoke(ztArgs().apply{action="create"});plugin.zeroTierDeviceWrite(paused);awaitWrite(plugin,paused);verify(paused.error!=null)
        AndroidZeroTierDeviceService.entered=null;AndroidZeroTierDeviceService.release=null;plugin.onResume(activity)
        val laterActivity=androidx.appcompat.app.AppCompatActivity();val laterPlugin=DeviceKeysPlugin(laterActivity);laterPlugin.onResume(laterActivity)
        val replayAcrossActivity=Invoke(lateArgs);laterPlugin.zeroTierDeviceWrite(replayAcrossActivity);replayAcrossActivity.await();verify(replayAcrossActivity.error!=null)
        AndroidZeroTierDeviceService.entered=java.util.concurrent.CountDownLatch(1);AndroidZeroTierDeviceService.release=java.util.concurrent.CountDownLatch(1)
        val destroying=Invoke(ztArgs().apply{action="create"});laterPlugin.zeroTierDeviceWrite(destroying);verify(AndroidZeroTierDeviceService.entered.await(5,java.util.concurrent.TimeUnit.SECONDS))
        laterPlugin.onDestroy(laterActivity);AndroidZeroTierDeviceService.release.countDown();awaitWrite(laterPlugin,destroying);verify(destroying.error!=null)
        val destroyedCall=Invoke(ztArgs().apply{action="create"});laterPlugin.zeroTierDeviceWrite(destroyedCall);awaitWrite(laterPlugin,destroyedCall);verify(destroyedCall.error!=null)
        AndroidZeroTierDeviceService.entered=null;AndroidZeroTierDeviceService.release=null
        val resumedActivity=androidx.appcompat.app.AppCompatActivity();resumedActivity.lifecycle.currentState=androidx.lifecycle.Lifecycle.State.RESUMED
        val resumedPlugin=DeviceKeysPlugin(resumedActivity);resumedPlugin.load(android.webkit.WebView())
        val lateStatus=Invoke(null);resumedPlugin.zeroTierDeviceStatus(lateStatus);lateStatus.await();verify(lateStatus.error==null);resumedPlugin.onPause(resumedActivity);resumedPlugin.load(android.webkit.WebView());val pausedAfterLoad=Invoke(null);resumedPlugin.zeroTierDeviceStatus(pausedAfterLoad);pausedAfterLoad.await();verify(pausedAfterLoad.error!=null);resumedPlugin.onDestroy(resumedActivity)
        activity.destroyed=true
        val retired=Invoke(NetworkAuthArgs().apply {url="https://login.test/authorize?token=opaque"});plugin.openNetworkAuthUrl(retired);retired.await();verify(retired.error!=null && activity.opens==1)
        println("Tauri Kotlin probe: $checks checks passed (DEVICE_STATE, secret rejection, exact handle, context-only bind, reviewed HTTPS, destroyed Activity)")
    } finally {plugin.onDestroy(activity)}
}
