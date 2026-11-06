package org.herdr.pocket

import android.app.Activity
import android.util.Base64
import androidx.activity.result.ActivityResult
import app.tauri.annotation.ActivityCallback
import app.tauri.annotation.Command
import app.tauri.annotation.InvokeArg
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.JSObject
import app.tauri.plugin.Plugin
import org.herdr.pocket.transfer.ArchiveDocument
import java.util.concurrent.atomic.AtomicBoolean

@InvokeArg
class SaveArchiveArgs { var archive: String = "" }

@TauriPlugin
class ConfigDocumentPlugin(private val activity: Activity) : Plugin(activity) {
    private val busy = AtomicBoolean(false)

    @Command fun open(invoke: Invoke) = choose(invoke, false)
    @Command fun save(invoke: Invoke) = choose(invoke, true)

    private fun choose(invoke: Invoke, save: Boolean) {
        if (!busy.compareAndSet(false, true)) { invoke.reject("document_busy"); return }
        try {
            if (save) archive(invoke)
            startActivityForResult(invoke, ArchiveDocument.choose(save), if (save) "saved" else "opened")
        } catch (_: Exception) {
            busy.set(false)
            invoke.reject("document_unavailable")
        }
    }

    private fun archive(invoke: Invoke): ByteArray {
        val encoded = invoke.parseArgs(SaveArchiveArgs::class.java).archive
        require(encoded.length <= ((ArchiveDocument.MAX_BYTES + 2) / 3) * 4)
        return Base64.decode(encoded, Base64.NO_WRAP).also { ArchiveDocument.checkForSave(it) }
    }

    @ActivityCallback fun saved(invoke: Invoke, result: ActivityResult) = complete(invoke, result, true)
    @ActivityCallback fun opened(invoke: Invoke, result: ActivityResult) = complete(invoke, result, false)

    private fun complete(invoke: Invoke, result: ActivityResult, save: Boolean) {
        Thread {
            try {
                val uri = ArchiveDocument.selectedUri(result.resultCode, result.data)
                val reply = JSObject()
                reply.put("cancelled", uri == null)
                if (uri != null && save) ArchiveDocument.write(activity.contentResolver, uri, archive(invoke))
                if (uri != null && !save) reply.put("archive",
                    Base64.encodeToString(ArchiveDocument.read(activity.contentResolver, uri), Base64.NO_WRAP))
                invoke.resolve(reply)
            } catch (_: Exception) {
                invoke.reject("document_io_failed")
            } finally {
                busy.set(false)
            }
        }.start()
    }
}
