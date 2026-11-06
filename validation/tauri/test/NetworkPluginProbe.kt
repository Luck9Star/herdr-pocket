package org.herdr.pocket
import app.tauri.plugin.Invoke
import org.herdr.network.AndroidTailscaleStateStore
import org.herdr.network.AndroidTailscaleConfig
import org.herdr.network.AndroidEasyTierConfig

fun main() {
    var checks=0
    fun verify(condition:Boolean){check(condition);checks++}
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
        activity.destroyed=true
        val retired=Invoke(NetworkAuthArgs().apply {url="https://login.test/authorize?token=opaque"});plugin.openNetworkAuthUrl(retired);retired.await();verify(retired.error!=null && activity.opens==1)
        println("Tauri Kotlin probe: $checks checks passed (DEVICE_STATE, secret rejection, exact handle, context-only bind, reviewed HTTPS, destroyed Activity)")
    } finally {plugin.onDestroy(activity)}
}
