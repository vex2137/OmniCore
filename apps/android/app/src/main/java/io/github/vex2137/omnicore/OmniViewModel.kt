package io.github.vex2137.omnicore

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import java.util.UUID
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

// All durable chat/model data belongs to the backend. This is a transient API projection.
data class UiState(
    val connected: Boolean = false,
    val connecting: Boolean = false,
    val authorizationFailed: Boolean = false,
    val busy: Boolean = false,
    val error: String? = null,
    val url: String = "",
    val trustedLan: Boolean = false,
    val hasToken: Boolean = false,
    val theme: String = "system",
    val language: String = "en-US",
    val conversations: List<Conversation> = emptyList(),
    val models: List<ModelInfo> = emptyList(),
    val engines: List<EngineDiagnostic> = emptyList(),
    val selectedConversation: String? = null,
    val selectedModel: String? = null,
    val messages: List<Message> = emptyList(),
    val generation: Generation? = null,
    val draft: String = "",
    val parameters: Parameters = Parameters(),
    val defaultParameters: Parameters = Parameters(),
    val repositories: List<HubRepository> = emptyList(),
    val remoteFiles: List<RemoteFile> = emptyList(),
    val downloads: List<Download> = emptyList(),
    val health: Health? = null,
    val diagnostics: Diagnostics = Diagnostics(),
    val reconnecting: Boolean = false,
    val connectionTest: String? = null,
    val autoTitle: Boolean = true,
) {
    val connectionStatus: ConnectionStatus
        get() =
            when {
                authorizationFailed -> ConnectionStatus.Unauthorized
                connecting || reconnecting -> ConnectionStatus.Connecting
                connected -> ConnectionStatus.Connected
                else -> ConnectionStatus.Disconnected
            }

    val generating: Boolean
        get() = generation?.terminal == false
}

class OmniViewModel(
    private val settings: ClientSettings,
    private val repository: (String, String) -> OmniRepository = ::OmniApi,
    private val io: kotlinx.coroutines.CoroutineDispatcher = Dispatchers.IO,
) : ViewModel() {
    private val mutable =
        MutableStateFlow(
            UiState(
                url = settings.url,
                trustedLan = settings.trustedLan,
                theme = settings.theme,
                language = settings.language,
                selectedConversation = settings.conversationId,
                parameters = settings.parameters,
                defaultParameters = settings.parameters,
            )
        )
    val state = mutable.asStateFlow()
    private var api: OmniRepository? = null
    private var events: Job? = null
    private var epoch = 0
    private var paused = false
    private var downloadUpdates: Job? = null
    private var recovery: Job? = null
    private var pending: GenerationRequest? = null
    private var pendingConversation: String? = null
    private var parameterRevision = 0L

    init {
        if (settings.url.isNotBlank()) connect()
    }

    private fun error(exception: Exception) {
        if (exception is CancellationException) throw exception
        val code = (exception as? ApiFailure)?.code ?: "invalid_response"
        mutable.update {
            it.copy(
                error = code,
                authorizationFailed = it.authorizationFailed || code == "unauthorized",
                connected = it.connected && code !in setOf("connection_error", "unauthorized"),
            )
        }
    }

    fun dismissError() {
        mutable.update { it.copy(error = null) }
    }

    private fun action(block: suspend (OmniRepository) -> Unit) {
        val service =
            api
                ?: run {
                    mutable.update { it.copy(error = "not_connected") }
                    return
                }
        if (mutable.value.busy) return
        mutable.update { it.copy(busy = true, error = null) }
        viewModelScope.launch {
            try {
                block(service)
            } catch (e: Exception) {
                error(e)
            } finally {
                mutable.update { it.copy(busy = false) }
                if (!mutable.value.connected) scheduleReconnect()
            }
        }
    }

    private fun closeTransport() {
        epoch++
        events?.cancel()
        events = null
        downloadUpdates?.cancel()
        recovery?.cancel()
        api?.close()
        api = null
    }

    fun connect() {
        if (mutable.value.busy) return
        closeTransport()
        mutable.update {
            it.copy(
                busy = true,
                connecting = true,
                authorizationFailed = false,
                connected = false,
                error = null,
                reconnecting = false,
            )
        }
        viewModelScope.launch {
            var candidate: OmniRepository? = null
            try {
                val token = withContext(io) { settings.readToken() }
                val base = ConnectionPolicy.validatedUrl(settings.url, settings.trustedLan)
                val service = repository(base, token)
                candidate = service
                val health = service.health()
                api = service
                candidate = null
                mutable.update {
                    it.copy(
                        url = base,
                        hasToken = token.isNotEmpty(),
                        connected = true,
                        health = health,
                        reconnecting = false,
                    )
                }
                refresh(service)
                recoverGeneration(service)
                if (!paused) {
                    resumeStream(service)
                    pollDownloads(service)
                }
            } catch (e: Exception) {
                candidate?.close()
                closeTransport()
                mutable.update { it.copy(connected = false) }
                error(e)
            } finally {
                mutable.update { it.copy(busy = false) }
                mutable.update { it.copy(connecting = false) }
                if (!mutable.value.connected) scheduleReconnect()
            }
        }
    }

    private fun scheduleReconnect() {
        if (
            paused ||
                settings.url.isBlank() ||
                mutable.value.authorizationFailed ||
                recovery?.isActive == true
        )
            return
        recovery =
            viewModelScope.launch {
                mutable.update { it.copy(reconnecting = true) }
                delay(3000)
                recovery = null
                if (!mutable.value.busy) connect() else scheduleReconnect()
            }
    }

    fun networkLost() {
        if (paused || settings.url.isBlank()) return
        epoch++
        events?.cancel()
        events = null
        mutable.update { it.copy(connected = false, reconnecting = !it.authorizationFailed) }
        if (!mutable.value.busy) scheduleReconnect()
    }

    fun networkAvailable() {
        if (
            !paused &&
                !mutable.value.authorizationFailed &&
                !mutable.value.connected &&
                !mutable.value.busy &&
                settings.url.isNotBlank()
        )
            connect()
    }

    private fun validateConnection(
        raw: String,
        newToken: String,
        clearToken: Boolean,
        trustedLan: Boolean,
    ): String {
        val url = ConnectionPolicy.validatedUrl(raw, trustedLan)
        if (
            settings.url.isNotBlank() &&
                !ConnectionPolicy.sameOrigin(settings.url, url) &&
                newToken.isEmpty() &&
                !clearToken
        )
            throw ApiFailure("token_for_new_host")
        if (
            newToken.isNotEmpty() &&
                (!newToken.matches(Regex("[A-Za-z0-9]{32,}")) || newToken.length > 4096)
        )
            throw ApiFailure("invalid_token")
        return url
    }

    fun testConnection(raw: String, newToken: String, clearToken: Boolean, trustedLan: Boolean) {
        if (mutable.value.busy) return
        mutable.update { it.copy(busy = true, error = null, connectionTest = "testing") }
        viewModelScope.launch {
            var candidate: OmniRepository? = null
            try {
                val url = validateConnection(raw, newToken, clearToken, trustedLan)
                val token =
                    when {
                        newToken.isNotEmpty() -> newToken
                        clearToken -> ""
                        else -> withContext(io) { settings.readToken() }
                    }
                candidate = repository(url, token)
                candidate.health()
                candidate.models() // Verify authenticated versioned API, not just TCP/HTTP.
                mutable.update { it.copy(connectionTest = "passed") }
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                // A rejected candidate must not disconnect the currently active server/chat.
                mutable.update {
                    it.copy(
                        connectionTest = "failed",
                        error = (e as? ApiFailure)?.code ?: "invalid_response",
                    )
                }
            } finally {
                candidate?.close()
                mutable.update { it.copy(busy = false) }
            }
        }
    }

    fun clearConnectionTest() {
        mutable.update { it.copy(connectionTest = null) }
    }

    fun pair(raw: String) {
        if (mutable.value.busy || (mutable.value.generating && mutable.value.connected)) return
        mutable.update { it.copy(busy = true, error = null) }
        viewModelScope.launch {
            try {
                val qr = PairingPolicy.parse(raw)
                val credential = withContext(io) {
                    val candidate = repository(qr.url, "")
                    try { candidate.redeemPairing(qr.code) } finally { candidate.close() }
                }
                if (!credential.token.matches(Regex("[a-f0-9]{64}"))) throw ApiFailure("pairing_invalid")
                withContext(io) {
                    val candidate = repository(qr.url, credential.token)
                    try { if (candidate.health().status != "ok") throw ApiFailure("invalid_response") }
                    finally { candidate.close() }
                }
                mutable.update { it.copy(busy = false) }
                saveConnection(qr.url, credential.token, false, true)
            } catch (e: Exception) {
                mutable.update { it.copy(busy = false) }
                error(e)
            }
        }
    }

    fun autoTitle(enabled: Boolean) = action { service ->
        service.saveHistorySettings(HistorySettings(enabled))
        mutable.update { it.copy(autoTitle = enabled) }
    }

    fun deleteAll(expectedCount: Int) = action { service ->
        service.deleteAll(expectedCount)
        epoch++
        events?.cancel()
        events = null
        settings.conversationId = null
        settings.generationId = null
        pending = null
        pendingConversation = null
        mutable.update {
            it.copy(conversations = emptyList(), selectedConversation = null,
                messages = emptyList(), generation = null, draft = "", parameters = settings.parameters)
        }
        refresh(service)
    }

    fun saveConnection(raw: String, newToken: String, clearToken: Boolean, trustedLan: Boolean) {
        if ((mutable.value.generating && mutable.value.connected) || mutable.value.busy) return
        mutable.update { it.copy(busy = true, error = null) }
        viewModelScope.launch {
            try {
                val url = validateConnection(raw, newToken, clearToken, trustedLan)
                withContext(io) {
                    if (newToken.isNotEmpty() || clearToken) settings.storeToken(newToken)
                    settings.url = url
                    settings.trustedLan = trustedLan
                }
                if (url != mutable.value.url) {
                    settings.conversationId = null
                    settings.generationId = null
                    pending = null
                    pendingConversation = null
                    mutable.update {
                        UiState(
                            url = url,
                            trustedLan = trustedLan,
                            theme = it.theme,
                            language = it.language,
                            defaultParameters = settings.parameters,
                            parameters = settings.parameters,
                        )
                    }
                } else mutable.update { it.copy(url = url, trustedLan = trustedLan, busy = false) }
                connect()
            } catch (e: Exception) {
                mutable.update { it.copy(busy = false) }
                error(e)
            }
        }
    }

    fun setTheme(value: String) {
        if (value !in setOf("system", "light", "dark")) return
        settings.theme = value
        mutable.update { it.copy(theme = value) }
    }

    fun setLanguage(value: String) {
        if (value !in setOf("pl-PL", "en-US")) return
        settings.language = value
        mutable.update { it.copy(language = value) }
    }

    fun parameters(value: Parameters, defaults: Boolean = false) {
        if (!value.valid()) {
            mutable.update { it.copy(error = "invalid_parameters") }
            return
        }
        if (mutable.value.generating || mutable.value.busy) return
        parameterRevision++
        val id = mutable.value.selectedConversation
        if (id == null || defaults) {
            settings.parameters = value
            mutable.update { it.copy(defaultParameters = value, parameters = if (id == null) value else it.parameters) }
        } else
            action { service ->
                service.saveParameters(id, value)
                mutable.update { previous ->
                    if (previous.selectedConversation == id) previous.copy(parameters = value)
                    else previous
                }
                refresh(service)
            }
    }

    fun draft(value: String) {
        if (value.length <= 60000) mutable.update { it.copy(draft = value) }
    }

    fun selectModel(id: String) {
        if (mutable.value.generating || mutable.value.busy) return
        val conversation = mutable.value.selectedConversation
        if (conversation == null) mutable.update { it.copy(selectedModel = id) }
        else
            action { service ->
                service.selectModel(conversation, id)
                mutable.update { previous ->
                    previous.copy(
                        selectedModel = id,
                        conversations =
                            previous.conversations.map {
                                if (it.id == conversation) it.copy(modelId = id) else it
                            },
                    )
                }
            }
    }

    fun refresh() {
        if (!mutable.value.connected) {
            connect()
            return
        }
        action {
            refresh(it)
            recoverGeneration(it)
            resumeStream(it)
        }
    }

    private suspend fun refresh(service: OmniRepository) {
        val revision = parameterRevision
        val selection = mutable.value.selectedConversation
        val conversations = service.conversations()
        val models = service.models()
        val engines = service.engines()
        val downloads = service.downloads()
        val diagnostics = service.diagnostics()
        val historySettings = service.historySettings()
        mutable.update { previous ->
            previous.copy(
                conversations = conversations,
                models = models,
                engines = engines,
                downloads = downloads,
                diagnostics = diagnostics,
                autoTitle = historySettings.autoTitle,
                selectedModel =
                    previous.selectedModel?.takeIf { id -> models.any { it.id == id } }
                        ?: models.firstOrNull()?.id,
            )
        }
        mutable.value.selectedConversation?.let { id ->
            if (conversations.any { it.id == id }) {
                val conversation = conversations.first { it.id == id }
                mutable.update {
                    it.copy(
                        selectedModel = conversation.modelId ?: it.selectedModel,
                        parameters =
                            if (it.selectedConversation == selection && parameterRevision == revision)
                                conversation.parameters
                            else it.parameters,
                    )
                }
                loadMessages(service, id)
            } else {
                settings.conversationId = null
                settings.generationId = null
                mutable.update {
                    it.copy(
                        selectedConversation = null,
                        messages = emptyList(),
                        generation = null,
                        draft = "",
                        parameters = settings.parameters,
                    )
                }
            }
        }
        mutable.value.generation?.takeIf { !it.terminal }?.let { accept(service.generation(it.id)) }
    }

    fun createConversation(title: String) = action { service ->
        val conversation =
            service.create(title.take(256), mutable.value.selectedModel, settings.parameters)
        settings.conversationId = conversation.id
        settings.generationId = null
        mutable.update {
            it.copy(
                conversations = listOf(conversation) + it.conversations,
                selectedConversation = conversation.id,
                messages = emptyList(),
                generation = null,
                draft = "",
                parameters = conversation.parameters,
            )
        }
    }

    fun openConversation(id: String) {
        if (mutable.value.generating || mutable.value.busy) return
        settings.conversationId = id
        settings.generationId = null
        mutable.update { previous ->
            previous.copy(
                selectedConversation = id,
                parameters =
                    previous.conversations.find { it.id == id }?.parameters ?: previous.parameters,
                messages = emptyList(),
                generation = null,
                selectedModel =
                    previous.conversations.find { it.id == id }?.modelId ?: previous.selectedModel,
                draft = "",
            )
        }
        action {
            loadMessages(it, id)
            recoverGeneration(it)
            resumeStream(it)
        }
    }

    private suspend fun loadMessages(service: OmniRepository, id: String) {
        val messages = service.messages(id)
        mutable.update { if (it.selectedConversation == id) it.copy(messages = messages) else it }
    }

    fun rename(id: String, title: String) = action { service ->
        service.rename(id, title.take(256))
        refresh(service)
    }

    fun delete(id: String) = action { service ->
        service.delete(id)
        refresh(service)
    }

    fun retryMessage() {
        val current = mutable.value
        if (!current.connected || current.busy || current.generating) return
        if (current.draft.isBlank()) {
            val previous = current.messages.lastOrNull { it.role == "user" } ?: return
            draft(previous.content)
        }
        send()
    }

    fun send() {
        val state = mutable.value
        if (state.generating || state.busy || state.draft.isBlank()) return
        val conversation =
            state.selectedConversation
                ?: run {
                    mutable.update { it.copy(error = "conversation_required") }
                    return
                }
        val model =
            state.selectedModel
                ?: run {
                    mutable.update { it.copy(error = "model_required") }
                    return
                }
        val parameters = state.parameters.forBackend(state.models.firstOrNull { it.id == model }?.backend)
        val request =
            pending?.takeIf {
                pendingConversation == conversation &&
                    it.content == state.draft &&
                    it.modelId == model &&
                    it.parameters == parameters
            } ?: GenerationRequest(state.draft, UUID.randomUUID().toString(), model, parameters)
        pending = request
        pendingConversation = conversation
        action { service ->
            val record = service.generate(conversation, request)
            pending = null
            pendingConversation = null
            mutable.update { it.copy(draft = "", generation = record) }
            loadMessages(service, conversation)
            settings.generationId = record.id
            if (!paused) watch(service, record)
        }
    }

    private suspend fun recoverGeneration(service: OmniRepository) {
        val id =
            settings.generationId
                ?: mutable.value.messages.lastOrNull { it.generationId != null }?.generationId
                ?: return
        try {
            val record = service.generation(id)
            if (record.conversationId != mutable.value.selectedConversation) return
            val previous = mutable.value.generation
            if (previous?.id == record.id && !acceptSnapshot(previous, record)) return
            mutable.update { it.copy(generation = record) }
            settings.generationId = if (record.terminal) null else record.id
        } catch (e: ApiFailure) {
            if (e.code == "not_found") settings.generationId = null else throw e
        }
    }

    private fun resumeStream(service: OmniRepository) {
        if (!paused && events?.isActive != true) {
            mutable.value.generation?.takeIf { !it.terminal }?.let { watch(service, it) }
        }
    }

    private fun watch(service: OmniRepository, record: Generation) {
        epoch++
        val current = epoch
        events?.cancel()
        if (paused || record.terminal) return
        events =
            viewModelScope.launch {
                var backoff = 500L
                while (
                    isActive &&
                        !paused &&
                        epoch == current &&
                        mutable.value.generation?.terminal == false
                ) {
                    try {
                        service.snapshots(record.id).collect { snapshot ->
                            if (epoch == current && snapshot.id == record.id) {
                                mutable.update {
                                    it.copy(connected = true, reconnecting = false, error = null)
                                }
                                accept(snapshot)
                            }
                        }
                    } catch (e: Exception) {
                        if (e is CancellationException) throw e
                        if ((e as? ApiFailure)?.code == "unauthorized") {
                            error(e)
                            return@launch
                        }
                    }
                    if (epoch != current || mutable.value.generation?.terminal != false) break
                    mutable.update { it.copy(reconnecting = true) }
                    delay(backoff)
                    backoff = (backoff * 2).coerceAtMost(8000)
                    try {
                        val next = service.generation(record.id)
                        if (epoch == current) accept(next)
                    } catch (e: Exception) {
                        error(e)
                        if ((e as? ApiFailure)?.code == "unauthorized") return@launch
                    }
                }
            }
    }

    private fun accept(record: Generation) {
        val previous = mutable.value.generation
        if (previous?.id != record.id || !acceptSnapshot(previous, record)) return
        mutable.update { it.copy(generation = record) }
        settings.generationId = if (record.terminal) null else record.id
        if (record.terminal) {
            epoch++
            events?.cancel()
            events = null
            if (record.errorCode != null) mutable.update { it.copy(error = record.errorCode) }
            api?.let { service ->
                viewModelScope.launch {
                    try {
                        loadMessages(service, record.conversationId)
                    } catch (e: Exception) {
                        error(e)
                    }
                }
            }
        }
    }

    fun cancel() {
        val record = mutable.value.generation?.takeIf { !it.terminal } ?: return
        val service = api ?: return
        viewModelScope.launch {
            try {
                accept(service.cancel(record.id))
            } catch (e: Exception) {
                error(e)
            }
        }
    }

    fun pause() {
        paused = true
        recovery?.cancel()
        downloadUpdates?.cancel()
        epoch++
        events?.cancel()
        events = null
    }

    fun resume() {
        val wasPaused = paused
        paused = false
        if (wasPaused && settings.url.isNotBlank()) connect()
    }

    private suspend fun refreshSharedHistory(service: OmniRepository) {
        val chats = service.conversations()
        val preferences = service.historySettings()
        if (mutable.value.busy) return
        val removed = mutable.value.selectedConversation?.let { id -> chats.none { it.id == id } } == true
        if (removed) {
            epoch++
            events?.cancel()
            events = null
            settings.conversationId = null
            settings.generationId = null
            mutable.update { it.copy(selectedConversation = null, messages = emptyList(),
                generation = null, draft = "", parameters = settings.parameters) }
        }
        mutable.update { it.copy(conversations = chats, autoTitle = preferences.autoTitle) }
    }

    private fun pollDownloads(service: OmniRepository) {
        downloadUpdates?.cancel()
        downloadUpdates =
            viewModelScope.launch {
                while (isActive && !paused) {
                    delay(2000)
                    try {
                        val records = service.downloads()
                        mutable.update { it.copy(downloads = records) }
                        // Shared history includes titles and deletions from Linux.
                        if (!mutable.value.busy) refreshSharedHistory(service)
                    } catch (e: Exception) {
                        if (e is CancellationException) throw e
                        error(e)
                        scheduleReconnect()
                        return@launch
                    }
                }
            }
    }

    fun searchHub(query: String) = action { service ->
        if (query.isBlank() || query.length > 256) throw ApiFailure("invalid_model_source")
        val records = service.search(query.trim())
        mutable.update { it.copy(repositories = records, remoteFiles = emptyList()) }
    }

    fun hubFiles(repository: String) = action { service ->
        val files = service.files(repository.trim())
        mutable.update { it.copy(remoteFiles = files) }
    }

    fun download(file: RemoteFile) = action { service ->
        service.download(file)
        val records = service.downloads()
        mutable.update { it.copy(downloads = records) }
    }

    fun cancelDownload(id: String) = action { service ->
        service.cancelDownload(id)
        val records = service.downloads()
        mutable.update { it.copy(downloads = records) }
    }

    fun resumeDownload(id: String) = action { service ->
        service.resumeDownload(id)
        val records = service.downloads()
        mutable.update { it.copy(downloads = records) }
    }

    fun loadModel(id: String) = action { service ->
        service.load(id, mutable.value.parameters)
        refresh(service)
    }

    fun unloadModel(id: String) = action { service ->
        service.unload(id)
        refresh(service)
    }

    fun removeModel(id: String) = action { service ->
        service.removeModel(id)
        refresh(service)
    }

    fun importModel(path: String) = action { service ->
        service.importModel(path)
        refresh(service)
    }

    override fun onCleared() {
        epoch++
        events?.cancel()
        downloadUpdates?.cancel()
        recovery?.cancel()
        api?.close()
    }
}
