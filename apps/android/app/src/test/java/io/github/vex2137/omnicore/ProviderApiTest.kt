package io.github.vex2137.omnicore

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.*
import org.junit.Test

class ProviderApiTest {
    @Test
    fun providerConfigurationCatalogSelectionAndRemovalUseSharedBackend() = runBlocking {
        val server = MockWebServer()
        val config = """{"id":"p","kind":"anthropic","label":"Work","endpoint":"https://api.anthropic.com/v1","key_present":true}"""
        listOf(config, "[$config]", "[\"controlled-chat\"]", "{}", "{}", "{}").forEach {
            server.enqueue(MockResponse().setBody(it))
        }
        server.start()
        val api = OmniApi(server.url("/").toString().trimEnd('/'), "manual-device-fixture")
        try {
            val input = ProviderInput("anthropic", "Work", "https://api.anthropic.com/v1", "synthetic-key")
            assertFalse(input.toString().contains("synthetic-key"))
            assertTrue(api.saveProvider(null, input).keyPresent)
            assertEquals("anthropic", api.providers().single().kind)
            assertEquals("controlled-chat", api.providerModels("p").single())
            api.testProvider("p")
            api.addProviderModel("p", "controlled-chat")
            api.deleteProvider("p")
            val requests = (1..6).map { server.takeRequest() }
            assertTrue(requests.all { it.getHeader("Authorization") == "Bearer manual-device-fixture" })
            assertTrue(requests.none { it.path!!.contains("synthetic-key") })
            assertEquals("synthetic-key", WireJson.parseToJsonElement(requests[0].body.readUtf8()).jsonObject["api_key"]!!.jsonPrimitive.content)
            assertEquals("/api/v1/providers/configs/p/test", requests[3].path)
            val model = WireJson.parseToJsonElement(requests[4].body.readUtf8()).jsonObject
            assertEquals("true", model["confirmed_external"]!!.jsonPrimitive.content)
            assertEquals("DELETE", requests[5].method)
            val stats = WireJson.decodeFromString<GenerationStatistics>("""{"execution_provider":"anthropic","execution_model":"controlled-chat","output_tokens":8}""")
            assertEquals("anthropic", stats.executionProvider)
            assertNull(stats.executionDevice)
        } finally { api.close(); server.shutdown() }
    }

    @Test
    fun nonceExchangeAndSensitiveDtosDoNotRevealCredentialsInDiagnostics() = runBlocking {
        val server = MockWebServer()
        val code = "a".repeat(64)
        val nonce = "b".repeat(64)
        server.enqueue(MockResponse().setBody("""{"device_id":"p","token":"${"c".repeat(64)}"}"""))
        server.start()
        val api = OmniApi(server.url("/").toString().trimEnd('/'), "")
        try {
            val result = api.redeemPairing(code, nonce)
            val request = server.takeRequest()
            val body = WireJson.parseToJsonElement(request.body.readUtf8()).jsonObject
            assertEquals(nonce, body["nonce"]!!.jsonPrimitive.content)
            assertNull(request.getHeader("Authorization"))
            assertFalse(result.toString().contains(result.token))
            assertFalse(PendingPairing(code, nonce).toString().contains(nonce))
            assertEquals(64, PairingPolicy.credential(code, nonce).length)
        } finally { api.close(); server.shutdown() }
    }
}
