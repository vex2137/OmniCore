package io.github.vex2137.omnicore

import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.sse.EventSource
import okhttp3.sse.EventSourceListener
import okhttp3.sse.EventSources

/** No inference, model-file access or database logic. Only the public versioned API. */
class OmniApi(private val base: String, private val token: String) {
    private val client =
        OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(45, TimeUnit.SECONDS)
            .writeTimeout(30, TimeUnit.SECONDS)
            .followRedirects(false)
            .followSslRedirects(false)
            .build()

    private fun request(path: String): Request.Builder =
        Request.Builder().url(base + path).apply {
            if (token.isNotEmpty()) header("Authorization", "Bearer $token")
        }

    internal suspend fun exchange(method: String, path: String, json: String? = null): String =
        withContext(Dispatchers.IO) {
            val body =
                if (method in setOf("POST", "PUT", "PATCH", "DELETE"))
                    (json ?: "{}").toRequestBody("application/json".toMediaType())
                else null
            val call = client.newCall(request(path).method(method, body).build())
            val context = kotlin.coroutines.coroutineContext
            val completion =
                context[kotlinx.coroutines.Job]?.invokeOnCompletion {
                    if (it != null) call.cancel()
                }
            try {
                call.execute().use { response ->
                    if (!response.isSuccessful) throw ApiFailure(errorCode(response))
                    val bytes = java.io.ByteArrayOutputStream()
                    response.body?.byteStream()?.use { stream ->
                        val buffer = ByteArray(8192)
                        while (true) {
                            val count = stream.read(buffer)
                            if (count < 0) break
                            if (bytes.size() + count > 2_000_000)
                                throw ApiFailure("response_too_large")
                            bytes.write(buffer, 0, count)
                        }
                    }
                    bytes.toString("UTF-8")
                }
            } catch (e: ApiFailure) {
                throw e
            } catch (_: IOException) {
                throw ApiFailure("connection_error")
            } finally {
                completion?.dispose()
            }
        }

    private fun errorCode(response: Response): String {
        if (response.code == 401 || response.code == 403) return "unauthorized"
        return try {
            val body = response.peekBody(65536).string()
            val code =
                WireJson.parseToJsonElement(body)
                    .jsonObject["error"]
                    ?.jsonObject
                    ?.get("code")
                    ?.jsonPrimitive
                    ?.content ?: "api_error"
            if (code.matches(Regex("[a-z_]{1,80}"))) code else "api_error"
        } catch (_: Exception) {
            "api_error"
        }
    }

    suspend fun health() {
        exchange("GET", "/api/v1/health")
    }

    suspend fun conversations(): List<Conversation> =
        WireJson.decodeFromString(exchange("GET", "/api/v1/text/conversations"))

    suspend fun models(): List<ModelInfo> =
        WireJson.decodeFromString(exchange("GET", "/api/v1/text/models"))

    suspend fun engines(): List<EngineDiagnostic> =
        WireJson.decodeFromString(exchange("GET", "/api/v1/text/engines"))

    suspend fun messages(id: String): List<Message> =
        WireJson.decodeFromString(exchange("GET", "/api/v1/text/conversations/$id/messages"))

    suspend fun create(title: String, model: String?): Conversation =
        WireJson.decodeFromString(
            exchange(
                "POST",
                "/api/v1/text/conversations",
                WireJson.encodeToString(CreateConversation(title, model)),
            )
        )

    suspend fun rename(id: String, title: String) {
        exchange(
            "PATCH",
            "/api/v1/text/conversations/$id",
            WireJson.encodeToString(RenameConversation(title)),
        )
    }

    suspend fun delete(id: String) {
        exchange("DELETE", "/api/v1/text/conversations/$id")
    }

    suspend fun generate(id: String, payload: GenerationRequest): Generation =
        WireJson.decodeFromString(
            exchange(
                "POST",
                "/api/v1/text/conversations/$id/generations",
                WireJson.encodeToString(payload),
            )
        )

    suspend fun generation(id: String): Generation =
        WireJson.decodeFromString(exchange("GET", "/api/v1/text/generations/$id"))

    suspend fun cancel(id: String): Generation =
        WireJson.decodeFromString(exchange("POST", "/api/v1/text/generations/$id/cancel"))

    suspend fun load(id: String, parameters: Parameters) {
        exchange("POST", "/api/v1/text/models/$id/load", WireJson.encodeToString(parameters))
    }

    suspend fun unload(id: String) {
        exchange("POST", "/api/v1/text/models/$id/unload")
    }

    suspend fun removeModel(id: String) {
        exchange("DELETE", "/api/v1/text/models/$id", WireJson.encodeToString(ModelDelete()))
    }

    suspend fun importModel(path: String) {
        exchange("POST", "/api/v1/text/models/import", WireJson.encodeToString(ModelImport(path)))
    }

    fun watch(id: String, snapshot: (Generation) -> Unit, failure: (String) -> Unit): EventSource {
        return EventSources.createFactory(client)
            .newEventSource(
                request("/api/v1/text/generations/$id/stream").build(),
                object : EventSourceListener() {
                    override fun onEvent(
                        eventSource: EventSource,
                        id: String?,
                        type: String?,
                        data: String,
                    ) {
                        if (data.length > 2_000_000) {
                            eventSource.cancel()
                            failure("response_too_large")
                            return
                        }
                        try {
                            snapshot(WireJson.decodeFromString(data))
                        } catch (_: Exception) {
                            eventSource.cancel()
                            failure("invalid_response")
                        }
                    }

                    override fun onClosed(eventSource: EventSource) {
                        failure("stream_disconnected")
                    }

                    override fun onFailure(
                        eventSource: EventSource,
                        t: Throwable?,
                        response: Response?,
                    ) {
                        failure(
                            if (response != null) errorCode(response) else "stream_disconnected"
                        )
                    }
                },
            )
    }

    fun close() {
        client.dispatcher.cancelAll()
        client.connectionPool.evictAll()
    }
}
