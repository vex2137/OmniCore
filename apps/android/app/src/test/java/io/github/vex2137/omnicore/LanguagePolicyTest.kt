package io.github.vex2137.omnicore

import org.junit.Assert.*
import org.junit.Test

class LanguagePolicyTest {
    @Test
    fun polishSystemVariantsSelectPolish() {
        for (tag in listOf("pl", "pl-PL", "pl-US")) assertEquals(
            "pl-PL",
            initialLanguage(listOf(tag)),
        )
    }

    @Test
    fun systemPriorityAndSupportedFallbackAreRespected() {
        assertEquals("en-US", initialLanguage(listOf("en-GB", "pl-PL")))
        assertEquals("pl-PL", initialLanguage(listOf("de-DE", "pl-PL")))
        assertEquals("en-US", initialLanguage(listOf("fr-FR")))
        assertEquals("en-US", initialLanguage(emptyList()))
    }

    @Test
    fun connectionStatesDistinguishAuthenticationAndOrdinaryWork() {
        assertEquals(ConnectionStatus.Disconnected, UiState(busy = true).connectionStatus)
        assertEquals(ConnectionStatus.Connecting, UiState(connecting = true).connectionStatus)
        assertEquals(ConnectionStatus.Connecting, UiState(reconnecting = true).connectionStatus)
        assertEquals(
            ConnectionStatus.Connected,
            UiState(connected = true, busy = true).connectionStatus,
        )
        assertEquals(
            ConnectionStatus.Unauthorized,
            UiState(authorizationFailed = true).connectionStatus,
        )
    }

    @Test
    fun terminalSnapshotCannotRevertToRunningEvenWithHigherSequence() {
        val done = Generation("g", "c", "completed", sequence = 4)
        assertFalse(acceptSnapshot(done, done.copy(state = "running", sequence = 5)))
        assertFalse(acceptSnapshot(done, done.copy(sequence = 3)))
    }
}
