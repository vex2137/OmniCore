package io.github.vex2137.omnicore

import android.content.Context
import android.os.Build
import java.io.BufferedReader
import java.io.File
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.InetAddress
import java.net.ServerSocket
import java.net.URL
import java.nio.charset.StandardCharsets
import java.nio.file.Files
import java.nio.file.Paths
import java.util.Locale
import java.util.UUID
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong
import java.util.regex.Pattern
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

data class VulkanDeviceInfo(
    val id: String,
    val name: String,
    val vendor: String,
    val heapMiB: Long? = null,
)

data class LocalEngineSnapshot(
    val available: Boolean,
    val loaded: Boolean,
    val loadedModelId: String? = null,
    val loadedModelName: String? = null,
    val backend: String = "cpu-native",
    val gpuActive: Boolean = false,
    val offloadedLayers: Int = 0,
    val deviceName: String? = null,
    val deviceVendor: String? = null,
    val reportedHeapMiB: Long? = null,
    val vulkanApiVersion: String? = null,
    val vulkanHardwareLevel: Int? = null,
    val gpuDevices: List<String> = emptyList(),
    val fallbackReason: String? = null,
    val ramBytes: Long? = null,
    val loadSeconds: Double? = null,
    val gpuDiagnosticSummary: String? = null,
)

data class LocalGenerationResult(
    val content: String,
    val reasoning: String,
    val finishReason: String,
    val inputTokens: Int?,
    val outputTokens: Int?,
    val ttftSeconds: Double?,
    val firstAnswerSeconds: Double?,
    val generationSeconds: Double,
    val tokensPerSecond: Double?,
    val contextUsedTokens: Int?,
    val contextLimitTokens: Int,
    val gpuOffloadedLayers: Int,
    val executionDevice: String,
    val fallbackReason: String?,
)

class CancelledGenerationFailure(val partial: LocalGenerationResult) : ApiFailure("cancelled")

/**
 * Manages the pinned on-device llama-server binary (arm64 CPU + Vulkan).
 * Bound strictly to 127.0.0.1 with an ephemeral per-launch API key.
 */
class LocalLlamaEngine(
    private val binaryProvider: () -> File,
    private val sdkLevel: Int = Build.VERSION.SDK_INT,
    private val cpuThreads: Int = Runtime.getRuntime().availableProcessors().coerceIn(1, 4),
    private val vulkanApiVersion: String? = null,
    private val vulkanHardwareLevel: Int? = null,
) {
    constructor(context: Context) : this(
        binaryProvider = {
            File(context.applicationInfo.nativeLibraryDir, "libomnicore_llama.so")
        },
        sdkLevel = Build.VERSION.SDK_INT,
        vulkanApiVersion = readVulkanApiVersion(context),
        vulkanHardwareLevel = readVulkanHardwareLevel(context),
    )

    private val epoch = AtomicLong(0)
    private val lock = Any()

    @Volatile private var process: Process? = null
    @Volatile private var probeProcess: Process? = null
    @Volatile private var activeConnection: HttpURLConnection? = null

    private var loadedModelId: String? = null
    private var loadedModelPath: String? = null
    private var loadedModelName: String? = null
    private var loadedContext: Int = 2048
    private var loadedLayerTarget: Int = 0
    private var apiKey: String = ""
    private var endpoint: String = ""
    private var gpuMode: Boolean = false
    private var gpuConfirmed: Boolean = false
    @Volatile private var offloadedLayers: Int = 0
    private var deviceName: String? = null
    private var deviceVendor: String? = null
    private var reportedHeapMiB: Long? = null
    private var fallbackReason: String? = null
    private var loadSeconds: Double? = null
    private var lastLog: String = ""
    private var gpuDiagnostics: GpuDiagnostics? = null
    private var probedDevices: List<VulkanDeviceInfo> = emptyList()

    fun isBinaryAvailable(): Boolean = binaryProvider().isFile && sdkLevel >= 28

    fun snapshot(): LocalEngineSnapshot {
        val p = process
        val alive = p != null && p.isAlive && loadedModelId != null
        val firstDev = probedDevices.firstOrNull()
        return LocalEngineSnapshot(
            available = isBinaryAvailable(),
            loaded = alive,
            loadedModelId = if (alive) loadedModelId else null,
            loadedModelName = if (alive) loadedModelName else null,
            backend = if (gpuMode) "vulkan" else "cpu-native",
            gpuActive = alive && gpuConfirmed,
            offloadedLayers = if (alive) offloadedLayers else 0,
            deviceName = deviceName ?: firstDev?.name,
            deviceVendor = deviceVendor ?: firstDev?.vendor,
            reportedHeapMiB = reportedHeapMiB ?: firstDev?.heapMiB,
            vulkanApiVersion = vulkanApiVersion,
            vulkanHardwareLevel = vulkanHardwareLevel,
            gpuDevices = probedDevices.map { "${it.id}: ${it.name}" },
            fallbackReason = fallbackReason,
            ramBytes = if (alive) readProcessRssBytes(p) else null,
            loadSeconds = loadSeconds,
            gpuDiagnosticSummary = gpuDiagnostics?.summary(),
        )
    }

    fun probeVulkanDevices(): List<String> {
        if (!isBinaryAvailable()) return emptyList()
        val version = epoch.get()
        return runCatching {
            val output = runProbe(version)
            probedDevices = parseVulkanDeviceInfos(output)
            probedDevices.map { "${it.id}: ${it.name}" }
        }.getOrElse { emptyList() }
    }

    fun prepare(
        modelId: String,
        modelName: String,
        modelFile: File,
        contextSize: Int,
        devicePreference: String,
        gpuLayers: Int,
    ) {
        synchronized(lock) {
            val version = epoch.get()
            val alive = process?.isAlive == true
            val normalizedMode = normalizeMode(devicePreference)
            val targetGpuLayers =
                if (normalizedMode == "cpu") 0 else gpuLayers.takeIf { it > 0 } ?: 99
            if (
                alive &&
                    loadedModelId == modelId &&
                    loadedModelPath == modelFile.absolutePath &&
                    loadedContext == contextSize &&
                    loadedLayerTarget == targetGpuLayers &&
                    ((normalizedMode == "cpu" && !gpuMode) || (normalizedMode != "cpu" && gpuMode))
            ) {
                return
            }
            if (!isBinaryAvailable()) throw ApiFailure("engine_unavailable")
            if (!modelFile.isFile) throw ApiFailure("model_not_found")
            fallbackReason = null

            if (normalizedMode != "cpu") {
                val diag = GpuDiagnostics(targetGpuLayers, contextSize)
                gpuDiagnostics = diag
                try {
                    val output = runProbe(version, diag)
                    probedDevices = parseVulkanDeviceInfos(output)
                    val chosen = probedDevices.firstOrNull()
                    if (chosen == null) {
                        fallbackReason = "no-compatible-gpu"
                        diag.fail(ApiFailure("gpu_unavailable"), null)
                    } else {
                        deviceName = chosen.name
                        deviceVendor = chosen.vendor
                        reportedHeapMiB = chosen.heapMiB
                        diag.selected(chosen.id)
                        startServer(
                            modelId = modelId,
                            modelName = modelName,
                            modelFile = modelFile,
                            contextSize = contextSize,
                            vulkanDevice = chosen.id,
                            gpuLayers = targetGpuLayers,
                            version = version,
                            diag = diag,
                        )
                        return
                    }
                } catch (e: Exception) {
                    checkEpoch(version)
                    val exit = process?.let { if (it.isAlive) null else it.exitValue() }
                    diag.fail(e, exit)
                    stopProcess()
                    // Structural model errors must never silently retry or be masked as GPU failures.
                    if (
                        e is ApiFailure &&
                            e.code in
                            setOf(
                                "unsupported_architecture",
                                "unsupported_quantization",
                                "missing_tokenizer",
                                "invalid_gguf",
                                "incomplete_gguf",
                            )
                    ) {
                        throw e
                    }
                    fallbackReason = diag.fallbackReason()
                }
                if (normalizedMode == "gpu") throw ApiFailure("gpu_unavailable")
            }

            startServer(
                modelId = modelId,
                modelName = modelName,
                modelFile = modelFile,
                contextSize = contextSize,
                vulkanDevice = null,
                gpuLayers = 0,
                version = version,
                diag = null,
            )
        }
    }

    fun streamChat(
        modelId: String,
        modelName: String,
        modelFile: File,
        messages: List<Pair<String, String>>,
        parameters: Parameters,
        onDelta: (content: String, reasoning: String) -> Unit,
    ): LocalGenerationResult {
        val version = epoch.get()
        prepare(
            modelId = modelId,
            modelName = modelName,
            modelFile = modelFile,
            contextSize = parameters.context,
            devicePreference = parameters.device,
            gpuLayers = parameters.gpuLayers,
        )
        checkEpoch(version)
        return try {
            executeChatStream(messages, parameters, version, onDelta)
        } catch (e: Exception) {
            if (e is CancelledGenerationFailure) throw e
            checkEpoch(version)
            val normalizedMode = normalizeMode(parameters.device)
            if (!gpuMode || normalizedMode == "gpu") throw e
            if (e is ApiFailure && e.code in setOf("context_limit_exceeded", "empty_response", "reasoning_limit_reached")) {
                throw e
            }
            // Safe GPU-to-CPU fallback when Vulkan inference fails before completing.
            synchronized(lock) {
                gpuDiagnostics?.recordStage("inference")
                gpuDiagnostics?.fail(
                    e,
                    process?.let { if (it.isAlive) null else it.exitValue() },
                )
                stopProcess()
                fallbackReason = "gpu-inference-failed"
                startServer(
                    modelId = modelId,
                    modelName = modelName,
                    modelFile = modelFile,
                    contextSize = parameters.context,
                    vulkanDevice = null,
                    gpuLayers = 0,
                    version = version,
                    diag = null,
                )
            }
            executeChatStream(messages, parameters, version, onDelta)
        }
    }

    fun cancelGeneration() {
        epoch.incrementAndGet()
        activeConnection?.disconnect()
    }

    fun unload() {
        epoch.incrementAndGet()
        activeConnection?.disconnect()
        synchronized(lock) { stopProcess() }
    }

    fun close() {
        epoch.incrementAndGet()
        activeConnection?.disconnect()
        probeProcess?.destroy()
        synchronized(lock) { stopProcess() }
    }

    private fun executeChatStream(
        messages: List<Pair<String, String>>,
        parameters: Parameters,
        version: Long,
        onDelta: (content: String, reasoning: String) -> Unit,
    ): LocalGenerationResult {
        val payload =
            buildJsonObject {
                    put(
                        "messages",
                        buildJsonArray {
                            messages.forEach { (role, text) ->
                                add(
                                    buildJsonObject {
                                        put("role", role)
                                        put("content", text)
                                    }
                                )
                            }
                        },
                    )
                    put("max_tokens", parameters.maxTokens)
                    put("temperature", parameters.temperature)
                    put("top_p", parameters.topP)
                    put("top_k", parameters.topK)
                    put("repeat_penalty", parameters.repeatPenalty)
                    if (parameters.seed > 0) put("seed", parameters.seed)
                    put("stream", true)
                    put("stream_options", buildJsonObject { put("include_usage", true) })
                    put(
                        "chat_template_kwargs",
                        buildJsonObject { put("enable_thinking", parameters.thinking) },
                    )
                }
                .toString()

        val conn =
            (URL("$endpoint/v1/chat/completions").openConnection() as HttpURLConnection).apply {
                connectTimeout = 2000
                readTimeout = 180_000
                requestMethod = "POST"
                doOutput = true
                setRequestProperty("Authorization", "Bearer $apiKey")
                setRequestProperty("Content-Type", "application/json")
            }
        activeConnection = conn
        val startedNs = System.nanoTime()
        var ttftSeconds: Double? = null
        var firstAnswerSeconds: Double? = null
        val contentBuf = StringBuilder()
        val reasoningBuf = StringBuilder()
        var streamedChunks = 0
        var finishReason = "stop"
        var usageObj: JsonObject? = null
        var timingsObj: JsonObject? = null

        fun snapshotResult(finalFinishReason: String): LocalGenerationResult {
            val totalSeconds = ((System.nanoTime() - startedNs) / 1e9).coerceAtLeast(0.001)
            val inputTokens =
                usageObj?.get("prompt_tokens")?.jsonPrimitive?.intOrNull
                    ?: timingsObj?.get("prompt_n")?.jsonPrimitive?.intOrNull
            val rawOutputTokens =
                usageObj?.get("completion_tokens")?.jsonPrimitive?.intOrNull
                    ?: timingsObj?.get("predicted_n")?.jsonPrimitive?.intOrNull
            val effectiveOutputTokens = rawOutputTokens ?: streamedChunks.takeIf { it > 0 }
            val predictedPerSec =
                timingsObj?.get("predicted_per_second")?.jsonPrimitive?.doubleOrNull
                    ?: effectiveOutputTokens?.let { it / totalSeconds }
            val confirmedGpu = gpuMode && offloadedLayers > 0 && (effectiveOutputTokens ?: 0) > 0
            if (confirmedGpu) {
                gpuConfirmed = true
                gpuDiagnostics?.confirmed()
            }
            return LocalGenerationResult(
                content = contentBuf.toString(),
                reasoning = reasoningBuf.toString(),
                finishReason = finalFinishReason,
                inputTokens = inputTokens,
                outputTokens = effectiveOutputTokens,
                ttftSeconds = ttftSeconds,
                firstAnswerSeconds = firstAnswerSeconds,
                generationSeconds = totalSeconds,
                tokensPerSecond = predictedPerSec,
                contextUsedTokens =
                    if (inputTokens != null && effectiveOutputTokens != null) {
                        inputTokens + effectiveOutputTokens
                    } else null,
                contextLimitTokens = loadedContext,
                gpuOffloadedLayers = if (confirmedGpu || (gpuMode && offloadedLayers > 0)) offloadedLayers else 0,
                executionDevice = if (confirmedGpu || (gpuMode && offloadedLayers > 0)) (deviceName ?: "Vulkan") else "CPU",
                fallbackReason = fallbackReason,
            )
        }

        try {
            conn.outputStream.use { it.write(payload.toByteArray(StandardCharsets.UTF_8)) }
            if (conn.responseCode != 200) {
                val errText =
                    runCatching { conn.errorStream?.bufferedReader()?.readText().orEmpty() }
                        .getOrDefault("")
                throw ApiFailure(classifyHttpError(errText))
            }
            BufferedReader(InputStreamReader(conn.inputStream, StandardCharsets.UTF_8)).use {
                reader ->
                while (true) {
                    val line = reader.readLine() ?: break
                    checkEpoch(version)
                    if (!line.startsWith("data:")) continue
                    val raw = line.substring(5).trim()
                    if (raw == "[DONE]" || raw.isEmpty()) continue
                    val chunk = WireJson.parseToJsonElement(raw).jsonObject
                    val choices = chunk["choices"]?.jsonArray
                    if (choices != null && choices.isNotEmpty()) {
                        val choice = choices[0].jsonObject
                        val delta = choice["delta"]?.jsonObject
                        if (delta != null) {
                            val rDelta =
                                delta["reasoning_content"]?.jsonPrimitive?.contentOrNull.orEmpty()
                            val cDelta = delta["content"]?.jsonPrimitive?.contentOrNull.orEmpty()
                            if (rDelta.isNotEmpty() || cDelta.isNotEmpty()) {
                                streamedChunks++
                                val elapsed = (System.nanoTime() - startedNs) / 1e9
                                if (ttftSeconds == null) ttftSeconds = elapsed
                                if (cDelta.isNotEmpty() && firstAnswerSeconds == null) {
                                    firstAnswerSeconds = elapsed
                                }
                                reasoningBuf.append(rDelta)
                                contentBuf.append(cDelta)
                                onDelta(contentBuf.toString(), reasoningBuf.toString())
                            }
                        }
                        choice["finish_reason"]?.jsonPrimitive?.contentOrNull?.let {
                            if (it != "null") finishReason = it
                        }
                    }
                    chunk["usage"]?.let { if (it is JsonObject) usageObj = it }
                    chunk["timings"]?.let { if (it is JsonObject) timingsObj = it }
                }
            }
            if (contentBuf.isEmpty()) {
                if (reasoningBuf.isNotEmpty() && finishReason == "length") {
                    throw ApiFailure("reasoning_limit_reached")
                }
                throw ApiFailure("empty_response")
            }
            return snapshotResult(finishReason)
        } catch (e: Exception) {
            if (epoch.get() != version || (e is ApiFailure && e.code == "cancelled")) {
                throw CancelledGenerationFailure(snapshotResult("cancelled"))
            }
            throw e
        } finally {
            conn.disconnect()
            if (activeConnection === conn) activeConnection = null
        }
    }

    private fun startServer(
        modelId: String,
        modelName: String,
        modelFile: File,
        contextSize: Int,
        vulkanDevice: String?,
        gpuLayers: Int,
        version: Long,
        diag: GpuDiagnostics?,
    ) {
        stopProcess()
        checkEpoch(version)
        val binary = binaryProvider()
        if (!binary.isFile) throw ApiFailure("engine_unavailable")

        val port = ServerSocket(0, 0, InetAddress.getByName("127.0.0.1")).use { it.localPort }
        apiKey = UUID.randomUUID().toString().replace("-", "")
        endpoint = "http://127.0.0.1:$port"
        offloadedLayers = 0
        lastLog = ""
        val startedNs = System.nanoTime()

        val args =
            listOf(
                binary.absolutePath,
                "--host",
                "127.0.0.1",
                "--port",
                port.toString(),
                "--api-key",
                apiKey,
                "--model",
                modelFile.absolutePath,
                "--ctx-size",
                contextSize.toString(),
                "--parallel",
                "1",
                "--threads",
                cpuThreads.toString(),
                "--batch-size",
                "128",
                "--ubatch-size",
                "64",
                "--no-webui",
                "-lv",
                "4",
                "--n-gpu-layers",
                if (vulkanDevice == null) "0" else gpuLayers.toString(),
                "--device",
                vulkanDevice ?: "none",
                "--jinja",
            )
        diag?.recordStage("process-start")
        val builder = ProcessBuilder(args).redirectErrorStream(true)
        binary.parent?.let { builder.environment()["LD_LIBRARY_PATH"] = it }
        val p = builder.start()
        process = p
        diag?.recordStage("native-startup")

        val reader =
            Thread {
                try {
                    BufferedReader(InputStreamReader(p.inputStream)).use { br ->
                        var line: String?
                        while (br.readLine().also { line = it } != null) {
                            val text = line!!
                            synchronized(this) {
                                lastLog = (lastLog + text + '\n').takeLast(32_000)
                            }
                            diag?.line(text)
                            val m = OFFLOAD_PATTERN.matcher(text)
                            if (m.find()) {
                                offloadedLayers = m.group(1)?.toIntOrNull() ?: offloadedLayers
                            }
                        }
                    }
                } catch (_: Exception) {
                }
            }
        reader.isDaemon = true
        reader.start()

        try {
            val deadline = System.nanoTime() + 120_000_000_000L
            var ready = false
            while (System.nanoTime() < deadline) {
                checkEpoch(version)
                if (!p.isAlive) throw ApiFailure("model_load_failed")
                if (probeHealth()) {
                    ready = true
                    break
                }
                Thread.sleep(100)
            }
            checkEpoch(version)
            if (!ready) throw ApiFailure("model_load_timeout")
            if (vulkanDevice != null && offloadedLayers < 1) throw ApiFailure("gpu_offload_failed")

            loadedModelId = modelId
            loadedModelPath = modelFile.absolutePath
            loadedModelName = modelName
            loadedContext = contextSize
            loadedLayerTarget = if (vulkanDevice == null) 0 else gpuLayers
            gpuMode = vulkanDevice != null
            gpuConfirmed = false
            loadSeconds = (System.nanoTime() - startedNs) / 1e9
            diag?.loaded(offloadedLayers)
        } catch (e: Exception) {
            if (!p.isAlive) reader.join(500)
            val detail = synchronized(this) { lastLog }
            stopProcess()
            if (e is ApiFailure && e.code == "cancelled") throw e
            val classified = classifyStartupLog(detail)
            if (classified != null) throw ApiFailure(classified)
            throw e
        }
    }

    private fun probeHealth(): Boolean =
        runCatching {
            val conn =
                (URL("$endpoint/health").openConnection() as HttpURLConnection).apply {
                    connectTimeout = 500
                    readTimeout = 1000
                    setRequestProperty("Authorization", "Bearer $apiKey")
                }
            try {
                conn.responseCode == 200
            } finally {
                conn.disconnect()
            }
        }.getOrDefault(false)

    private fun runProbe(version: Long, diag: GpuDiagnostics? = null): String {
        val binary = binaryProvider()
        val builder = ProcessBuilder(binary.absolutePath, "--list-devices").redirectErrorStream(true)
        binary.parent?.let { builder.environment()["LD_LIBRARY_PATH"] = it }
        val p = builder.start()
        probeProcess = p
        val out = StringBuilder()
        val reader =
            Thread {
                try {
                    BufferedReader(InputStreamReader(p.inputStream)).use { br ->
                        var line: String?
                        while (br.readLine().also { line = it } != null) {
                            val text = line!!
                            synchronized(out) {
                                if (out.length < 32_000) out.append(text).append('\n')
                            }
                            diag?.line(text)
                        }
                    }
                } catch (_: Exception) {
                }
            }
        reader.start()
        try {
            if (!p.waitFor(10, TimeUnit.SECONDS)) throw ApiFailure("gpu_probe_timeout")
            reader.join(1000)
            checkEpoch(version)
            if (p.exitValue() != 0) throw ApiFailure("gpu_driver_failed")
            return synchronized(out) { out.toString() }
        } finally {
            killProcess(p)
            if (probeProcess === p) probeProcess = null
        }
    }

    private fun stopProcess() {
        val p = process
        loadedModelId = null
        loadedModelPath = null
        loadedModelName = null
        loadedLayerTarget = 0
        gpuMode = false
        gpuConfirmed = false
        offloadedLayers = 0
        killProcess(p)
        if (process === p) process = null
    }

    private fun killProcess(p: Process?) {
        if (p == null) return
        p.destroy()
        if (!p.waitFor(1500, TimeUnit.MILLISECONDS)) {
            p.destroyForcibly()
            p.waitFor(3000, TimeUnit.MILLISECONDS)
        }
    }

    private fun checkEpoch(expected: Long) {
        if (epoch.get() != expected) throw ApiFailure("cancelled")
    }

    private fun readProcessRssBytes(p: Process?): Long? {
        if (p == null) return null
        return runCatching {
            val pid = (p.javaClass.getMethod("pid").invoke(p) as Number).toLong()
            val lines = Files.readAllLines(Paths.get("/proc/$pid/status"))
            val vmRss = lines.firstOrNull { it.startsWith("VmRSS:") } ?: return null
            vmRss.replace(Regex("[^0-9]"), "").toLong() * 1024L
        }.getOrNull()
    }

    companion object {
        private val OFFLOAD_PATTERN = Pattern.compile("offloaded (\\d+)/\\d+ layers to GPU")
        private val VULKAN_DEVICE_PATTERN =
            Pattern.compile("(?m)^\\s*(Vulkan\\d+):\\s*(.+?)(?:\\s*\\((\\d+)\\s*MiB,\\s*(\\d+)\\s*MiB free\\))?\\s*$")
        private val SOFTWARE_RENDERER_RE =
            Regex("(?i).*(llvmpipe|lavapipe|swiftshader|software|cpu).*")

        fun normalizeMode(devicePreference: String): String =
            when {
                devicePreference.equals("cpu", ignoreCase = true) -> "cpu"
                devicePreference.equals("gpu", ignoreCase = true) ||
                    devicePreference.equals("cuda", ignoreCase = true) ||
                    devicePreference.equals("vulkan", ignoreCase = true) ||
                    devicePreference.startsWith("Vulkan", ignoreCase = true) -> "gpu"
                else -> "auto"
            }

        fun inferVendor(deviceName: String): String {
            val lower = deviceName.lowercase(Locale.ROOT)
            return when {
                "mali" in lower || "immortalis" in lower -> "ARM Mali"
                "adreno" in lower -> "Qualcomm Adreno"
                "powervr" in lower -> "Imagination PowerVR"
                "xclipse" in lower -> "Samsung Xclipse"
                "nvidia" in lower || "geforce" in lower -> "NVIDIA"
                "amd" in lower || "radeon" in lower -> "AMD"
                "intel" in lower -> "Intel"
                else -> "Unknown"
            }
        }

        fun parseVulkanDeviceInfos(output: String): List<VulkanDeviceInfo> {
            val result = ArrayList<VulkanDeviceInfo>()
            val matcher = VULKAN_DEVICE_PATTERN.matcher(output)
            while (matcher.find()) {
                val id = matcher.group(1)?.trim().orEmpty()
                val name = matcher.group(2)?.trim().orEmpty()
                val heap = matcher.group(3)?.toLongOrNull()
                if (id.isNotEmpty() && name.isNotEmpty() && !SOFTWARE_RENDERER_RE.matches(name)) {
                    result.add(VulkanDeviceInfo(id = id, name = name, vendor = inferVendor(name), heapMiB = heap))
                }
            }
            return result
        }

        fun parseVulkanDevices(output: String): List<Pair<String, String>> =
            parseVulkanDeviceInfos(output).map { it.id to it.name }

        fun classifyStartupLog(log: String): String? {
            val lower = log.lowercase(Locale.ROOT)
            return when {
                "unknown model architecture" in lower ||
                    "unsupported model architecture" in lower ||
                    "arch not supported" in lower -> "unsupported_architecture"
                "unsupported quantization" in lower ||
                    "unknown tensor type" in lower ||
                    "unsupported file_type" in lower ||
                    "unsupported ftype" in lower -> "unsupported_quantization"
                "missing tokenizer" in lower ||
                    "no tokenizer" in lower ||
                    "failed to load vocab" in lower -> "missing_tokenizer"
                "exceeds the available context" in lower ||
                    "n_ctx" in lower && "exceed" in lower -> "context_limit_exceeded"
                "out of memory" in lower ||
                    "bad_alloc" in lower ||
                    "allocation failed" in lower ||
                    "vk_error_out_of_device_memory" in lower ||
                    "vk_error_out_of_host_memory" in lower -> "out_of_memory"
                "not a gguf" in lower ||
                    "invalid gguf" in lower ||
                    "corrupted" in lower ||
                    "truncated" in lower ||
                    "bad magic" in lower -> "invalid_gguf"
                else -> null
            }
        }

        fun classifyHttpError(body: String): String {
            val lower = body.lowercase(Locale.ROOT)
            return when {
                "exceeds the available context" in lower ||
                    "context size" in lower ||
                    "prompt is too long" in lower -> "context_limit_exceeded"
                "out of memory" in lower -> "out_of_memory"
                else -> "invalid_response"
            }
        }

        private fun readVulkanApiVersion(context: Context): String? {
            val feat =
                context.packageManager.systemAvailableFeatures.firstOrNull {
                    it.name == "android.hardware.vulkan.version"
                } ?: return null
            val v = feat.version
            val major = (v shr 22) and 0x3ff
            val minor = (v shr 12) and 0x3ff
            val patch = v and 0xfff
            return "$major.$minor.$patch"
        }

        private fun readVulkanHardwareLevel(context: Context): Int? =
            context.packageManager.systemAvailableFeatures
                .firstOrNull { it.name == "android.hardware.vulkan.level" }
                ?.version
    }
}
