package io.github.vex2137.omnicore

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

val WireJson = Json {
    ignoreUnknownKeys = true
    encodeDefaults = true
    explicitNulls = false
}

@Serializable
data class Conversation(
    val id: String,
    val title: String = "",
    val parameters: Parameters = Parameters(),
    @SerialName("model_id") val modelId: String? = null,
)

@Serializable
data class Message(
    val id: String = "",
    val role: String,
    val content: String,
    @SerialName("model_name") val modelName: String? = null,
    @SerialName("reasoning_content") val reasoningContent: String = "",
    val statistics: GenerationStatistics? = null,
    val status: String = "completed",
    @SerialName("generation_id") val generationId: String? = null,
)

@Serializable
data class ModelInfo(
    val id: String,
    val name: String,
    val backend: String,
    val format: String = "",
    @SerialName("size_bytes") val sizeBytes: Long = 0,
    val quantization: String? = null,
    val license: String? = null,
    val compatibility: String = "unverified",
)

@Serializable
data class Resources(
    @SerialName("ram_bytes") val ram: Long? = null,
    @SerialName("vram_bytes") val vram: Long? = null,
)

@Serializable
data class EngineInfo(
    val id: String,
    val version: String? = null,
    val available: Boolean,
    val capabilities: List<String> = emptyList(),
    val resources: Resources = Resources(),
)

@Serializable
data class EngineDiagnostic(
    val info: EngineInfo,
    @SerialName("gpu_devices") val gpuDevices: List<String> = emptyList(),
)

@Serializable
data class Parameters(
    val temperature: Double = 0.7,
    @SerialName("top_p") val topP: Double = 0.9,
    @SerialName("max_tokens") val maxTokens: Int = 256,
    @SerialName("context_size") val context: Int = 2048,
    @SerialName("system_prompt") val systemPrompt: String = "",
    @SerialName("top_k") val topK: Int = 40,
    @SerialName("repeat_penalty") val repeatPenalty: Double = 1.1,
    val seed: Int = 0,
    @SerialName("gpu_layers") val gpuLayers: Int = 0,
    val device: String = "cpu",
    val thinking: Boolean = false,
)

@Serializable
data class GenerationStatistics(
    @SerialName("execution_device") val executionDevice: String? = null,
    @SerialName("fallback_reason") val fallbackReason: String? = null,
    @SerialName("input_tokens") val inputTokens: Int? = null,
    @SerialName("output_tokens") val outputTokens: Int? = null,
    @SerialName("ttft_seconds") val ttftSeconds: Double? = null,
    @SerialName("first_answer_seconds") val firstAnswerSeconds: Double? = null,
    @SerialName("generation_seconds") val generationSeconds: Double? = null,
    @SerialName("model_load_seconds") val modelLoadSeconds: Double? = null,
    @SerialName("context_used_tokens") val contextUsedTokens: Int? = null,
    @SerialName("context_limit_tokens") val contextLimitTokens: Int? = null,
    @SerialName("finish_reason") val finishReason: String? = null,
    @SerialName("tokens_per_second") val tokensPerSecond: Double? = null,
)

@Serializable
data class Generation(
    val id: String,
    @SerialName("conversation_id") val conversationId: String,
    val state: String,
    val content: String = "",
    val sequence: Long = 0,
    @SerialName("error_code") val errorCode: String? = null,
    @SerialName("tokens_per_second") val tokensPerSecond: Double? = null,
    @SerialName("execution_device") val executionDevice: String? = null,
    @SerialName("fallback_reason") val fallbackReason: String? = null,
    @SerialName("model_name") val modelName: String? = null,
    @SerialName("reasoning_content") val reasoningContent: String = "",
    @SerialName("input_tokens") val inputTokens: Int? = null,
    @SerialName("output_tokens") val outputTokens: Int? = null,
    @SerialName("ttft_seconds") val ttftSeconds: Double? = null,
    @SerialName("first_answer_seconds") val firstAnswerSeconds: Double? = null,
    @SerialName("generation_seconds") val generationSeconds: Double? = null,
    @SerialName("model_load_seconds") val modelLoadSeconds: Double? = null,
    @SerialName("context_used_tokens") val contextUsedTokens: Int? = null,
    @SerialName("context_limit_tokens") val contextLimitTokens: Int? = null,
    @SerialName("finish_reason") val finishReason: String? = null,
) {
    fun statistics() =
        GenerationStatistics(
            executionDevice,
            fallbackReason,
            inputTokens,
            outputTokens,
            ttftSeconds,
            firstAnswerSeconds,
            generationSeconds,
            modelLoadSeconds,
            contextUsedTokens,
            contextLimitTokens,
            finishReason,
            tokensPerSecond,
        )

    val terminal: Boolean
        get() = state in setOf("completed", "cancelled", "failed", "interrupted")
}

@Serializable
data class CreateConversation(
    val title: String,
    val parameters: Parameters? = null,
    @SerialName("model_id") val modelId: String? = null,
)

@Serializable data class RenameConversation(val title: String)

@Serializable data class ModelSelection(@SerialName("model_id") val modelId: String)

@Serializable
data class GenerationRequest(
    val content: String,
    @SerialName("request_key") val requestKey: String,
    @SerialName("model_id") val modelId: String,
    val parameters: Parameters? = null,
)

@Serializable data class ModelImport(val path: String)

@Serializable data class ModelDelete(@SerialName("delete_file") val deleteFile: Boolean = false)

fun acceptSnapshot(previous: Generation?, next: Generation): Boolean =
    previous == null ||
        previous.id != next.id ||
        (next.sequence >= previous.sequence && (!previous.terminal || next.terminal))

@Serializable data class ParameterSelection(val parameters: Parameters)

@Serializable
data class Health(
    val status: String,
    val version: String = "",
    @SerialName("database_version") val databaseVersion: Int = 0,
)

@Serializable
data class HubRepository(@SerialName("repository") val id: String, val license: String? = null)

@Serializable
data class RemoteFile(
    val repository: String,
    val revision: String,
    val filename: String,
    @SerialName("size_bytes") val sizeBytes: Long,
    val license: String? = null,
    val sha256: String? = null,
)

@Serializable
data class Download(
    val id: String,
    val source: RemoteFile,
    val state: String,
    val percent: Double = 0.0,
    @SerialName("received_bytes") val receivedBytes: Long = 0,
    val path: String? = null,
    @SerialName("error_code") val errorCode: String? = null,
    @SerialName("integrity_verified") val integrityVerified: Boolean = false,
)

@Serializable
data class DownloadRequest(
    val repository: String,
    val filename: String,
    val revision: String,
    @SerialName("expected_size") val expectedSize: Long,
    val confirmed: Boolean = true,
)

@Serializable
data class DiagnosticJob(
    val id: String,
    val state: String,
    @SerialName("error_code") val errorCode: String? = null,
)

@Serializable
data class Diagnostics(@SerialName("generations") val jobs: List<DiagnosticJob> = emptyList())

fun Parameters.valid(): Boolean =
    temperature.isFinite() &&
        temperature in 0.0..2.0 &&
        topP.isFinite() &&
        topP > 0 &&
        topP <= 1 &&
        maxTokens in 1..32768 &&
        context in 128..131072 &&
        systemPrompt.length <= 16384
