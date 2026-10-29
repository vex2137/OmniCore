package io.github.vex2137.omnicore

import java.net.URI

/** Pure validation; never resolves arbitrary DNS on the UI thread. */
object ConnectionPolicy {
    fun validatedUrl(raw: String, trustedLan: Boolean): String {
        val uri =
            try {
                URI(raw.trim())
            } catch (_: Exception) {
                throw ApiFailure("invalid_url")
            }
        if (
            uri.scheme !in setOf("https", "http") ||
                uri.host.isNullOrBlank() ||
                uri.userInfo != null ||
                uri.rawQuery != null ||
                uri.rawFragment != null ||
                uri.port !in -1..65535 ||
                uri.port == 0
        )
            throw ApiFailure("invalid_url")
        if (uri.scheme == "http" && (!trustedLan || !privateHost(uri.host)))
            throw ApiFailure("https_required")
        return uri.toASCIIString().trimEnd('/')
    }

    fun sameOrigin(first: String, second: String): Boolean {
        fun origin(value: String): Triple<String?, String?, Int> {
            val uri = URI(value)
            return Triple(
                uri.scheme?.lowercase(),
                uri.host?.lowercase(),
                if (uri.port != -1) uri.port else if (uri.scheme == "https") 443 else 80,
            )
        }
        return origin(first) == origin(second)
    }

    private fun privateHost(raw: String): Boolean {
        val host = raw.removePrefix("[").removeSuffix("]").lowercase()
        if (host == "localhost" || host == "::1") return true
        val octets = host.split('.').map { it.toIntOrNull() ?: return false }
        if (octets.size != 4 || octets.any { it !in 0..255 }) return false
        return octets[0] == 10 ||
            octets[0] == 127 ||
            (octets[0] == 192 && octets[1] == 168) ||
            (octets[0] == 172 && octets[1] in 16..31)
    }
}

class ApiFailure(val code: String) : Exception(code)
