package io.github.vex2137.omnicore

import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import org.junit.Assert.*
import org.junit.Test

class GenerationMetadataTest {
    @Test
    fun oldHistoryAndGenerationHaveSafeDefaults() {
        val message = WireJson.decodeFromString<Message>("""{"role":"assistant","content":"old"}""")
        assertNull(message.modelName)
        assertNull(message.statistics)
        val job =
            WireJson.decodeFromString<Generation>(
                """{"id":"g","conversation_id":"c","state":"completed"}"""
            )
        assertNull(job.modelName)
        assertNull(job.statistics().outputTokens)
        assertFalse(Parameters().thinking)
    }

    @Test
    fun modelSnapshotAndStatisticsRoundTripWithoutLosingThinkingPreference() {
        val raw =
            """{"id":"m","role":"assistant","content":"answer","model_name":"Original model","reasoning_content":"reason","statistics":{"output_tokens":256,"input_tokens":11,"ttft_seconds":0.3,"context_used_tokens":267,"context_limit_tokens":2048,"finish_reason":"length"}}"""
        val message = WireJson.decodeFromString<Message>(raw)
        assertEquals("Original model", message.modelName)
        assertEquals("length", message.statistics?.finishReason)
        assertEquals(256, message.statistics?.outputTokens)
        assertEquals(message, WireJson.decodeFromString<Message>(WireJson.encodeToString(message)))
        val parameters = Parameters(thinking = true, device = "CUDA0", gpuLayers = 20)
        assertTrue(parameters.copy(maxTokens = 512).thinking)
        assertEquals(
            parameters,
            WireJson.decodeFromString<Parameters>(WireJson.encodeToString(parameters)),
        )
    }
}
