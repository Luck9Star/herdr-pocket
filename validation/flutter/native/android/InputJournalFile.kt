package dev.herdr.herdr_flutter_probe

import android.content.Context
import org.json.JSONObject

/** Conservative single public marker, independent of host catalog and key files. */
class InputJournalFile(context: Context) {
    private val storage = HostCatalogFile(context, "herdr-input-journal-v1")
    private val fields = setOf("schemaVersion", "requestId", "host", "port", "username", "hostFingerprint",
        "session", "socketPath", "paneId", "terminalId", "generation", "createdAt")
    private fun validate(record: String) {
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
            val match = Regex("easy-tier:([a-f0-9]{32}):([1-9][0-9]{0,9}):([a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12})").matchEntire(route)
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
    }
    fun read(): String? {
        val text = storage.load().getValue("contents")
        if (text.isEmpty() || text == "{}") return null
        validate(text); return text
    }
    fun prepare(record: String) {
        validate(record)
        val old = storage.load(); check(old.getValue("contents") in listOf("", "{}"))
        storage.save(old.getValue("revision"), record)
    }
    fun clear(record: String) {
        validate(record)
        val old = storage.load(); check(old.getValue("contents") == record)
        storage.save(old.getValue("revision"), "{}")
    }
}
