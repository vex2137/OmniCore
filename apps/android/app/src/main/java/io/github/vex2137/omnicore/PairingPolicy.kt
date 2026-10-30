package io.github.vex2137.omnicore

import java.net.URI

object PairingPolicy {
    fun credential(code: String, nonce: String): String {
        val key = nonce.chunked(2).map { it.toInt(16).toByte() }.toByteArray()
        val mac = javax.crypto.Mac.getInstance("HmacSHA256")
        mac.init(javax.crypto.spec.SecretKeySpec(key, "HmacSHA256"))
        return mac.doFinal(code.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it.toInt() and 255) }
    }

    fun parse(raw: String, @Suppress("UNUSED_PARAMETER") now: Double = System.currentTimeMillis() / 1000.0): PairingQr {
        if (raw.length > 2048) throw ApiFailure("pairing_invalid")
        val qr = try { WireJson.decodeFromString<PairingQr>(raw) }
                 catch (_: Exception) { throw ApiFailure("pairing_invalid") }
        if (qr.omnicore != 1 || !qr.expiresAt.isFinite() || qr.expiresAt <= 0 || !qr.code.matches(Regex("[a-f0-9]{64}")))
            throw ApiFailure("pairing_invalid")
        val url = ConnectionPolicy.validatedUrl(qr.url, true)
        val uri = URI(url)
        // Pair only to explicit private IPv4 addresses, never an arbitrary QR destination.
        if (!ConnectionPolicy.privateHost(uri.host) || uri.host == "localhost" ||
            uri.host.startsWith("127.") || uri.host.contains(':') || uri.path !in listOf("", "/"))
            throw ApiFailure("pairing_invalid")
        return qr.copy(url = url)
    }
}
