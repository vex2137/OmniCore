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

    @Test
    fun compactAndExpandedGenerationStatisticsFormatAllMetricsIncludingCancellation() {
        val full =
            GenerationStatistics(
                gpuOffloadedLayers = 25,
                executionDevice = "Mali-G720 MC7",
                inputTokens = 14,
                outputTokens = 61,
                ttftSeconds = 7.16,
                firstAnswerSeconds = 7.16,
                generationSeconds = 11.63,
                modelLoadSeconds = 5.35,
                contextUsedTokens = 75,
                contextLimitTokens = 2048,
                finishReason = "stop",
                tokensPerSecond = 13.43,
            )
        val compact = formatCompactMetrics(full, "Cancelled")
        assertEquals(2, compact.size)
        assertTrue(compact[0].contains("13") && compact[0].contains("tok/s"))
        assertTrue(compact[1].contains("11") && compact[1].contains("s"))

        val labels =
            StatLabels(
                speed = "Speed",
                inputTokens = "Input tokens",
                outputTokens = "Output tokens",
                ttft = "TTFT",
                firstAnswer = "First answer",
                generationTime = "Elapsed",
                modelLoadTime = "Model load",
                context = "Context",
                finishReason = "Finish",
                completed = "Completed",
                finishLength = "token limit",
                cancelled = "Cancelled",
                failed = "Failed",
                offloadedLayers = "Layers on GPU",
                device = "Device",
                cpuFallback = "CPU fallback",
            )
        val entries = buildStatEntries(full, labels)
        val byLabel = entries.associate { it.label to it.value }
        assertTrue(byLabel["Speed"]!!.contains("tok/s"))
        assertEquals("14", byLabel["Input tokens"])
        assertEquals("61", byLabel["Output tokens"])
        assertTrue(byLabel["Context"]!!.startsWith("75/2048"))
        assertEquals("Completed", byLabel["Finish"])
        assertEquals("25", byLabel["Layers on GPU"])
        assertEquals("Mali-G720 MC7", byLabel["Device"])

        val cancelled =
            full.copy(finishReason = "cancelled", tokensPerSecond = 8.42, generationSeconds = 3.21)
        val compactCancelled = formatCompactMetrics(cancelled, "Cancelled")
        assertEquals("Cancelled", compactCancelled[0])
        assertTrue(compactCancelled.any { it.contains("tok/s") })
        assertTrue(compactCancelled.any { it.contains("s") })

        val ttftOnly = GenerationStatistics(ttftSeconds = 0.85, outputTokens = 12)
        val compactFallback = formatCompactMetrics(ttftOnly, "Cancelled")
        assertTrue(compactFallback.single().startsWith("TTFT "))
    }
}
