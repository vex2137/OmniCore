package io.github.vex2137.omnicore

import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.file.Files
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class LocalInferenceTest {
    private val tempDirs = mutableListOf<File>()

    @After
    fun cleanup() {
        Dispatchers.resetMain()
        tempDirs.forEach { it.deleteRecursively() }
    }

    private fun tempDir(): File =
        Files.createTempDirectory("omnicore-local-test-").toFile().also { tempDirs.add(it) }

    private fun writeFakeGguf(file: File, version: Int = 3) {
        val header = ByteBuffer.allocate(16).order(ByteOrder.LITTLE_ENDIAN)
        header.put('G'.code.toByte())
        header.put('G'.code.toByte())
        header.put('U'.code.toByte())
        header.put('F'.code.toByte())
        header.putInt(version)
        header.putLong(0L)
        file.writeBytes(header.array())
    }

    @Test
    fun ggufValidationRejectsNonGgufAndAcceptsValidHeader() {
        val dir = tempDir()
        val valid = File(dir, "LFM3-1.7B-Q8_0.gguf")
        writeFakeGguf(valid, version = 3)
        val bad = File(dir, "not_a_model.gguf").apply { writeText("hello world") }

        val store = LocalModelStore(dir)
        val rec = store.importLocalFile(valid)
        assertEquals("LFM3-1.7B-Q8_0", rec.name)
        assertEquals("Q8_0", rec.quantization)
        assertFalse(rec.managedFile)
        assertEquals(1, store.list().size)

        try {
            store.importLocalFile(bad)
            fail("Expected invalid_gguf")
        } catch (e: ApiFailure) {
            assertEquals("invalid_gguf", e.code)
        }

        // Removing an external (non-managed) entry keeps the original file intact.
        store.remove(null, rec.id)
        assertTrue(store.list().isEmpty())
        assertTrue(valid.isFile)
    }

    @Test
    fun conversationStorePersistsHistoryAndParametersAcrossReload() {
        val dir = tempDir()
        val store1 = LocalConversationStore(dir)
        val params = Parameters(temperature = 0.2, maxTokens = 512, context = 4096, device = "vulkan")
        val conv = store1.create("Offline Chat", "m1", params)
        store1.appendMessage(
            conv.id,
            Message(id = "u1", role = "user", content = "Hi offline!"),
        )
        store1.rename(conv.id, "Renamed Chat")

        val store2 = LocalConversationStore(dir)
        val loaded = store2.list()
        assertEquals(1, loaded.size)
        assertEquals("Renamed Chat", loaded[0].title)
        assertEquals("m1", loaded[0].modelId)
        assertEquals(4096, loaded[0].parameters.context)
        assertEquals("vulkan", loaded[0].parameters.device)
        assertEquals(listOf("Hi offline!"), store2.messages(conv.id).map { it.content })
    }

    @Test
    fun vulkanDeviceParserFiltersSoftwareRenderersAndConfirmsHardwareGpu() {
        val probeOutput =
            """
            ggml_vulkan: Found 2 Vulkan devices:
              Vulkan0: llvmpipe (LLVM 17.0.6, 256 bits)
              Vulkan1: Adreno (TM) 740
            """.trimIndent()
        val devices = LocalLlamaEngine.parseVulkanDevices(probeOutput)
        assertEquals(listOf("Vulkan1" to "Adreno (TM) 740"), devices)
        assertEquals("cpu", LocalLlamaEngine.normalizeMode("cpu"))
        assertEquals("gpu", LocalLlamaEngine.normalizeMode("vulkan"))
        assertEquals("gpu", LocalLlamaEngine.normalizeMode("cuda"))
        assertEquals("auto", LocalLlamaEngine.normalizeMode("auto"))
    }

    @Test
    fun gpuDiagnosticsSanitizesSecretsAndClassifiesVulkanErrors() {
        val diag = GpuDiagnostics(requestedLayers = 99, contextLength = 2048)
        diag.line("Authorization: Bearer secret12345 /data/user/0/secret.gguf")
        diag.line("Vulkan error VK_ERROR_OUT_OF_DEVICE_MEMORY at createComputePipeline")
        diag.fail(ApiFailure("gpu_offload_failed"), 1)
        val summary = diag.summary()
        assertFalse(summary.contains("secret12345"))
        assertFalse(summary.contains("/data/user"))
        assertEquals("insufficient-vram", diag.fallbackReason())
    }

    @Test
    fun endToEndLocalInferenceStreamingVulkanFallbackAndUnloadWithMockLlamaBinary() {
        val dir = tempDir()
        val gguf = File(dir, "tiny-Q4_K_M.gguf")
        writeFakeGguf(gguf)

        // Executable Python mock llama-server simulating --list-devices, /health, Vulkan fail -> CPU fallback, and SSE streaming.
        val script =
            File(dir, "libomnicore_llama.so").apply {
                writeText(
                    """#!/usr/bin/env python3
import http.server, json, sys, time

args = sys.argv[1:]
if "--list-devices" in args:
    print("Vulkan0: Adreno (TM) 740", flush=True)
    sys.exit(0)

def arg(name, default=None):
    return args[args.index(name) + 1] if name in args else default

port = int(arg("--port", "0"))
device = arg("--device", "none")
if device.startswith("Vulkan"):
    # Simulate Vulkan shader/OOM failure on startup so auto mode must fall back to CPU!
    print("ggml_vulkan: VK_ERROR_OUT_OF_DEVICE_MEMORY", flush=True)
    sys.exit(1)

print("load_tensors: offloaded 0/12 layers to GPU", flush=True)

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200); self.end_headers(); self.wfile.write(b'{"status":"ok"}')
    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        _ = self.rfile.read(n)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        chunks = [
            {"choices":[{"delta":{"content":"Offline "},"finish_reason":None}]},
            {"choices":[{"delta":{"content":"OK"},"finish_reason":"stop"}],
             "usage":{"prompt_tokens":10,"completion_tokens":2},
             "timings":{"prompt_n":10,"predicted_n":2,"predicted_per_second":42.5}},
        ]
        for c in chunks:
            self.wfile.write(("data: " + json.dumps(c) + "\n\n").encode())
            self.wfile.flush()
            time.sleep(0.02)
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

http.server.HTTPServer(("127.0.0.1", port), Handler).serve_forever()
""".trimIndent()
                )
                setExecutable(true)
            }

        val engine = LocalLlamaEngine(binaryProvider = { script }, sdkLevel = 34, cpuThreads = 2)
        val models = LocalModelStore(dir)
        val convs = LocalConversationStore(dir)
        val repo = LocalOmniRepository(null, engine, models, convs)

        runBlocking {
            repo.importModel(gguf.absolutePath)
            val modelList = repo.models()
            assertEquals(1, modelList.size)
            val conv = repo.create("Local Test", modelList[0].id, Parameters(device = "auto"))
            val job =
                repo.generate(
                    conv.id,
                    GenerationRequest(
                        content = "Hello",
                        requestKey = "req-1",
                        modelId = modelList[0].id,
                        parameters = Parameters(device = "auto"),
                    ),
                )
            val snapshots = mutableListOf<Generation>()
            val handle = repo.watch(job.id, { snapshots.add(it) }, { fail("Unexpected error: $it") })
            val deadline = System.currentTimeMillis() + 15_000
            while (System.currentTimeMillis() < deadline) {
                if (snapshots.lastOrNull()?.terminal == true) break
                delay(50)
            }
            handle.cancel()

            val finalGen = snapshots.lastOrNull()
            assertNotNull(finalGen)
            assertEquals("completed", finalGen!!.state)
            assertEquals("Offline OK", finalGen.content)
            assertEquals("CPU", finalGen.executionDevice)
            assertEquals(0, finalGen.gpuOffloadedLayers)
            assertEquals("insufficient-vram", finalGen.fallbackReason)
            assertEquals(42.5, finalGen.tokensPerSecond ?: 0.0, 0.01)
            assertEquals(1, repo.messages(conv.id).count { it.role == "assistant" })

            repo.unload(modelList[0].id)
            assertFalse(engine.snapshot().loaded)
            repo.close()
        }
    }

    @Test
    fun viewModelBootsIntoLocalModeOfflineWithoutRemoteUrl() = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        val dir = tempDir()
        val settings =
            object : ClientSettings {
                override var url = ""
                override var localMode = true
                override var trustedLan = false
                override var theme = "system"
                override var language = "en-US"
                override var conversationId: String? = null
                override var generationId: String? = null
                override var parameters = Parameters()

                override fun storeToken(token: String) {}

                override fun readToken() = ""
            }
        val engine =
            LocalLlamaEngine(
                binaryProvider = { File(dir, "missing_llama.so") },
                sdkLevel = 34,
            )
        val vm =
            OmniViewModel(
                settings = settings,
                io = dispatcher,
                localRepository = {
                    LocalOmniRepository(
                        null,
                        engine,
                        LocalModelStore(dir),
                        LocalConversationStore(dir), dispatcher,
                    )
                },
            )
        advanceUntilIdle()
        assertTrue(vm.state.value.localMode)
        assertTrue(vm.state.value.connected)
        assertNull(vm.state.value.error)
        vm.createConversation("Offline Note")
        advanceUntilIdle()
        assertEquals(1, vm.state.value.conversations.size)
        vm.pause()
    }

    @Test
    fun safPickerPauseResumeAndImportFromMultipleFoldersRegistersModelsWithoutConnectionError() =
        runTest {
            val dispatcher = StandardTestDispatcher(testScheduler)
            Dispatchers.setMain(dispatcher)
            val dir = tempDir()
            val downloads = File(dir, "Download").apply { mkdirs() }
            val otherFolder = File(dir, "Documents/AI").apply { mkdirs() }
            val modelA = File(downloads, "LFM3-1.7B-Q8_0.gguf").also { writeFakeGguf(it) }
            val modelB = File(otherFolder, "Qwen3.5-4B-Q4_K_M.gguf").also { writeFakeGguf(it) }
            val badFile = File(downloads, "corrupt.gguf").apply { writeText("not gguf") }

            val settings =
                object : ClientSettings {
                    override var url = ""
                    override var localMode = true
                    override var trustedLan = false
                    override var theme = "system"
                    override var language = "en-US"
                    override var conversationId: String? = null
                    override var generationId: String? = null
                    override var parameters = Parameters()

                    override fun storeToken(token: String) {}

                    override fun readToken() = ""
                }
            val engine =
                LocalLlamaEngine(
                    binaryProvider = { File(dir, "libomnicore_llama.so") },
                    sdkLevel = 34,
                )
            val repo =
                LocalOmniRepository(
                    null,
                    engine,
                    LocalModelStore(dir),
                    LocalConversationStore(dir),
                    dispatcher,
                )
            val vm =
                OmniViewModel(
                    settings = settings,
                    io = dispatcher,
                    localRepository = { repo },
                )
            advanceUntilIdle()
            assertTrue(vm.state.value.connected)
            assertTrue(vm.state.value.localMode)

            // Simulate system file picker opening (onStop -> pause), returning (onStart -> resume),
            // and immediately firing the ActivityResult callback before/during resume.
            vm.pause()
            vm.resume()
            vm.importModel(modelA.absolutePath)
            advanceUntilIdle()
            assertNull(vm.state.value.error)
            assertEquals(1, vm.state.value.models.size)
            assertEquals("LFM3-1.7B-Q8_0", vm.state.value.models[0].name)

            // Simulate importing from a second folder while connectLocal() is busy (activity recreate).
            vm.connectLocal()
            vm.importModel(modelB.absolutePath)
            advanceUntilIdle()
            assertNull(vm.state.value.error)
            assertEquals(2, vm.state.value.models.size)

            // Invalid GGUF must report invalid_gguf, never not_connected or connection_error.
            vm.importModel(badFile.absolutePath)
            advanceUntilIdle()
            assertEquals("invalid_gguf", vm.state.value.error)
            assertEquals(2, vm.state.value.models.size)
            vm.pause()
        }
}
