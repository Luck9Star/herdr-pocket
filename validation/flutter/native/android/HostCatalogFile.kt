package dev.herdr.herdr_flutter_probe

import android.content.Context
import android.system.Os
import android.system.OsConstants
import java.io.File
import java.io.FileOutputStream
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import java.nio.charset.StandardCharsets
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest

/** Public host metadata only, fixed app-private/no-backup location; compare-and-swap. */
class HostCatalogFile(context: Context, directoryName: String = "herdr-hosts-v1") {
    init { check(directoryName in setOf("herdr-hosts-v1", "herdr-input-journal-v1")) }
    private val directory = File(context.noBackupFilesDir, directoryName)
    private fun bytes(): ByteArray? {
        val file = File(directory, "catalog.json")
        check(!Files.isSymbolicLink(file.toPath()))
        if (!file.exists()) return null
        check(file.isFile && file.length() in 1..262144)
        return file.readBytes().also { check(it.size in 1..262144) }
    }
    private fun text(bytes: ByteArray): String = StandardCharsets.UTF_8.newDecoder()
        .onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT)
        .decode(ByteBuffer.wrap(bytes)).toString()
    private fun token(bytes: ByteArray?): String = bytes?.let {
        MessageDigest.getInstance("SHA-256").digest(it).joinToString("") { byte -> "%02x".format(byte) }
    } ?: ""
    private fun <T> locked(block: () -> T): T = synchronized(HostCatalogFile::class.java) {
        check(!Files.isSymbolicLink(directory.toPath()))
        check(directory.isDirectory || directory.mkdirs())
        val lock = File(directory, "catalog.lock")
        check(!Files.isSymbolicLink(lock.toPath()))
        FileOutputStream(lock, true).channel.use { channel -> channel.lock().use { block() } }
    }
    fun load(): Map<String, String> = locked {
        val current = bytes()
        mapOf("revision" to token(current), "contents" to (current?.let { text(it) } ?: ""))
    }
    fun save(expected: String, contents: String): String = locked {
        check(expected.matches(Regex("(?:[a-f0-9]{64})?")))
        val replacement = contents.toByteArray(StandardCharsets.UTF_8)
        check(replacement.size in 1..262144 && text(replacement) == contents)
        check(token(bytes()) == expected) { "catalog conflict" }
        val pending = File.createTempFile("catalog-", ".new", directory)
        try {
            FileOutputStream(pending).use { stream -> stream.write(replacement); stream.fd.sync() }
            Files.move(pending.toPath(), File(directory, "catalog.json").toPath(),
                StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING)
            val fd = Os.open(directory.path, OsConstants.O_RDONLY or OsConstants.O_DIRECTORY, 0)
            try { Os.fsync(fd) } finally { Os.close(fd) }
            token(replacement)
        } finally { pending.delete() }
    }
}
