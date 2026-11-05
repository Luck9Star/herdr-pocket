package dev.herdr.herdr_flutter_probe

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import org.herdr.pairing.AndroidDeviceKeyStore
import java.util.concurrent.Executors

/** Four operations only. All seed/envelope work stays in shared native code. */
class MainActivity : FlutterActivity() {
    private val worker = Executors.newSingleThreadExecutor()
    override fun configureFlutterEngine(engine: FlutterEngine) {
        super.configureFlutterEngine(engine)
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
    override fun onDestroy() { worker.shutdown(); super.onDestroy() }
}
