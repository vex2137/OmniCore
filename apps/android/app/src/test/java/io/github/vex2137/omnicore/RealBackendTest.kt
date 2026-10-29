package io.github.vex2137.omnicore

import java.util.UUID
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.*
import org.junit.Test

/** Explicit integration suite, excluded from normal JVM runs. No fixture/model download. */
class RealBackendTest {
    @Test
    fun actualGgufImportLoadStreamDetachCancelHistoryAndUnload() = runBlocking {
        val base = requireNotNull(System.getenv("OMNICORE_ANDROID_REAL_URL"))
        val token = requireNotNull(System.getenv("OMNICORE_ANDROID_REAL_TOKEN"))
        val path = requireNotNull(System.getenv("OMNICORE_TEST_GGUF"))
        val api = OmniApi(ConnectionPolicy.validatedUrl(base, true), token)
        try {
            api.health()
            api.importModel(path)
            val model = api.models().single()
            assertEquals("llama.cpp", model.backend)
            val parameters = Parameters(temperature = 0.0, context = 512, maxTokens = 32)
            api.load(model.id, parameters)
            val conversation = api.create("Android real CPU integration", model.id, parameters)
            val job =
                api.generate(
                    conversation.id,
                    GenerationRequest(
                        "Write a warm welcome to a local AI app.",
                        UUID.randomUUID().toString(),
                        model.id,
                    ),
                )
            var snapshots = 0
            val final =
                withTimeout(130000) {
                    api.snapshots(job.id).first {
                        snapshots++
                        it.terminal
                    }
                }
            assertEquals("completed", final.state)
            assertTrue(final.content.isNotBlank())
            assertTrue(snapshots > 1)
            assertTrue(
                api.messages(conversation.id).any {
                    it.role == "assistant" && it.content == final.content
                }
            )
            api.saveParameters(conversation.id, parameters.copy(maxTokens = 2048))
            val second =
                api.generate(
                    conversation.id,
                    GenerationRequest(
                        "Count from one to one hundred, explaining each number in detail.",
                        UUID.randomUUID().toString(),
                        model.id,
                    ),
                )
            withTimeout(130000) {
                api.snapshots(second.id).first { it.content.isNotBlank() || it.terminal }
            }
            delay(200)
            val detached = api.generation(second.id)
            assertNotEquals("cancelled", detached.state)
            assertNotEquals("failed", detached.state)
            assertFalse(
                "Generation must still be active for an actual cancel test",
                detached.terminal,
            )
            assertEquals("cancelled", api.cancel(second.id).state)
            val reconnected = OmniApi(base, token)
            try {
                assertTrue(
                    reconnected.messages(conversation.id).any { it.content == final.content }
                )
            } finally {
                reconnected.close()
            }
            api.unload(model.id)
            api.delete(conversation.id)
        } finally {
            api.close()
        }
    }
}
