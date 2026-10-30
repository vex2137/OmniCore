package io.github.vex2137.omnicore

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.*
import org.junit.Test

class PairingTest {
    @Test
    fun qrRequiresPrivateDestinationCodeAndVersionButUsesServerExpiry() {
        val good = PairingQr(1, "http://192.168.1.12:8000", "a".repeat(64), 1100.0)
        assertEquals(good, PairingPolicy.parse(WireJson.encodeToString(good), 1000.0))
        assertEquals(good, PairingPolicy.parse(WireJson.encodeToString(good), 5000.0))
        assertEquals(good, PairingPolicy.parse(WireJson.encodeToString(good), 100.0))
        for (bad in listOf(good.copy(url = "https://public.example"), good.copy(url = "http://127.0.0.1:8000"), good.copy(url = "http://[::1]:8000"), good.copy(code = "wrong"), good.copy(omnicore = 2), good.copy(expiresAt = -1.0))) {
            try { PairingPolicy.parse(WireJson.encodeToString(bad), 1000.0); fail("Accepted bad QR") }
            catch (_: ApiFailure) { }
        }
    }

    @Test
    fun exchangeSendsOnlyOneTimeCodeWithoutMasterCredential() = runBlocking {
        val server = MockWebServer()
        server.enqueue(MockResponse().setBody("""{"device_id":"phone","token":"${"b".repeat(64)}"}"""))
        server.start()
        val api = OmniApi(server.url("/").toString().trimEnd('/'), "")
        try {
            assertEquals("phone", api.redeemPairing("a".repeat(64)).deviceId)
            val request = server.takeRequest()
            assertEquals("/api/v1/pairing/redeem", request.path)
            assertNull(request.getHeader("Authorization"))
            assertEquals("a".repeat(64), WireJson.parseToJsonElement(request.body.readUtf8()).jsonObject["code"]!!.jsonPrimitive.content)
        } finally { api.close(); server.shutdown() }
    }

    @Test
    fun ollamaDoesNotReceiveLlamaGpuOverrides() {
        val gpu = Parameters(device = "cuda", gpuLayers = 25)
        assertEquals(gpu, gpu.forBackend("llama.cpp"))
        assertEquals("cpu", gpu.forBackend("ollama").device)
        assertEquals(0, gpu.forBackend("ollama").gpuLayers)
    }
}
