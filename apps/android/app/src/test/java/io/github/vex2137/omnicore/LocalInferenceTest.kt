package io.github.vex2137.omnicore

import java.io.ByteArrayOutputStream
import java.io.DataOutputStream
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

    private fun writeFakeGguf(
        file: File,
        version: Int = 3,
        architecture: String = "qwen35",
        name: String = "Test Model",
        fileType: Int = 15, // Q4_K_M
        contextLength: Int = 32768,
        includeTokenizer: Boolean = true,
        splitCount: Int? = null,
        truncatePayload: Boolean = false,
    ) {
        val raw = ByteArrayOutputStream()
        val out = DataOutputStream(raw)

        fun putU32(v: Int) =
            out.write(ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN).putInt(v).array())

        fun putU64(v: Long) =
            out.write(ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN).putLong(v).array())

        fun putStr(s: String) {
            val b = s.toByteArray(Charsets.UTF_8)
            putU64(b.size.toLong())
            out.write(b)
        }

        val kvPairs = mutableListOf<Pair<String, Pair<Int, Any>>>(
            "general.architecture" to (8 to architecture),
            "general.name" to (8 to name),
            "general.file_type" to (4 to fileType),
            "$architecture.context_length" to (4 to contextLength),
        )
        if (includeTokenizer) kvPairs.add("tokenizer.ggml.model" to (8 to "gpt2"))
        if (splitCount != null) kvPairs.add("split.count" to (4 to splitCount))

        out.write(byteArrayOf('G'.code.toByte(), 'G'.code.toByte(), 'U'.code.toByte(), 'F'.code.toByte()))
        putU32(version)
        putU64(1L) // tensorCount
        putU64(kvPairs.size.toLong())

        for ((k, typedVal) in kvPairs) {
            putStr(k)
            val (vType, value) = typedVal
            putU32(vType)
            when (vType) {
                8 -> putStr(value as String)
                4 -> putU32((value as Number).toInt())
            }
        }

        // One F32 1x4 tensor (16 bytes) at offset 0.
        putStr("token_embd.weight")
        putU32(1)
        putU64(4L)
        putU32(0) // F32
        putU64(0L)

        val headerBytes = raw.toByteArray()
        val alignedStart = ((headerBytes.size + 31) / 32) * 32
        val pad = ByteArray(alignedStart - headerBytes.size)
        val tensorPayload = if (truncatePayload) ByteArray(4) else ByteArray(16)
        file.writeBytes(headerBytes + pad + tensorPayload)
    }

    @Test
    fun ggufReaderParsesLfm3AndDistinguishesInvalidIncompleteAndSplitFiles() {
        val dir = tempDir()
        val lfm3 = File(dir, "LFM3-1.7B-Q4_K_M.gguf")
        writeFakeGguf(
            lfm3,
            architecture = "lfm3",
            name = "LFM3 1.7B",
            fileType = 15,
            contextLength = 262144,
        )
        val store = LocalModelStore(dir)
        val rec = store.importLocalFile(lfm3)
        assertEquals("LFM3-1.7B-Q4_K_M", rec.name)
        assertEquals("lfm3", rec.architecture)
        assertEquals("Q4_K_M", rec.quantization)
        assertEquals(262144, rec.contextLength)
        assertTrue(rec.hasTokenizer)
        assertFalse(rec.managedFile)

        // Incomplete / truncated GGUF must report incomplete_gguf.
        val truncated = File(dir, "truncated.gguf")
        writeFakeGguf(truncated, truncatePayload = true)
        try {
            store.importLocalFile(truncated)
            fail("Expected incomplete_gguf")
        } catch (e: ApiFailure) {
            assertEquals("incomplete_gguf", e.code)
        }

        // Split GGUF must report multipart_gguf_unsupported.
        val split = File(dir, "split-00001-of-00002.gguf")
        writeFakeGguf(split, splitCount = 2)
        try {
            store.importLocalFile(split)
            fail("Expected multipart_gguf_unsupported")
        } catch (e: ApiFailure) {
            assertEquals("multipart_gguf_unsupported", e.code)
        }

        // Non-GGUF file must report invalid_gguf even when shorter than 24 bytes.
        val bad = File(dir, "not_a_model.gguf").apply { writeText("hello world") }
        try {
            store.importLocalFile(bad)
            fail("Expected invalid_gguf")
        } catch (e: ApiFailure) {
            assertEquals("invalid_gguf", e.code)
        }

        // Truncated GGUF header must report incomplete_gguf.
        val truncatedHeader = File(dir, "truncated_header.gguf").apply {
            writeBytes(byteArrayOf('G'.code.toByte(), 'G'.code.toByte(), 'U'.code.toByte(), 'F'.code.toByte(), 3, 0, 0, 0))
        }
        try {
            store.importLocalFile(truncatedHeader)
            fail("Expected incomplete_gguf")
        } catch (e: ApiFailure) {
            assertEquals("incomplete_gguf", e.code)
        }

        store.remove(null, rec.id)
        assertTrue(store.list().isEmpty())
        assertTrue(lfm3.isFile)
    }

    @Test
    fun nativeErrorClassifierNeverMislabelsUnsupportedArchAsInvalidGguf() {
        assertEquals(
            "unsupported_architecture",
            LocalLlamaEngine.classifyStartupLog("llama_model_load: error loading model: unknown model architecture: 'lfm3'"),
        )
        assertEquals(
            "unsupported_quantization",
            LocalLlamaEngine.classifyStartupLog("gguf_init_from_file: unknown tensor type 99"),
        )
        assertEquals(
            "missing_tokenizer",
            LocalLlamaEngine.classifyStartupLog("error: failed to load vocab from model"),
        )
        assertEquals(
            "out_of_memory",
            LocalLlamaEngine.classifyStartupLog("ggml_vulkan: VK_ERROR_OUT_OF_DEVICE_MEMORY"),
        )
        assertEquals(
            "context_limit_exceeded",
            LocalLlamaEngine.classifyHttpError("request (4096 tokens) exceeds the available context size (2048 tokens)"),
        )
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
    fun vulkanDeviceParserDetectsMaliAndNeverReportsSharedRamAsDedicatedVram() {
        val probeOutput =
            """
            ggml_vulkan: Found 2 Vulkan devices:
              Vulkan0: llvmpipe (LLVM 17.0.6, 256 bits)
              Vulkan1: Mali-G720 MC7 (11360 MiB, 11360 MiB free)
            """.trimIndent()
        val infos = LocalLlamaEngine.parseVulkanDeviceInfos(probeOutput)
        assertEquals(1, infos.size)
        assertEquals("Vulkan1", infos[0].id)
        assertEquals("Mali-G720 MC7", infos[0].name)
        assertEquals("ARM Mali", infos[0].vendor)
        assertEquals(11360L, infos[0].heapMiB)
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
    fun endToEndLocalInferenceStreamingVulkanFallbackModelSwitchingAndUnloadWithMockLlamaBinary() {
        val dir = tempDir()
        val gguf1 = File(dir, "tiny-Q4_K_M.gguf")
        val gguf2 = File(dir, "LFM3-1.7B-Q4_K_M.gguf")
        writeFakeGguf(gguf1, architecture = "qwen35", name = "Tiny Qwen", contextLength = 1024)
        writeFakeGguf(gguf2, architecture = "lfm3", name = "LFM3 1.7B", contextLength = 4096)

        val script =
            File(dir, "libomnicore_llama.so").apply {
                writeText(
                    """#!/usr/bin/env python3
import http.server, json, sys, time

args = sys.argv[1:]
if "--list-devices" in args:
    print("Vulkan0: Mali-G720 MC7 (11360 MiB, 11360 MiB free)", flush=True)
    sys.exit(0)

def arg(name, default=None):
    return args[args.index(name) + 1] if name in args else default

port = int(arg("--port", "0"))
device = arg("--device", "none")
model_path = arg("--model", "")
if device.startswith("Vulkan"):
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
        reply = "LFM3 OK" if "LFM3" in model_path else "Offline OK"
        chunks = [
            {"choices":[{"delta":{"content":reply.split()[0] + " "},"finish_reason":None}]},
            {"choices":[{"delta":{"content":reply.split()[1]},"finish_reason":"stop"}],
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

        val engine =
            LocalLlamaEngine(
                binaryProvider = { script },
                sdkLevel = 36,
                cpuThreads = 2,
                vulkanApiVersion = "1.3.0",
                vulkanHardwareLevel = 1,
            )
        val models = LocalModelStore(dir)
        val convs = LocalConversationStore(dir)
        val repo = LocalOmniRepository(null, engine, models, convs)

        runBlocking {
            repo.importModel(gguf1.absolutePath)
            repo.importModel(gguf2.absolutePath)
            val modelList = repo.models()
            assertEquals(2, modelList.size)
            val engineDiags = repo.engines()
            assertEquals(1, engineDiags.size)
            assertNull(engineDiags[0].info.resources.vram) // Never report unified RAM as dedicated VRAM.
            assertTrue(engineDiags[0].vulkan?.unifiedMemory == true)

            val qwen = modelList.first { it.architecture == "qwen35" }
            val lfm3 = modelList.first { it.architecture == "lfm3" }
            val conv = repo.create("Local Test", qwen.id, Parameters(device = "auto", context = 4096))

            // 1. Run Qwen (context clamped from 4096 -> 1024; Vulkan fails -> CPU fallback).
            val job1 =
                repo.generate(
                    conv.id,
                    GenerationRequest(
                        content = "Hello",
                        requestKey = "req-1",
                        modelId = qwen.id,
                        parameters = Parameters(device = "auto", context = 4096),
                    ),
                )
            val snaps1 = mutableListOf<Generation>()
            val h1 = repo.watch(job1.id, { snaps1.add(it) }, { fail("Unexpected error: $it") })
            val deadline1 = System.currentTimeMillis() + 15_000
            while (System.currentTimeMillis() < deadline1) {
                if (snaps1.lastOrNull()?.terminal == true) break
                delay(50)
            }
            h1.cancel()

            val final1 = snaps1.lastOrNull()
            assertNotNull(final1)
            assertEquals("completed", final1!!.state)
            assertEquals("Offline OK", final1.content)
            assertEquals("CPU", final1.executionDevice)
            assertEquals(1024, final1.contextLimitTokens)
            assertEquals("insufficient-vram", final1.fallbackReason)
            assertEquals(42.5, final1.tokensPerSecond ?: 0.0, 0.01)

            // 2. Switch models cleanly and run LFM3.
            repo.selectModel(conv.id, lfm3.id)
            assertFalse(engine.snapshot().loaded)
            val job2 =
                repo.generate(
                    conv.id,
                    GenerationRequest(
                        content = "Test LFM3",
                        requestKey = "req-2",
                        modelId = lfm3.id,
                        parameters = Parameters(device = "cpu"),
                    ),
                )
            val snaps2 = mutableListOf<Generation>()
            val h2 = repo.watch(job2.id, { snaps2.add(it) }, { fail("Unexpected error: $it") })
            val deadline2 = System.currentTimeMillis() + 15_000
            while (System.currentTimeMillis() < deadline2) {
                if (snaps2.lastOrNull()?.terminal == true) break
                delay(50)
            }
            h2.cancel()
            assertEquals("LFM3 OK", snaps2.lastOrNull()?.content)

            repo.unload(lfm3.id)
            assertFalse(engine.snapshot().loaded)
            repo.close()
        }
    }

    @Test
    fun safPickerPauseResumeAndImportFromMultipleFoldersRegistersModelsWithoutConnectionError() =
        runTest {
            val dispatcher = StandardTestDispatcher(testScheduler)
            Dispatchers.setMain(dispatcher)
            val dir = tempDir()
            val downloads = File(dir, "Download").apply { mkdirs() }
            val otherFolder = File(dir, "Documents/AI").apply { mkdirs() }
            val modelA =
                File(downloads, "LFM3-1.7B-Q4_K_M.gguf").also {
                    writeFakeGguf(it, architecture = "lfm3", name = "LFM3 1.7B")
                }
            val modelB =
                File(otherFolder, "Qwen3.5-4B-Q4_K_M.gguf").also {
                    writeFakeGguf(it, architecture = "qwen35", name = "Qwen3.5 4B")
                }
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
                    sdkLevel = 36,
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

            vm.pause()
            vm.resume()
            vm.importModel(modelA.absolutePath)
            advanceUntilIdle()
            assertNull(vm.state.value.error)
            assertEquals(1, vm.state.value.models.size)
            assertEquals("lfm3", vm.state.value.models[0].architecture)

            vm.connectLocal()
            vm.importModel(modelB.absolutePath)
            advanceUntilIdle()
            assertNull(vm.state.value.error)
            assertEquals(2, vm.state.value.models.size)

            vm.importModel(badFile.absolutePath)
            advanceUntilIdle()
            assertEquals("invalid_gguf", vm.state.value.error)
            assertEquals(2, vm.state.value.models.size)

            // Diagnostic report excludes user prompts/paths.
            vm.createConversation("Private Chat")
            advanceUntilIdle()
            val report = vm.diagnosticReportText()
            assertTrue(report.contains("OmniCore"))
            assertFalse(report.contains(dir.absolutePath))
            vm.pause()
        }
}
