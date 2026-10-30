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
    fun zxingDecodesPairingQrAndRejectsBlankImage() {
        val qr = PairingQr(1, "http://192.168.1.12:8000", "a".repeat(64), 2000.0)
        val encoded = WireJson.encodeToString(qr)
        val matrix = com.google.zxing.qrcode.QRCodeWriter().encode(encoded, com.google.zxing.BarcodeFormat.QR_CODE, 400, 400)
        val pixels = IntArray(400 * 400) { i -> if (matrix[i % 400, i / 400]) 0xff000000.toInt() else 0xffffffff.toInt() }
        fun decode(values: IntArray): String = com.google.zxing.qrcode.QRCodeReader().decode(
            com.google.zxing.BinaryBitmap(com.google.zxing.common.HybridBinarizer(com.google.zxing.RGBLuminanceSource(400, 400, values)))
        ).text
        assertEquals(qr, PairingPolicy.parse(decode(pixels)))
        try { decode(IntArray(400 * 400) { 0xffffffff.toInt() }); fail("Blank image decoded") }
        catch (_: com.google.zxing.NotFoundException) { }
    }

    @Test
    fun pairingErrorsAreNotConfusedWithRejectedDeviceCredentials() = runBlocking {
        val server = MockWebServer()
        for (code in listOf("pairing_invalid", "pairing_expired", "pairing_used", "pairing_lan_required"))
            server.enqueue(MockResponse().setResponseCode(403).setBody("""{"error":{"code":"$code"}}"""))
        server.enqueue(MockResponse().setResponseCode(403).setBody("""{"error":{"code":"forbidden"}}"""))
        server.start()
        val api = OmniApi(server.url("/").toString().trimEnd('/'), "")
        try {
            for (expected in listOf("pairing_invalid", "pairing_expired", "pairing_used", "pairing_lan_required", "unauthorized")) {
                try { api.redeemPairing("a".repeat(64), "b".repeat(64)); fail("Expected rejection") }
                catch (e: ApiFailure) { assertEquals(expected, e.code) }
            }
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
