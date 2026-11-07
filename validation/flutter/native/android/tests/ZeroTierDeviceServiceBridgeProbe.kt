package dev.herdr.herdr_flutter_probe

import android.app.Activity
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import org.herdr.network.ZeroTierServiceBridgeFixture as Fixture
import java.nio.file.Files
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Real Flutter Kotlin channel + Java service/store/core; Android and keys are synthetic. */
fun main(args: Array<String>) {
    var checks=0
    fun verify(value: Boolean) { check(value) { "bridge check $checks" }; checks++ }
    val root=Files.createTempDirectory("zt-bridge-").toFile()
    val activity=Activity(root); val disk=HostCatalogFile(activity)
    val network="a".repeat(32); val host="b".repeat(32)
    val catalog="""{"schemaVersion":4,"profiles":[{"id":"$host","provider":"zerotier","networkProfileId":"$network"}],"pendingCreation":null,"networkProfiles":[{"id":"$network","provider":"zerotier"}]}"""
    val revision=disk.save("",catalog)
    val review=mapOf("catalogRevision" to revision,"profileIds" to listOf(network),"hostIds" to listOf(host))
    class Reply: MethodChannel.Result {
        val done=CountDownLatch(1); var value:Any?=null; var code:String?=null
        override fun success(value:Any?) { this.value=value; done.countDown() }
        override fun error(code:String,message:String?,details:Any?) { this.code=code; done.countDown() }
        override fun notImplemented() { code="notImplemented"; done.countDown() }
        fun waitReply():Reply { verify(done.await(5,TimeUnit.SECONDS));return this }
    }
    fun fire(method:String,value:Any?=null):Reply { val reply=Reply();MethodChannel.fire("dev.herdr/zerotier-device",MethodCall(method,value),reply);return reply.waitReply() }
    val channel=ZeroTierDeviceChannel(activity,object:BinaryMessenger {})
    try {
        channel.setForeground(true)
        val unavailable=fire("status").value as Map<*,*>
        verify(unavailable["available"]==false && unavailable["device"]==null)
        verify(fire("create",review).code=="zerotier_device_write_unknown")
        verify(!root.resolve("herdr-zerotier-device-v1").exists())
        Fixture.install(root,args.single()=="pending")
        verify((fire("status").value as Map<*,*>)["available"]==true)
        if(args.single()=="pending") {
            verify(fire("create",review).code=="zerotier_device_write_unknown")
            val pending=(fire("status").value as Map<*,*>)["pendingCreation"] as Map<*,*>
            val handle=pending["handle"] as String;verify(pending["phase"]=="record-present")
            verify(fire("recoverPendingCreation",review+mapOf("handle" to handle,"expectedPhase" to "finishing")).code=="zerotier_device_write_unknown")
            val recovered=fire("recoverPendingCreation",review+mapOf("handle" to handle,"expectedPhase" to "record-present")).value as Map<*,*>
            verify(recovered["handle"]==handle && Fixture.generations==1)
            verify((fire("status").value as Map<*,*>)["pendingCreation"]==null)
        } else if (args.single()=="pending-deletion") {
            val device=fire("create",review).value as Map<*,*>;val handle=device["handle"] as String;val instance=device["instanceId"] as String
            Fixture.failNextRemoval()
            verify(fire("forget",review+mapOf("handle" to handle,"instanceId" to instance)).code=="zerotier_device_write_unknown")
            val pending=(fire("status").value as Map<*,*>)["pendingDeletion"] as Map<*,*>
            verify(pending["handle"]==handle && pending["phase"]=="record-present")
            verify(fire("recoverPendingDeletion",review+mapOf("handle" to handle,"expectedPhase" to "record-removed")).code=="zerotier_device_write_unknown")
            verify(fire("recoverPendingDeletion",review+mapOf("handle" to handle,"expectedPhase" to "record-present")).code==null)
            val after=fire("status").value as Map<*,*>;verify(after["device"]==null && after["pendingDeletion"]==null && Fixture.generations==1)
        } else {
            val device=fire("create",review).value as Map<*,*>;val handle=device["handle"] as String;val instance=device["instanceId"] as String
            verify(Fixture.generations==1);verify((fire("status").value as Map<*,*>)["device"]==device)
            Fixture.acquire(handle)
            verify(fire("forget",review+mapOf("handle" to handle,"instanceId" to instance)).code=="zerotier_device_write_unknown")
            verify((fire("status").value as Map<*,*>)["device"]==device)
            Fixture.release()
            verify(fire("forget",review+mapOf("handle" to handle,"instanceId" to "11111111-1111-4111-8111-111111111111")).code=="zerotier_device_write_unknown")
            verify((fire("status").value as Map<*,*>)["device"]==device)
            verify(fire("forget",review+mapOf("handle" to handle,"instanceId" to instance)).code==null)
            val after=fire("status").value as Map<*,*>;verify(after["device"]==null && after["pendingDeletion"]==null)
        }
    } finally { channel.close();root.deleteRecursively();verify(!root.exists()) }
    println("real Kotlin channel + Java service/store/core (${args.single()}): $checks checks passed; synthetic Android/key provider/identity")
}
