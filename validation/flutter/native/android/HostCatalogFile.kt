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
import org.json.JSONArray
import org.json.JSONObject

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
    /** Hold the same CAS/file lock as save for the complete device action.
     * Recompute the complete impact from disk; frontend lists are only a review.
     */
    fun <T> runWithExpectedRevision(expected: String, profileIds: Set<String>, hostIds: Set<String>, action: () -> T): T = locked {
        check(expected.matches(Regex("(?:[a-f0-9]{64})?")))
        val current = bytes()
        check(token(current) == expected) { "catalog conflict" }
        val impact = current?.let { zeroTierImpact(text(it)) } ?: (emptySet<String>() to emptySet<String>())
        check(impact.first == profileIds && impact.second == hostIds) { "catalog impact changed" }
        action()
    }
    private fun zeroTierImpact(source: String): Pair<Set<String>, Set<String>> {
        strictJson(source)
        val root = JSONObject(source)
        val fields = root.keys().asSequence().toSet()
        check(fields.containsAll(setOf("schemaVersion", "profiles", "pendingCreation")) &&
            fields.all { it in setOf("schemaVersion", "profiles", "pendingCreation", "networkProfiles", "preferences") })
        val version = root.get("schemaVersion")
        check(version is Int && version in 1..4)
        val networks = if (version == 4) root.getJSONArray("networkProfiles") else JSONArray().also { check(!root.has("networkProfiles")) }
        val hosts = root.getJSONArray("profiles")
        check(networks.length() <= 32 && hosts.length() <= 32)
        val ids = Regex("[a-f0-9]{32}")
        val allNetworks = mutableSetOf<String>(); val affectedNetworks = mutableSetOf<String>(); val affectedHosts = mutableSetOf<String>(); val allHosts = mutableSetOf<String>()
        for (i in 0 until networks.length()) {
            val item = networks.getJSONObject(i); val id = item.get("id"); val provider = item.get("provider")
            check(id is String && ids.matches(id) && allNetworks.add(id))
            check(provider is String && provider in setOf("tailscale", "easytier", "zerotier"))
            if (provider == "zerotier") affectedNetworks.add(id)
        }
        for (i in 0 until hosts.length()) {
            val item = hosts.getJSONObject(i); val id = item.get("id")
            check(id is String && ids.matches(id) && allHosts.add(id))
            val provider = if (version == 1 && !item.has("provider")) "unspecified" else item.get("provider")
            check(provider is String && provider in setOf("unspecified", "direct", "tailscale", "easytier", "zerotier"))
            val network = item.opt("networkProfileId").let { if (it == JSONObject.NULL) null else it }
            check(network == null || (network is String && ids.matches(network) && network in allNetworks))
            if (provider == "zerotier" || network in affectedNetworks) affectedHosts.add(id)
        }
        return affectedNetworks to affectedHosts
    }
    // Android org.json accepts extensions and duplicate keys. Reject them,
    // including escaped duplicate keys, before computing the reviewed impact.
    private fun strictJson(source: String) {
        var i = 0
        fun ws() { while (i < source.length && source[i] in " \t\r\n") i++ }
        fun string(): String {
            val start = i; check(i < source.length && source[i++] == '"')
            while (i < source.length) {
                val c = source[i++]
                if (c == '"') return JSONObject("{\"key\":" + source.substring(start, i) + "}").getString("key")
                check(c.code >= 32)
                if (c == '\\') {
                    check(i < source.length); val escape = source[i++]
                    if (escape == 'u') {
                        check(i + 4 <= source.length && source.substring(i, i + 4).all { it in '0'..'9' || it in 'a'..'f' || it in 'A'..'F' }); i += 4
                    } else check(escape in "\"\\/bfnrt")
                }
            }
            error("unterminated string")
        }
        lateinit var value: (Int) -> Unit
        value = { depth ->
            check(depth <= 8); ws(); check(i < source.length)
            when (source[i]) {
                '"' -> { string(); Unit }
                '{' -> {
                    i++; ws(); val keys = mutableSetOf<String>()
                    if (i < source.length && source[i] == '}') i++ else while (true) {
                        ws(); check(keys.add(string())); ws(); check(i < source.length && source[i++] == ':'); value(depth + 1); ws()
                        check(i < source.length); val end = source[i++]; if (end == '}') break; check(end == ',')
                    }
                }
                '[' -> {
                    i++; ws()
                    if (i < source.length && source[i] == ']') i++ else while (true) {
                        value(depth + 1); ws(); check(i < source.length); val end = source[i++]; if (end == ']') break; check(end == ',')
                    }
                }
                else -> {
                    val match = Regex("(?:-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|true|false|null)").find(source, i)
                    check(match != null && match.range.first == i); i = match.range.last + 1
                }
            }
        }
        value(0); ws(); check(i == source.length)
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
            val fd = Os.open(directory.path, OsConstants.O_RDONLY or OsConstants.O_NOFOLLOW or OsConstants.O_NONBLOCK, 0)
            try {
                check(OsConstants.S_ISDIR(Os.fstat(fd).st_mode))
                Os.fsync(fd)
            } finally { Os.close(fd) }
            token(replacement)
        } finally { pending.delete() }
    }
}
