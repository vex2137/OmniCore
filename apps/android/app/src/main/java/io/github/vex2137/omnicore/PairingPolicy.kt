package io.github.vex2137.omnicore

import java.net.URI

object PairingPolicy {
    fun parse(raw: String, now: Double = System.currentTimeMillis() / 1000.0): PairingQr {
        if (raw.length > 2048) throw ApiFailure("pairing_invalid")
        val qr = try { WireJson.decodeFromString<PairingQr>(raw) }
                 catch (_: Exception) { throw ApiFailure("pairing_invalid") }
        if (qr.omnicore != 1 || !qr.expiresAt.isFinite() || qr.expiresAt <= now ||
            qr.expiresAt > now + 180 || !qr.code.matches(Regex("[a-f0-9]{64}")))
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
