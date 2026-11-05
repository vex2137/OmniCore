package io.github.vex2137.omnicore

import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.*
import org.junit.Test

class ClientTest {
    @Test
    fun publicHttpIsRejectedEvenWithLanConsent() {
        for (url in listOf("http://8.8.8.8:8000", "http://public.example", "http://192.169.1.2")) {
            try {
                ConnectionPolicy.validatedUrl(url, true)
                fail(url)
            } catch (e: ApiFailure) {
                assertEquals("https_required", e.code)
            }
        }
    }

    @Test
    fun localHttpRequiresExplicitConsent() {
        for (url in
            listOf("http://192.168.1.10:8000", "http://10.0.2.2:8000", "http://172.16.1.2:8000")) {
            try {
                ConnectionPolicy.validatedUrl(url, false)
                fail()
            } catch (e: ApiFailure) {
                assertEquals("https_required", e.code)
            }
            assertEquals(url, ConnectionPolicy.validatedUrl(url, true))
        }
    }

    @Test
    fun httpsAndBasePathsAreSupported() {
        assertEquals(
            "https://example.org/omnicore",
            ConnectionPolicy.validatedUrl("https://example.org/omnicore/", false),
        )
    }

    @Test
    fun credentialsQueriesInvalidPortsAndOtherProtocolsAreRejected() {
        for (url in
            listOf(
                "https://user:pass@example.org",
                "https://example.org?token=x",
                "file:///tmp/db",
                "https://example.org:0",
                "https://example.org:99999",
                "https://example.org/#token",
            )) {
            try {
                ConnectionPolicy.validatedUrl(url, true)
                fail(url)
            } catch (e: ApiFailure) {
                assertEquals("invalid_url", e.code)
            }
        }
    }

    @Test
    fun contractDecodingPreservesNullsAndIgnoresAddedFields() {
        val model =
            WireJson.decodeFromString<ModelInfo>(
                """{"id":"m","name":"GGUF","backend":"llama.cpp","quantization":null,"new_field":true}"""
            )
        assertNull(model.quantization)
        val conversation =
            WireJson.decodeFromString<Conversation>(
                """{"id":"c","title":"Zażółć","model_id":null,"parameters":{"temperature":0.7}}"""
            )
        assertEquals("Zażółć", conversation.title)
    }

    @Test
    fun snapshotsReplaceContentAndSequencesAreScopedToJob() {
        val old = Generation("old", "chat", "completed", "old text", 999)
        val fresh = Generation("new", "chat", "running", "a", 1)
        assertTrue(acceptSnapshot(old, fresh))
        assertFalse(acceptSnapshot(fresh, fresh.copy(sequence = 0)))
        assertTrue(acceptSnapshot(fresh, fresh.copy(sequence = 2, content = "ab")))
        assertTrue(fresh.copy(state = "cancelled").terminal)
    }

    @Test
    fun requestUsesExistingApiContract() {
        val json =
            WireJson.encodeToString(
                GenerationRequest("Hi", "idempotent-key", "model", Parameters())
            )
        assertTrue(json.contains("\"request_key\":\"idempotent-key\""))
        assertTrue(json.contains("\"model_id\":\"model\""))
        assertFalse(json.contains("token" + "_value"))
    }

    @Test
    fun actualHttpUsesBearerAndJsonWithoutPuttingTokenInUrl() = runBlocking {
        val server = MockWebServer()
        server.enqueue(MockResponse().setBody("[]"))
        server.start()
        val api = OmniApi(server.url("/").toString().trimEnd('/'), "test-only-token")
        try {
            assertTrue(api.models().isEmpty())
            val call = server.takeRequest(2, TimeUnit.SECONDS)!!
            assertEquals("/api/v1/text/models", call.path)
            assertEquals("Bearer test-only-token", call.getHeader("Authorization"))
            assertFalse(call.path!!.contains("token"))
        } finally {
            api.close()
            server.shutdown()
        }
    }

    @Test
    fun redirectIsNotFollowedToAnotherHost() = runBlocking {
        val source = MockWebServer()
        val other = MockWebServer()
        other.start()
        source.enqueue(
            MockResponse().setResponseCode(302).addHeader("Location", other.url("/steal"))
        )
        source.start()
        val api = OmniApi(source.url("/").toString().trimEnd('/'), "test-only-token")
        try {
            try {
                api.models()
                fail()
            } catch (e: ApiFailure) {
                assertEquals("api_error", e.code)
            }
            assertNull(other.takeRequest(200, TimeUnit.MILLISECONDS))
        } finally {
            api.close()
            source.shutdown()
            other.shutdown()
        }
    }

    @Test
    fun authenticationErrorsDoNotEchoBodyOrToken() = runBlocking {
        val server = MockWebServer()
        server.enqueue(MockResponse().setResponseCode(401).setBody("secret body"))
        server.start()
        val api = OmniApi(server.url("/").toString().trimEnd('/'), "test-only-token")
        try {
            try {
                api.health()
                fail()
            } catch (e: ApiFailure) {
                assertEquals("unauthorized", e.message)
            }
        } finally {
            api.close()
            server.shutdown()
        }
    }

    @Test
    fun sseUsesCompleteSnapshotsAndCanBeCancelled() {
        val server = MockWebServer()
        server.enqueue(
            MockResponse()
                .setHeader("Content-Type", "text/event-stream")
                .setBody(
                    "data: {\"id\":\"j\",\"conversation_id\":\"c\",\"state\":\"running\",\"content\":\"a\",\"sequence\":1}\n\n" +
                        "data: {\"id\":\"j\",\"conversation_id\":\"c\",\"state\":\"completed\",\"content\":\"ab\",\"sequence\":2}\n\n"
                )
        )
        server.start()
        val api = OmniApi(server.url("/").toString().trimEnd('/'), "test-only-token")
        val latch = CountDownLatch(2)
        val records = java.util.Collections.synchronizedList(mutableListOf<Generation>())
        val events =
            api.watch(
                "j",
                {
                    records.add(it)
                    latch.countDown()
                },
                {},
            )
        try {
            assertTrue(latch.await(5, TimeUnit.SECONDS))
            assertEquals(listOf("a", "ab"), records.map { it.content })
        } finally {
            events.cancel()
            api.close()
            server.shutdown()
        }
    }

    @Test
    fun storedTokenIsBoundToOriginRatherThanPath() {
        assertTrue(
            ConnectionPolicy.sameOrigin("https://example.org:443/a", "https://example.org/b")
        )
        assertFalse(ConnectionPolicy.sameOrigin("https://example.org", "https://other.example.org"))
        assertFalse(ConnectionPolicy.sameOrigin("https://example.org", "http://example.org"))
    }

    @Test
    fun responseSizeIsBounded() = runBlocking {
        val server = MockWebServer()
        server.enqueue(MockResponse().setBody("x".repeat(2_000_001)))
        server.start()
        val api = OmniApi(server.url("/").toString().trimEnd('/'), "")
        try {
            try {
                api.health()
                fail()
            } catch (e: ApiFailure) {
                assertEquals("response_too_large", e.code)
            }
        } finally {
            api.close()
            server.shutdown()
        }
    }

    @Test
    fun cancellingTheCoroutineClosesItsActualHttpCall() = runBlocking {
        val server = MockWebServer()
        server.enqueue(
            MockResponse().setSocketPolicy(okhttp3.mockwebserver.SocketPolicy.NO_RESPONSE)
        )
        server.start()
        val api = OmniApi(server.url("/").toString().trimEnd('/'), "")
        try {
            val task = async(kotlinx.coroutines.Dispatchers.Default) { api.health() }
            assertNotNull(server.takeRequest(3, TimeUnit.SECONDS))
            kotlinx.coroutines.withTimeout(2000) {
                task.cancel()
                task.join()
            }
            assertTrue(task.isCancelled)
        } finally {
            api.close()
            server.shutdown()
        }
    }

    @Test
    fun healthRejectsAnUnrelatedSuccessfulHttpServer() = runBlocking {
        val server = MockWebServer()
        server.enqueue(MockResponse().setBody("{\"status\":\"something_else\"}"))
        server.start()
        val api = OmniApi(server.url("/").toString().trimEnd('/'), "")
        try {
            try {
                api.health()
                fail()
            } catch (e: ApiFailure) {
                assertEquals("incompatible_backend", e.code)
            }
        } finally {
            api.close()
            server.shutdown()
        }
    }

    @Test
    fun generationPreservesBackendConversationParametersByDefault() {
        val payload = WireJson.encodeToString(GenerationRequest("Hi", "key", "model"))
        assertFalse(payload.contains("parameters"))
    }

    @Test
    fun modelSelectionIsPersistedThroughConversationPatch() = runBlocking {
        val server = MockWebServer()
        server.enqueue(MockResponse().setBody("{}"))
        server.start()
        val api = OmniApi(server.url("/").toString().trimEnd('/'), "test-token")
        try {
            api.selectModel("c", "m2")
            val call = server.takeRequest(2, TimeUnit.SECONDS)!!
            assertEquals("PATCH", call.method)
            assertEquals("/api/v1/text/conversations/c", call.path)
            assertEquals("{\"model_id\":\"m2\"}", call.body.readUtf8())
        } finally {
            api.close()
            server.shutdown()
        }
    }

    @Test
    fun coldModelLoadCanOutlastTheOrdinaryReadTimeout() = runBlocking {
        val server = MockWebServer()
        server.enqueue(MockResponse().setHeadersDelay(200, TimeUnit.MILLISECONDS).setBody("{}"))
        server.start()
        val shortClient =
            okhttp3.OkHttpClient.Builder().readTimeout(50, TimeUnit.MILLISECONDS).build()
        val api = OmniApi(server.url("/").toString().trimEnd('/'), "test-token", shortClient)
        try {
            api.load("m", Parameters())
            val call = server.takeRequest(2, TimeUnit.SECONDS)!!
            assertEquals("/api/v1/text/models/m/load", call.path)
            assertEquals("Bearer test-token", call.getHeader("Authorization"))
        } finally {
            api.close()
            server.shutdown()
        }
    }
}
