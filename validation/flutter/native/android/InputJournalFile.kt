package dev.herdr.herdr_flutter_probe

import android.content.Context
import org.json.JSONObject
import org.json.JSONArray
import java.io.File
import java.nio.charset.CodingErrorAction
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.StandardOpenOption
import java.nio.channels.FileChannel
import java.nio.channels.FileLock
import java.security.SecureRandom

/** Journal ownership lasts for the process, including Activity recreation. */
class InputJournalFile(context: Context) {
    private val storage = HostCatalogFile(context, "herdr-input-journal-v1")
    private val directory = File(context.noBackupFilesDir, "herdr-input-journal-v1").absoluteFile.normalize()
    private data class Endpoint(val route: String, val host: String, val port: Int, val username: String,
        val fingerprint: String, val session: String, val socket: String, val pane: String, val terminal: String)
    private data class Active(val raw: String, val lease: String)
    private class Owner(val channel: FileChannel, val lock: FileLock) {
        val active = mutableMapOf<Endpoint, Active>()
        var knownStore = false
    }
    companion object {
        private val owners = mutableMapOf<String, Owner>()
        private val random = SecureRandom()
        // Hold the OS lock for the entire process lifetime. A second process
        // cannot mistake another process's in-memory active lease for absence.
        @Synchronized private fun owner(directory: File): Owner {
            check(!Files.isSymbolicLink(directory.toPath()))
            check(directory.isDirectory || directory.mkdirs())
            val key = directory.canonicalPath
            owners[key]?.let { return it }
            val path = File(directory, "owner.lock").toPath()
            val channel = FileChannel.open(path, StandardOpenOption.CREATE, StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS)
            try {
                check(Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS))
                val lock = channel.tryLock() ?: error("journal owned")
                return Owner(channel, lock).also { owners[key] = it }
            } catch (error: Throwable) { channel.close(); throw error }
        }
        private fun lease(): String = ByteArray(16).also(random::nextBytes).joinToString("") { "%02x".format(it) }
    }
    // org.json accepts several non-JSON extensions. Reject those before using
    // it for decoding. Bounds are enforced before this recursive parser runs.
    private fun strictJson(source: String) {
        var i = 0
        fun ws() { while (i < source.length && source[i] in " \t\r\n") i++ }
        fun string() {
            check(i < source.length && source[i++] == '"')
            while (i < source.length) {
                val c = source[i++]
                if (c == '"') return
                check(c.code >= 32)
                if (c == '\\') {
                    check(i < source.length)
                    val e = source[i++]
                    if (e == 'u') {
                        check(i + 4 <= source.length && source.substring(i, i + 4).all { it in '0'..'9' || it in 'a'..'f' || it in 'A'..'F' }); i += 4
                    } else check(e in "\"\\/bfnrt")
                }
            }
            error("unterminated string")
        }
        lateinit var value: (Int) -> Unit
        value = { depth ->
            check(depth <= 4); ws(); check(i < source.length)
            when (source[i]) {
                '"' -> string()
                '{' -> { i++; ws(); if (i < source.length && source[i] == '}') i++ else {
                    while (true) { ws(); string(); ws(); check(i < source.length && source[i++] == ':'); value(depth+1); ws()
                        check(i < source.length); val c = source[i++]; if (c == '}') break; check(c == ',') }
                } }
                '[' -> { i++; ws(); if (i < source.length && source[i] == ']') i++ else {
                    while (true) { value(depth+1); ws(); check(i < source.length); val c = source[i++]; if (c == ']') break; check(c == ',') }
                } }
                else -> {
                    val match = Regex("(?:-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|true|false|null)").find(source, i)
                    check(match != null && match.range.first == i); i = match.range.last + 1
                }
            }
        }
        value(0); ws(); check(i == source.length)
    }
    private val fields = setOf("schemaVersion", "requestId", "host", "port", "username", "hostFingerprint",
        "session", "socketPath", "paneId", "terminalId", "generation", "createdAt")
    private fun validate(record: String): Endpoint {
        check(record.length in 1..8192)
        Charsets.UTF_8.newEncoder().onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT).encode(java.nio.CharBuffer.wrap(record))
        strictJson(record)
        check(record.toByteArray(Charsets.UTF_8).size in 1..8192 && record.trim().startsWith("{") && record.trim().endsWith("}"))
        var quoted = false; var escaped = false; var colons = 0; var braces = 0
        for (c in record) {
            if (quoted) {
                if (escaped) escaped = false else if (c == '\\') escaped = true else if (c == '"') quoted = false
            } else when (c) {
                '"' -> quoted = true
                ':' -> colons++
                '{', '}' -> braces++
                '[', ']' -> error("nested journal")
            }
        }
        check(!quoted && braces == 2)
        val obj = JSONObject(record)
        val version = obj.opt("schemaVersion")
        val expected = if (version == 1) fields else if (version == 2) fields + "route" else error("invalid version")
        check(colons == expected.size && obj.keys().asSequence().toSet() == expected)
        fun integer(name: String, min: Long, max: Long): Long {
            val raw = obj.get(name)
            check(raw is Int || raw is Long)
            val n = (raw as Number).toLong(); check(n in min..max); return n
        }
        fun text(name: String, max: Int): String {
            val value = obj.get(name); check(value is String && value.isNotEmpty() && value.length <= max)
            check(value.none { it.code < 32 || it.code == 127 }); return value
        }
        integer("schemaVersion",1,2); integer("port",1,65535); integer("generation",1,2147483647)
        if (version == 2 && !obj.isNull("route")) {
            val route = text("route",256)
            val match = Regex("(?:easy-tier|tailscale):([a-f0-9]{32}):([1-9][0-9]{0,9}):([a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12})").matchEntire(route)
            check(match != null && match.groupValues[2].toLong() <= 2147483647L)
        }
        check(text("requestId",32).matches(Regex("[a-f0-9]{32}")))
        check(text("host",253).matches(Regex("[A-Za-z0-9:.\\[\\]_-]+")))
        val user = text("username",128); check(!user.startsWith("-") && user.none { it.isWhitespace() })
        check(text("hostFingerprint",100).matches(Regex("SHA256:[A-Za-z0-9+/]{43}")))
        val session = text("session",64); check(session != "default" && session.matches(Regex("[A-Za-z0-9_-]+")))
        val socket = text("socketPath",1024); check(socket.startsWith("/") && socket.split('/').drop(1).none { it.isEmpty() || it == "." || it == ".." })
        check(text("paneId",128).matches(Regex("[A-Za-z0-9:_-]+")))
        check(text("terminalId",128).matches(Regex("term_[0-9a-f]{1,123}")))
        check(text("createdAt",40).matches(Regex("[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+Z")))
        return Endpoint(if (version == 1 || obj.isNull("route")) "system" else obj.getString("route"),
            obj.getString("host"), obj.getInt("port"), obj.getString("username"), obj.getString("hostFingerprint"),
            obj.getString("session"), obj.getString("socketPath"), obj.getString("paneId"), obj.getString("terminalId"))
    }
    private data class Loaded(val revision: String, val records: List<String>, val legacy: Boolean)
    private fun load(): Loaded {
        val saved = storage.load(); val text = saved.getValue("contents")
        val state = owner(directory)
        if (saved.getValue("revision").isEmpty()) check(!state.knownStore) { "journal disappeared" }
        else state.knownStore = true
        if (text.isEmpty() || text == "{}") return Loaded(saved.getValue("revision"), emptyList(), true)
        strictJson(text)
        val obj = JSONObject(text)
        if (obj.opt("schemaVersion") != 3) {
            validate(text)
            return Loaded(saved.getValue("revision"), listOf(text), true)
        }
        var quoted = false; var escaped = false; var colons = 0; var braces = 0; var brackets = 0
        for (c in text) {
            if (quoted) { if (escaped) escaped = false else if (c == '\\') escaped = true else if (c == '"') quoted = false }
            else when (c) { '"' -> quoted = true; ':' -> colons++; '{', '}' -> braces++; '[', ']' -> brackets++ }
        }
        check(!quoted && colons == 2 && braces == 2 && brackets == 2 && obj.keys().asSequence().toSet() == setOf("schemaVersion", "records"))
        check(obj.get("schemaVersion") is Int && obj.getInt("schemaVersion") == 3)
        val values = obj.getJSONArray("records"); check(values.length() <= 32)
        val records = (0 until values.length()).map { check(values.get(it) is String); values.getString(it) }
        val endpoints = records.map(::validate)
        check(records.toSet().size == records.size && endpoints.toSet().size == endpoints.size)
        return Loaded(saved.getValue("revision"), records, false)
    }
    private fun save(old: Loaded, records: List<String>) {
        check(records.size <= 32)
        val text = JSONObject().put("schemaVersion", 3).put("records", JSONArray(records)).toString()
        check(text.toByteArray(Charsets.UTF_8).size <= 262144)
        // A failed save may have reached the atomic replacement before fsync
        // failed. Never later interpret disappearance as a proven fresh store.
        owner(directory).knownStore = true
        storage.save(old.revision, text)
    }
    fun readAll(): List<String> = synchronized(owner(directory)) { load().records.toList() }
    fun prepare(record: String): String = synchronized(owner(directory)) {
        val key = validate(record); val state = owner(directory); val old = load()
        check(key !in state.active && old.records.none { validate(it) == key } && old.records.size < 32)
        val lease = lease()
        save(old, old.records + record) // Persist first. Failure never grants a lease.
        state.active[key] = Active(record, lease)
        lease
    }
    fun complete(record: String, lease: String) = synchronized(owner(directory)) {
        val key = validate(record); val state = owner(directory)
        check(lease.matches(Regex("[a-f0-9]{32}")) && state.active[key] == Active(record, lease))
        val old = load(); check(old.records.count { it == record } == 1)
        save(old, old.records.filterNot { it == record }); state.active.remove(key); Unit
    }
    fun abandon(record: String, lease: String) = synchronized(owner(directory)) {
        val key = validate(record); val state = owner(directory)
        check(lease.matches(Regex("[a-f0-9]{32}")) && state.active[key] == Active(record, lease))
        state.active.remove(key); Unit
    }
    fun resolve(record: String) = synchronized(owner(directory)) {
        val key = validate(record); val state = owner(directory); val old = load()
        check(key !in state.active && old.records.count { it == record } == 1)
        save(old, old.records.filterNot { it == record }); Unit
    }
    // Old clients can inspect/clear a legacy single marker only. They cannot
    // decode a v3 table or clear a target owned by an active send.
    fun read(): String? = synchronized(owner(directory)) { val old = load(); check(old.legacy); old.records.singleOrNull() }
    fun clear(record: String) = synchronized(owner(directory)) {
        val key = validate(record); val state = owner(directory); val old = load()
        check(old.legacy && key !in state.active && old.records.singleOrNull() == record)
        storage.save(old.revision, "{}"); Unit
    }
}
