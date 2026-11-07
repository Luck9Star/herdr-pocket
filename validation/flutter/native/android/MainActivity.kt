package dev.herdr.herdr_flutter_probe

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import org.herdr.pairing.AndroidDeviceKeyStore
import java.util.concurrent.Executors
import android.content.Intent
import dev.herdr.pocket.NetworkRuntimeChannel

/** Four operations only. All seed/envelope work stays in shared native code. */
class MainActivity : FlutterActivity() {
    private var scanner: PairScanChannel? = null
    private var documents: ConfigDocumentChannel? = null
    private var networkRuntime: NetworkRuntimeChannel? = null
    private var networkIdentity: NetworkIdentityChannel? = null
    private var zeroTierDevice: ZeroTierDeviceChannel? = null
    private val worker = Executors.newSingleThreadExecutor()
    override fun configureFlutterEngine(engine: FlutterEngine) {
        super.configureFlutterEngine(engine)
        scanner = PairScanChannel(this, engine.dartExecutor.binaryMessenger)
        documents = ConfigDocumentChannel(this, engine.dartExecutor.binaryMessenger)
        networkRuntime = NetworkRuntimeChannel(this, engine.dartExecutor.binaryMessenger)
        networkIdentity = NetworkIdentityChannel(this, engine.dartExecutor.binaryMessenger)
        zeroTierDevice = ZeroTierDeviceChannel(this, engine.dartExecutor.binaryMessenger)
        MethodChannel(engine.dartExecutor.binaryMessenger, "herdr.pocket/input_journal")
            .setMethodCallHandler { call, result ->
                if (call.method !in listOf("read", "readAll", "prepare", "complete", "abandon", "resolve", "clear")) result.notImplemented()
                else worker.execute {
                    try {
                        val store = InputJournalFile(applicationContext)
                        val value: Any? = when (call.method) {
                            "read" -> store.read()
                            "readAll" -> store.readAll()
                            "prepare" -> store.prepare(call.argument<String>("record") ?: error("record"))
                            "complete" -> { store.complete(call.argument<String>("record") ?: error("record"), call.argument<String>("lease") ?: error("lease")); null }
                            "abandon" -> { store.abandon(call.argument<String>("record") ?: error("record"), call.argument<String>("lease") ?: error("lease")); null }
                            "resolve" -> { store.resolve(call.argument<String>("record") ?: error("record")); null }
                            "clear" -> { store.clear(call.argument<String>("record") ?: error("record")); null }
                            else -> error("operation")
                        }
                        runOnUiThread { result.success(value) }
                    } catch (_: Exception) {
                        runOnUiThread { result.error("input_journal_unavailable", "Public input marker unavailable or changed", null) }
                    }
                }
            }
        MethodChannel(engine.dartExecutor.binaryMessenger, "dev.herdr/host-catalog")
            .setMethodCallHandler { call, result ->
                if (call.method !in listOf("load", "save")) result.notImplemented()
                else worker.execute {
                    try {
                        val store = HostCatalogFile(applicationContext)
                        val value: Any = when (call.method) {
                            "load" -> store.load()
                            "save" -> store.save(call.argument<String>("expected") ?: error("expected"),
                                call.argument<String>("contents") ?: error("contents"))
                            else -> error("operation")
                        }
                        runOnUiThread { result.success(value) }
                    } catch (_: Exception) {
                        runOnUiThread { result.error("catalog_unavailable", "Local host catalog unavailable or changed", null) }
                    }
                }
            }
        MethodChannel(engine.dartExecutor.binaryMessenger, "dev.herdr/device-keys")
            .setMethodCallHandler { call, result ->
                if (call.method !in listOf("create", "public", "sign", "delete")) {
                    result.notImplemented()
                } else {
                    worker.execute {
                        try {
                            val store = AndroidDeviceKeyStore(applicationContext)
                            val value: Any? = when (call.method) {
                                "create" -> store.create().handle
                                "public" -> store.publicKey(call.argument<String>("handle") ?: error("handle"))
                                "sign" -> store.sign(call.argument<String>("handle") ?: error("handle"),
                                    call.argument<ByteArray>("payload") ?: error("payload"))
                                "delete" -> { store.delete(call.argument<String>("handle") ?: error("handle")); null }
                                else -> error("operation")
                            }
                            runOnUiThread { result.success(value) }
                        } catch (_: Exception) {
                            runOnUiThread { result.error("device_key_unavailable", "Protected device key unavailable", null) }
                        }
                    }
                }
            }
    }
    override fun onResume() { super.onResume(); networkRuntime?.setForeground(true); zeroTierDevice?.setForeground(true) }
    override fun onPause() { zeroTierDevice?.setForeground(false); networkRuntime?.setForeground(false); super.onPause() }
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (scanner?.handle(requestCode, resultCode, data) != true &&
            documents?.handle(requestCode, resultCode, data) != true) super.onActivityResult(requestCode, resultCode, data)
    }
    override fun onDestroy() { zeroTierDevice?.close(); scanner?.close(); documents?.close(); networkIdentity?.close(); networkRuntime?.close(); worker.shutdown(); super.onDestroy() }
}
