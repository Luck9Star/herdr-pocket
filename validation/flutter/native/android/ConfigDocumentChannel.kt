package dev.herdr.herdr_flutter_probe

import android.app.Activity
import android.content.Intent
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodChannel
import org.herdr.pocket.transfer.ArchiveDocument
import java.util.concurrent.Executors

class ConfigDocumentChannel(
    private val activity: Activity,
    messenger: BinaryMessenger,
) {
    private val worker = Executors.newSingleThreadExecutor()
    private val channel = MethodChannel(messenger, "herdr.pocket/config_document")
    private var pending: MethodChannel.Result? = null
    private var archive: ByteArray? = null

    init {
        channel.setMethodCallHandler { call, answer ->
            if (call.method != "open" && call.method != "save") {
                answer.notImplemented()
            } else if (pending != null) {
                answer.error("document_busy", null, null)
            } else {
                try {
                    val data = if (call.method == "save") {
                        val bytes = call.arguments as? ByteArray ?: error("invalid_archive")
                        ArchiveDocument.checkForSave(bytes)
                        bytes
                    } else null
                    pending = answer
                    archive = data
                    activity.startActivityForResult(ArchiveDocument.choose(data != null), REQUEST)
                } catch (_: Exception) {
                    pending = null
                    archive = null
                    answer.error("document_unavailable", null, null)
                }
            }
        }
    }

    fun handle(code: Int, result: Int, data: Intent?): Boolean {
        if (code != REQUEST) return false
        val answer = pending ?: return true
        val bytes = archive
        try {
            val uri = ArchiveDocument.selectedUri(result, data)
            if (uri == null) {
                pending = null
                archive = null
                answer.success(if (bytes == null) null else false)
            } else {
                worker.execute {
                    try {
                        val value = if (bytes == null) ArchiveDocument.read(activity.contentResolver, uri)
                        else { ArchiveDocument.write(activity.contentResolver, uri, bytes); true }
                        activity.runOnUiThread { complete(answer) { answer.success(value) } }
                    } catch (_: Exception) {
                        activity.runOnUiThread { complete(answer) { answer.error("document_io_failed", null, null) } }
                    }
                }
            }
        } catch (_: Exception) {
            complete(answer) { answer.error("document_io_failed", null, null) }
        }
        return true
    }

    private fun complete(answer: MethodChannel.Result, reply: () -> Unit) {
        if (pending !== answer) return
        pending = null
        archive = null
        reply()
    }

    fun close() {
        channel.setMethodCallHandler(null)
        worker.shutdownNow()
        pending?.error("document_closed", null, null)
        pending = null
        archive = null
    }

    companion object { private const val REQUEST = 0x4852 }
}
