package org.herdr.pocket

/** No identity data or logs. Validate again at the explicit native open boundary. */
object NetworkAuthReview {
    fun validUrl(value:String):Boolean {
        if(value.isEmpty() || value.length>4096 || value.any {it.code<=32 || it.code>=127 || it=='\\'}) return false
        return try {
            val uri=java.net.URI(value)
            uri.scheme=="https" && !uri.host.isNullOrEmpty() && uri.rawUserInfo==null && uri.rawFragment==null
        } catch (_:Exception) {false}
    }
}
