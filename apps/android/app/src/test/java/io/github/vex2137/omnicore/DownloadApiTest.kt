package io.github.vex2137.omnicore

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.*
import org.junit.Test

class DownloadApiTest {
    @Test
    fun searchFilesConfirmationAndResumeUseBackendContracts() = runBlocking {
        val server = MockWebServer()
        val file =
            """{"repository":"owner/repo","revision":"abc","filename":"dir/a b.gguf","size_bytes":999,"license":"Apache-2.0"}"""
        server.enqueue(MockResponse().setBody("""[{"repository":"owner/repo","license":null}]"""))
        server.enqueue(MockResponse().setBody("[$file]"))
        repeat(3) {
            server.enqueue(
                MockResponse().setBody("""{"id":"d","source":$file,"state":"running"}""")
            )
        }
        server.start()
        val api = OmniApi(server.url("/").toString().trimEnd('/'), "test-only")
        try {
            assertEquals("owner/repo", api.search("a & b").single().id)
            assertEquals("a & b", server.takeRequest().requestUrl!!.queryParameter("query"))
            val source = api.files("owner/repo").single()
            assertEquals(
                "owner/repo",
                server.takeRequest().requestUrl!!.queryParameter("repository"),
            )
            api.download(source)
            val request = server.takeRequest()
            val body = WireJson.parseToJsonElement(request.body.readUtf8()).jsonObject
            assertEquals("POST", request.method)
            assertEquals("true", body["confirmed"]!!.jsonPrimitive.content)
            assertEquals("999", body["expected_size"]!!.jsonPrimitive.content)
            assertEquals("abc", body["revision"]!!.jsonPrimitive.content)
            assertFalse(body.containsKey("path"))
            api.cancelDownload("d")
            assertEquals("/api/v1/text/downloads/d/cancel", server.takeRequest().path)
            api.resumeDownload("d")
            assertEquals("/api/v1/text/downloads/d/resume", server.takeRequest().path)
        } finally {
            api.close()
            server.shutdown()
        }
    }

    @Test
    fun conversationParametersRoundTripPreservesBackendGpuSettings() {
        val original =
            """{"id":"c","parameters":{"temperature":0.7,"top_k":85,"gpu_layers":22,"device":"auto","repeat_penalty":1.3}}"""
        val conversation = WireJson.decodeFromString<Conversation>(original)
        val updated = conversation.parameters.copy(temperature = 1.1)
        assertEquals(22, updated.gpuLayers)
        assertEquals(85, updated.topK)
        assertEquals("auto", updated.device)
        assertTrue(updated.valid())
        assertFalse(updated.copy(topP = Double.POSITIVE_INFINITY).valid())
    }

    @Test
    fun sseDisconnectDoesNotImplicitlyCancelBackendTask() = runBlocking {
        val server = MockWebServer()
        server.enqueue(
            MockResponse()
                .setHeader("Content-Type", "text/event-stream")
                .setBody("data: {\"id\":\"g\",\"conversation_id\":\"c\",\"state\":\"running\"}\n\n")
        )
        server.start()
        val api = OmniApi(server.url("/").toString().trimEnd('/'), "test-only")
        try {
            val done = java.util.concurrent.CountDownLatch(1)
            val stream = api.watch("g", { done.countDown() }, {})
            assertTrue(done.await(5, java.util.concurrent.TimeUnit.SECONDS))
            assertEquals(
                "false",
                server.takeRequest().requestUrl!!.queryParameter("cancel_on_disconnect"),
            )
            stream.cancel()
            assertNull(server.takeRequest(200, java.util.concurrent.TimeUnit.MILLISECONDS))
        } finally {
            api.close()
            server.shutdown()
        }
    }
}
