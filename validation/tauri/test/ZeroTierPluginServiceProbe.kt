package org.herdr.pocket

import app.tauri.plugin.Invoke
import org.herdr.network.ZeroTierPluginServiceFixture as Fixture
import org.json.JSONObject

fun main(arguments:Array<String>) {
    var checks=0; var sequence=0L
    fun verify(value:Boolean) { check(value); checks++ }
    val activity=androidx.appcompat.app.AppCompatActivity()
    val plugin=DeviceKeysPlugin(activity)
    fun status():JSONObject {
        val call=Invoke(null);plugin.zeroTierDeviceStatus(call);call.await()
        verify(call.error==null)
        val value=JSONObject((call.result["payload"] as JSONObject).toString())
        verify(value.keySet()==setOf("available","device","pendingCreation","pendingDeletion"))
        return value
    }
    fun args(action:String,handle:String?=null,instance:String?=null,phase:String?=null)=
        ZeroTierDeviceArgs().apply {this.action=action;this.handle=handle;instanceId=instance;expectedPhase=phase;operationId=++sequence}
    fun fence(id:Long):Boolean {
        val call=Invoke(ZeroTierFenceArgs().apply{operationId=id})
        plugin.zeroTierDeviceFence(call);call.await();verify(call.error==null)
        return call.result["finished"]==true
    }
    fun write(value:ZeroTierDeviceArgs,accepted:Boolean):Invoke {
        val call=Invoke(value);plugin.zeroTierDeviceWrite(call);call.await()
        verify((call.error==null)==accepted);verify(fence(value.operationId));return call
    }
    try {
        plugin.onResume(activity)
        val unavailable=status();verify(!unavailable.getBoolean("available"))
        for(key in listOf("device","pendingCreation","pendingDeletion")) verify(unavailable.isNull(key))
        write(args("create"),false)
        if(arguments[0]=="uninstalled") {
            verify(!java.nio.file.Files.exists(java.nio.file.Path.of(arguments[1])))
            println("Tauri real ZeroTier service uninstalled: $checks checks passed");return
        }
        Fixture.install(arguments[1]);verify(status().getBoolean("available"))
        val created=write(args("create"),true)
        val record=created.result["device"] as JSONObject
        val handle=record.getString("handle");val instance=record.getString("instanceId")
        verify(record.keySet()==setOf("handle","instanceId"));verify(Fixture.generated==1)
        verify(status().getJSONObject("device").getString("instanceId")==instance)
        write(args("forget",handle,"11111111-1111-4111-8111-111111111111"),false)
        verify(status().getJSONObject("device").getString("instanceId")==instance)
        Fixture.acquire(handle);write(args("forget",handle,instance),false)
        Fixture.drain();verify(write(args("forget",handle,instance),true).result["present"]==false)
        verify(status().isNull("device"))

        Fixture.failCreate=true;write(args("create"),false)
        val pending=status().getJSONObject("pendingCreation")
        val pendingHandle=pending.getString("handle");verify(pending.getString("phase")=="record-present")
        Fixture.failCreate=false
        write(args("recoverPendingCreation",pendingHandle,phase="finishing"),false)
        write(args("discardPendingCreation",pendingHandle,phase="record-present"),false)
        val recovered=write(args("recoverPendingCreation",pendingHandle,phase="record-present"),true)
        val restored=recovered.result["device"] as JSONObject
        verify(restored.getString("handle")==pendingHandle);verify(Fixture.generated==2)
        verify(status().isNull("pendingCreation"))

        Fixture.failDelete=true;write(args("forget",pendingHandle,restored.getString("instanceId")),false)
        val deletion=status().getJSONObject("pendingDeletion");verify(deletion.getString("phase")=="record-present")
        write(args("recoverPendingDeletion",pendingHandle,phase="record-removed"),false)
        Fixture.failDelete=false
        write(args("recoverPendingDeletion",pendingHandle,phase="record-present"),true)
        verify(status().isNull("pendingDeletion"));verify(status().isNull("device"))

        Fixture.lock.locked=true
        val locked=Invoke(null);plugin.zeroTierDeviceStatus(locked);locked.await();verify(locked.error!=null)
        Fixture.lock.locked=false
        Fixture.entered=java.util.concurrent.CountDownLatch(1);Fixture.release=java.util.concurrent.CountDownLatch(1)
        val delayedArgs=args("create");val delayed=Invoke(delayedArgs)
        plugin.zeroTierDeviceWrite(delayed)
        verify(Fixture.entered.await(5,java.util.concurrent.TimeUnit.SECONDS));verify(!fence(delayedArgs.operationId))
        plugin.onPause(activity);Fixture.release.countDown();delayed.await();verify(delayed.error!=null)
        verify(fence(delayedArgs.operationId));Fixture.entered=null;Fixture.release=null
        plugin.onResume(activity)
        verify(status().getJSONObject("device").getString("handle").isNotEmpty());verify(Fixture.generated==3)
        val replay=Invoke(delayedArgs);plugin.zeroTierDeviceWrite(replay);replay.await();verify(replay.error!=null)
        val after=status().getJSONObject("device")
        write(args("forget",after.getString("handle"),after.getString("instanceId")),true)
        println("Tauri real Kotlin -> Java service/store/core: $checks checks passed; exact metadata, recovery, lease, lifecycle, fence; no native node")
    } finally {plugin.onDestroy(activity);Fixture.cleanup()}
}
