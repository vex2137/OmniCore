package io.github.vex2137.omnicore

import android.app.ActivityManager
import android.content.Context
import android.net.Uri
import java.io.File
import java.util.UUID
import java.util.concurrent.CompletableFuture
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext

/**
 * Fully offline on-device [OmniRepository] backed by [LocalLlamaEngine],
 * [LocalModelStore], and [LocalConversationStore].
 */
class LocalOmniRepository(
    private val context: Context?,
    private val engine: LocalLlamaEngine,
    private val modelsStore: LocalModelStore,
    private val conversationsStore: LocalConversationStore,
    private val io: kotlinx.coroutines.CoroutineDispatcher = Dispatchers.IO,
) : OmniRepository {
    constructor(context: Context) : this(
        context = context.applicationContext,
        engine = LocalLlamaEngine(context.applicationContext),
        modelsStore = LocalModelStore(context.applicationContext.filesDir),
        conversationsStore = LocalConversationStore(context.applicationContext.filesDir),
    )

    private data class ActiveJob(
        @Volatile var generation: Generation,
        val listeners: CopyOnWriteArrayList<Pair<(Generation) -> Unit, (String) -> Unit>> =
            CopyOnWriteArrayList(),
        val seq: AtomicLong = AtomicLong(0),
        val done: CompletableFuture<Generation> = CompletableFuture(),
    )

    private val executor = Executors.newSingleThreadExecutor()
    private val jobs = ConcurrentHashMap<String, ActiveJob>()
    private val verifiedModels = ConcurrentHashMap.newKeySet<String>()
    private val unsupportedModels = ConcurrentHashMap.newKeySet<String>()
    private val mutableImportProgress = MutableStateFlow<Pair<Float, String>?>(null)
    val importProgress: StateFlow<Pair<Float, String>?> = mutableImportProgress.asStateFlow()

    override suspend fun health(): Health =
        Health(status = "ok", version = BuildConfig.VERSION_NAME)

    override suspend fun conversations(): List<Conversation> =
        withContext(io) { conversationsStore.list() }

    override suspend fun models(): List<ModelInfo> =
        withContext(io) {
            modelsStore.list().map { rec ->
                val compat =
                    when {
                        !engine.isBinaryAvailable() -> "unsupported"
                        rec.id in unsupportedModels -> "unsupported"
                        rec.id in verifiedModels -> "tested"
                        else -> "unverified"
                    }
                ModelInfo(
                    id = rec.id,
                    name = rec.name,
                    backend = "llama.cpp-android",
                    format = "gguf",
                    sizeBytes = rec.sizeBytes,
                    quantization = rec.quantization,
                    compatibility = compat,
                    architecture = rec.architecture,
                    contextLength = rec.contextLength,
                )
            }
        }

    override suspend fun engines(): List<EngineDiagnostic> =
        withContext(io) {
            val snap = engine.snapshot()
            val gpuDevices =
                if (snap.gpuDevices.isNotEmpty()) snap.gpuDevices else engine.probeVulkanDevices()
            val afterProbe = engine.snapshot()
            val caps =
                buildList {
                    add("cpu")
                    if (gpuDevices.isNotEmpty()) add("vulkan")
                }
            val vulkanInfo =
                VulkanCapabilityInfo(
                    supported = afterProbe.vulkanApiVersion != null || gpuDevices.isNotEmpty(),
                    apiVersion = afterProbe.vulkanApiVersion,
                    hardwareLevel = afterProbe.vulkanHardwareLevel,
                    deviceName = afterProbe.deviceName,
                    vendor = afterProbe.deviceVendor,
                    reportedHeapMiB = afterProbe.reportedHeapMiB,
                    unifiedMemory = true,
                    offloadSupported = gpuDevices.isNotEmpty(),
                    activeLayers = if (afterProbe.gpuActive) afterProbe.offloadedLayers else 0,
                    fallbackReason = afterProbe.fallbackReason,
                    diagnosticSummary = afterProbe.gpuDiagnosticSummary,
                )
            listOf(
                EngineDiagnostic(
                    info =
                        EngineInfo(
                            id = "llama.cpp-android",
                            version = "c3df4b7e",
                            available = afterProbe.available,
                            capabilities = caps,
                            resources = Resources(ram = afterProbe.ramBytes ?: totalDeviceRamBytes()),
                        ),
                    gpuDevices = gpuDevices,
                    vulkan = vulkanInfo,
                )
            )
        }

    override suspend fun messages(id: String): List<Message> =
        withContext(io) { conversationsStore.messages(id) }

    override suspend fun create(
        title: String,
        model: String?,
        parameters: Parameters?,
    ): Conversation =
        withContext(io) { conversationsStore.create(title, model, parameters) }

    override suspend fun rename(id: String, title: String) =
        withContext(io) { conversationsStore.rename(id, title) }

    override suspend fun selectModel(conversationId: String, modelId: String) =
        withContext(io) {
            conversationsStore.selectModel(conversationId, modelId)
            val snap = engine.snapshot()
            if (snap.loaded && snap.loadedModelId != modelId) {
                engine.unload()
            }
        }

    override suspend fun saveParameters(id: String, parameters: Parameters) =
        withContext(io) { conversationsStore.saveParameters(id, parameters) }

    override suspend fun delete(id: String) =
        withContext(io) { conversationsStore.delete(id) }

    override suspend fun generate(id: String, payload: GenerationRequest): Generation =
        withContext(io) {
            val modelId = payload.modelId
            val model = modelsStore.find(modelId) ?: throw ApiFailure("model_not_found")
            val modelFile = File(model.path)
            if (!modelFile.isFile) throw ApiFailure("model_not_found")
            if (!model.hasTokenizer) throw ApiFailure("missing_tokenizer")

            val historyBefore = conversationsStore.messages(id)
            val last = historyBefore.lastOrNull()
            // Do not duplicate an identical pending/failed user message on retry.
            if (last == null || last.role != "user" || last.content != payload.content) {
                val userMsg =
                    Message(
                        id = UUID.randomUUID().toString().replace("-", ""),
                        role = "user",
                        content = payload.content,
                        status = "completed",
                    )
                conversationsStore.appendMessage(id, userMsg)
            }

            val params = payload.parameters ?: conversationsStore.get(id)?.parameters ?: Parameters()
            val clampedParams =
                model.contextLength?.let { modelMax ->
                    if (params.context > modelMax) params.copy(context = modelMax) else params
                } ?: params
            val history = conversationsStore.messages(id)
            val promptMessages = buildList {
                if (clampedParams.systemPrompt.isNotBlank()) {
                    add("system" to clampedParams.systemPrompt.trim())
                }
                history.takeLast(24).forEach { msg ->
                    if (msg.role in setOf("user", "assistant") && msg.content.isNotBlank()) {
                        add(msg.role to msg.content)
                    }
                }
            }

            val jobId = UUID.randomUUID().toString().replace("-", "")
            val initial =
                Generation(
                    id = jobId,
                    conversationId = id,
                    state = "queued",
                    modelName = model.name,
                )
            val active = ActiveJob(initial)
            jobs[jobId] = active

            executor.execute {
                try {
                    publish(active, active.generation.copy(state = "running"))
                    val result =
                        engine.streamChat(
                            modelId = model.id,
                            modelName = model.name,
                            modelFile = modelFile,
                            messages = promptMessages,
                            parameters = clampedParams,
                        ) { content, reasoning ->
                            publish(
                                active,
                                active.generation.copy(
                                    state = "running",
                                    content = content,
                                    reasoningContent = reasoning,
                                ),
                            )
                        }
                    verifiedModels.add(model.id)
                    unsupportedModels.remove(model.id)
                    val completed =
                        active.generation.copy(
                            state = "completed",
                            content = result.content,
                            reasoningContent = result.reasoning,
                            tokensPerSecond = result.tokensPerSecond,
                            gpuOffloadedLayers = result.gpuOffloadedLayers,
                            executionDevice = result.executionDevice,
                            fallbackReason = result.fallbackReason,
                            inputTokens = result.inputTokens,
                            outputTokens = result.outputTokens,
                            ttftSeconds = result.ttftSeconds,
                            firstAnswerSeconds = result.firstAnswerSeconds,
                            generationSeconds = result.generationSeconds,
                            modelLoadSeconds = engine.snapshot().loadSeconds,
                            contextUsedTokens = result.contextUsedTokens,
                            contextLimitTokens = result.contextLimitTokens,
                            finishReason = result.finishReason,
                        )
                    conversationsStore.appendMessage(
                        id,
                        Message(
                            id = UUID.randomUUID().toString().replace("-", ""),
                            role = "assistant",
                            content = result.content,
                            modelName = model.name,
                            reasoningContent = result.reasoning,
                            statistics = completed.statistics(),
                            status = "completed",
                            generationId = jobId,
                        ),
                    )
                    val terminal = publish(active, completed)
                    active.done.complete(terminal)
                } catch (e: Exception) {
                    val code = (e as? ApiFailure)?.code ?: "model_load_failed"
                    if (code in setOf("unsupported_architecture", "unsupported_quantization", "missing_tokenizer")) {
                        unsupportedModels.add(model.id)
                    }
                    val state = if (code == "cancelled") "cancelled" else "failed"
                    val partialResult = (e as? CancelledGenerationFailure)?.partial
                    val partial =
                        partialResult?.content?.ifEmpty { active.generation.content }
                            ?: active.generation.content
                    val partialReasoning =
                        partialResult?.reasoning?.ifEmpty { active.generation.reasoningContent }
                            ?: active.generation.reasoningContent
                    val snap = engine.snapshot()
                    val terminalBase =
                        if (state == "cancelled") {
                            active.generation.copy(
                                state = "cancelled",
                                content = partial,
                                reasoningContent = partialReasoning,
                                errorCode = null,
                                tokensPerSecond = partialResult?.tokensPerSecond ?: active.generation.tokensPerSecond,
                                gpuOffloadedLayers =
                                    partialResult?.gpuOffloadedLayers
                                        ?: if (snap.gpuActive) snap.offloadedLayers else 0,
                                executionDevice =
                                    partialResult?.executionDevice
                                        ?: if (snap.gpuActive) (snap.deviceName ?: "Vulkan") else "CPU",
                                fallbackReason = partialResult?.fallbackReason ?: snap.fallbackReason,
                                inputTokens = partialResult?.inputTokens,
                                outputTokens = partialResult?.outputTokens,
                                ttftSeconds = partialResult?.ttftSeconds,
                                firstAnswerSeconds = partialResult?.firstAnswerSeconds,
                                generationSeconds = partialResult?.generationSeconds,
                                modelLoadSeconds = snap.loadSeconds,
                                contextUsedTokens = partialResult?.contextUsedTokens,
                                contextLimitTokens = partialResult?.contextLimitTokens ?: clampedParams.context,
                                finishReason = "cancelled",
                            )
                        } else {
                            active.generation.copy(
                                state = "failed",
                                errorCode = code,
                            )
                        }
                    if (state == "cancelled" && (partial.isNotBlank() || partialReasoning.isNotBlank())) {
                        conversationsStore.appendMessage(
                            id,
                            Message(
                                id = UUID.randomUUID().toString().replace("-", ""),
                                role = "assistant",
                                content = partial,
                                modelName = model.name,
                                reasoningContent = partialReasoning,
                                statistics = terminalBase.statistics(),
                                status = "cancelled",
                                generationId = jobId,
                            ),
                        )
                    }
                    val terminal = publish(active, terminalBase)
                    active.done.complete(terminal)
                }
            }
            initial
        }

    override suspend fun generation(id: String): Generation =
        jobs[id]?.generation ?: throw ApiFailure("not_found")

    override suspend fun cancel(id: String): Generation =
        withContext(io) {
            val active = jobs[id] ?: throw ApiFailure("not_found")
            engine.cancelGeneration()
            runCatching { active.done.get(2, TimeUnit.SECONDS) }.getOrElse {
                val cancelled = publish(
                    active,
                    active.generation.copy(state = "cancelled", finishReason = "cancelled"),
                )
                active.done.complete(cancelled)
                cancelled
            }
        }

    override suspend fun load(id: String, parameters: Parameters): Unit =
        withContext(io) {
            val model = modelsStore.find(id) ?: throw ApiFailure("model_not_found")
            if (!model.hasTokenizer) throw ApiFailure("missing_tokenizer")
            val clampedCtx =
                model.contextLength?.let { minOf(parameters.context, it) } ?: parameters.context
            try {
                engine.prepare(
                    modelId = model.id,
                    modelName = model.name,
                    modelFile = File(model.path),
                    contextSize = clampedCtx,
                    devicePreference = parameters.device,
                    gpuLayers = parameters.gpuLayers,
                )
                verifiedModels.add(model.id)
                unsupportedModels.remove(model.id)
                Unit
            } catch (e: ApiFailure) {
                if (e.code in setOf("unsupported_architecture", "unsupported_quantization", "missing_tokenizer")) {
                    unsupportedModels.add(model.id)
                }
                throw e
            }
        }

    override suspend fun unload(id: String) =
        withContext(io) { engine.unload() }

    override suspend fun removeModel(id: String) =
        withContext(io) {
            if (engine.snapshot().loadedModelId == id) engine.unload()
            modelsStore.remove(context, id)
        }

    override suspend fun importModel(path: String) {
        withContext(io) {
            val trimmed = path.trim()
            if (trimmed.isBlank()) throw ApiFailure("model_not_found")
            try {
                if (trimmed.startsWith("content://") && context != null) {
                    modelsStore.importContentUri(context, Uri.parse(trimmed)) { pct, name ->
                        mutableImportProgress.value = pct to name
                    }
                } else {
                    modelsStore.importLocalFile(File(trimmed))
                }
            } finally {
                mutableImportProgress.value = null
            }
        }
    }

    override suspend fun search(query: String): List<HubRepository> = emptyList()

    override suspend fun files(repository: String): List<RemoteFile> = emptyList()

    override suspend fun downloads(): List<Download> = emptyList()

    override suspend fun download(file: RemoteFile): Download =
        throw ApiFailure("offline_mode_unsupported")

    override suspend fun cancelDownload(id: String): Download =
        throw ApiFailure("offline_mode_unsupported")

    override suspend fun resumeDownload(id: String): Download =
        throw ApiFailure("offline_mode_unsupported")

    override suspend fun diagnostics(): Diagnostics =
        withContext(io) {
            Diagnostics(
                jobs =
                    jobs.values.map {
                        DiagnosticJob(
                            id = it.generation.id,
                            state = it.generation.state,
                            errorCode = it.generation.errorCode,
                        )
                    }
            )
        }

    override fun watch(
        id: String,
        snapshot: (Generation) -> Unit,
        failure: (String) -> Unit,
    ): StreamHandle {
        val active = jobs[id]
        if (active == null) {
            failure("not_found")
            return StreamHandle {}
        }
        val pair = snapshot to failure
        active.listeners.add(pair)
        snapshot(active.generation)
        return StreamHandle { active.listeners.remove(pair) }
    }

    fun loadedModelId(): String? = engine.snapshot().loadedModelId

    fun activeSnapshot(): LocalEngineSnapshot = engine.snapshot()

    override fun close() {
        engine.close()
        executor.shutdownNow()
    }

    private fun publish(active: ActiveJob, next: Generation): Generation {
        val numbered = next.copy(sequence = active.seq.incrementAndGet())
        active.generation = numbered
        active.listeners.forEach { (cb, _) -> cb(numbered) }
        return numbered
    }

    private fun totalDeviceRamBytes(): Long? {
        val ctx = context ?: return null
        return runCatching {
            val am = ctx.getSystemService(Context.ACTIVITY_SERVICE) as? ActivityManager ?: return null
            val info = ActivityManager.MemoryInfo()
            am.getMemoryInfo(info)
            info.totalMem
        }.getOrNull()
    }
}
