package io.github.vex2137.omnicore

import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow

fun interface StreamHandle {
    fun cancel()
}

/** Replaceable data boundary: future on-device engines need not change Compose screens. */
interface OmniRepository {
    suspend fun health(): Health

    suspend fun conversations(): List<Conversation>

    suspend fun models(): List<ModelInfo>

    suspend fun engines(): List<EngineDiagnostic>

    suspend fun messages(id: String): List<Message>

    suspend fun create(title: String, model: String?, parameters: Parameters? = null): Conversation

    suspend fun rename(id: String, title: String)

    suspend fun selectModel(conversationId: String, modelId: String)

    suspend fun saveParameters(id: String, parameters: Parameters)

    suspend fun delete(id: String)

    suspend fun historySettings(): HistorySettings = HistorySettings()

    suspend fun saveHistorySettings(value: HistorySettings) { throw ApiFailure("unsupported") }

    suspend fun deleteAll(expectedCount: Int) { throw ApiFailure("unsupported") }

    suspend fun redeemPairing(code: String): PairingCredential { throw ApiFailure("unsupported") }

    suspend fun redeemPairing(code: String, nonce: String): PairingCredential = redeemPairing(code)

    suspend fun providers(): List<ProviderInfo> = emptyList()
    suspend fun saveProvider(id: String?, value: ProviderInput): ProviderInfo { throw ApiFailure("unsupported") }
    suspend fun deleteProvider(id: String) { throw ApiFailure("unsupported") }
    suspend fun providerModels(id: String): List<String> { throw ApiFailure("unsupported") }
    suspend fun testProvider(id: String) { throw ApiFailure("unsupported") }
    suspend fun addProviderModel(id: String, model: String) { throw ApiFailure("unsupported") }

    suspend fun generate(id: String, payload: GenerationRequest): Generation

    suspend fun generation(id: String): Generation

    suspend fun cancel(id: String): Generation

    suspend fun load(id: String, parameters: Parameters)

    suspend fun unload(id: String)

    suspend fun removeModel(id: String)

    suspend fun importModel(path: String)

    suspend fun search(query: String): List<HubRepository>

    suspend fun files(repository: String): List<RemoteFile>

    suspend fun downloads(): List<Download>

    suspend fun download(file: RemoteFile): Download

    suspend fun cancelDownload(id: String): Download

    suspend fun resumeDownload(id: String): Download

    suspend fun diagnostics(): Diagnostics

    fun watch(id: String, snapshot: (Generation) -> Unit, failure: (String) -> Unit): StreamHandle

    fun close()

    fun snapshots(id: String): Flow<Generation> = callbackFlow {
        val source =
            watch(
                id,
                { if (!trySend(it).isSuccess) close(ApiFailure("stream_disconnected")) },
                { close(ApiFailure(it)) },
            )
        awaitClose { source.cancel() }
    }
}

interface ClientSettings {
    var url: String
    var trustedLan: Boolean
    var theme: String
    var language: String
    var conversationId: String?
    var generationId: String?
    var parameters: Parameters

    fun readPendingPairing(): String?
    fun storePendingPairing(value: String?)
    fun hasPendingPairing(): Boolean
    fun commitConnection(newUrl: String, newToken: String?, trusted: Boolean) {
        if (newToken != null) storeToken(newToken)
        url = newUrl
        trustedLan = trusted
    }

    fun storeToken(token: String)

    fun readToken(): String
}
