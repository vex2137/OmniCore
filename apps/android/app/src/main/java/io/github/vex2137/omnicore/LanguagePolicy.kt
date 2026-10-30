package io.github.vex2137.omnicore

import java.util.Locale

/** System languages are consulted once. A saved manual choice always takes precedence. */
fun initialLanguage(tags: List<String>): String =
    tags.firstNotNullOfOrNull {
        when (Locale.forLanguageTag(it).language) {
            "pl" -> "pl-PL"
            "en" -> "en-US"
            else -> null
        }
    } ?: "en-US"

enum class ConnectionStatus {
    Connected,
    Connecting,
    Disconnected,
    Unavailable,
    Unauthorized,
}
