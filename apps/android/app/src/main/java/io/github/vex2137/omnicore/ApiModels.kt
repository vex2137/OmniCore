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
    @SerialName("model_id") val modelId: String? = null,
)

@Serializable
data class Message(
    val id: String = "",
    val role: String,
    val content: String,
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
) {
    val terminal: Boolean
        get() = state in setOf("completed", "cancelled", "failed", "interrupted")
}

@Serializable
data class CreateConversation(
    val title: String,
    @SerialName("model_id") val modelId: String? = null,
)

@Serializable data class RenameConversation(val title: String)

@Serializable
data class GenerationRequest(
    val content: String,
    @SerialName("request_key") val requestKey: String,
    @SerialName("model_id") val modelId: String,
    val parameters: Parameters,
)

@Serializable data class ModelImport(val path: String)

@Serializable data class ModelDelete(@SerialName("delete_file") val deleteFile: Boolean = false)

fun acceptSnapshot(previous: Generation?, next: Generation): Boolean =
    previous == null || previous.id != next.id || next.sequence >= previous.sequence
