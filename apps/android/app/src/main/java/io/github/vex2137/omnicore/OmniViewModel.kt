package io.github.vex2137.omnicore

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import java.util.UUID
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.sse.EventSource

// All durable chat/model data belongs to the backend. This is a transient API projection.
data class UiState(
    val connected: Boolean = false,
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
) {
    val generating: Boolean
        get() = generation?.terminal == false
}

class OmniViewModel(application: Application) : AndroidViewModel(application) {
    private val settings = SecureSettings(application)
    private val mutable =
        MutableStateFlow(
            UiState(
                url = settings.url,
                trustedLan = settings.trustedLan,
                theme = settings.theme,
                language = settings.language,
            )
        )
    val state = mutable.asStateFlow()
    private var api: OmniApi? = null
    private var events: EventSource? = null
    private var epoch = 0
    private var paused = false
    private var pending: GenerationRequest? = null
    private var pendingConversation: String? = null

    init {
        if (settings.url.isNotBlank()) connect()
    }

    private fun error(exception: Exception) {
        if (exception is CancellationException) throw exception
        val code = (exception as? ApiFailure)?.code ?: "invalid_response"
        mutable.update {
            it.copy(
                error = code,
                connected = it.connected && code !in setOf("connection_error", "unauthorized"),
            )
        }
    }

    fun dismissError() {
        mutable.update { it.copy(error = null) }
    }

    private fun action(block: suspend (OmniApi) -> Unit) {
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
            }
        }
    }

    private fun closeTransport() {
        epoch++
        events?.cancel()
        events = null
        api?.close()
        api = null
    }

    fun connect() {
        if (mutable.value.busy) return
        closeTransport()
        mutable.update { it.copy(busy = true, connected = false, error = null) }
        viewModelScope.launch {
            var candidate: OmniApi? = null
            try {
                val token = withContext(Dispatchers.IO) { settings.readToken() }
                val base = ConnectionPolicy.validatedUrl(settings.url, settings.trustedLan)
                val service = OmniApi(base, token)
                candidate = service
                service.health()
                api = service
                candidate = null
                mutable.update {
                    it.copy(url = base, hasToken = token.isNotEmpty(), connected = true)
                }
                refresh(service)
                mutable.value.generation?.takeIf { !it.terminal }?.let { watch(service, it) }
            } catch (e: Exception) {
                candidate?.close()
                closeTransport()
                mutable.update { it.copy(connected = false) }
                error(e)
            } finally {
                mutable.update { it.copy(busy = false) }
            }
        }
    }

    fun saveConnection(raw: String, newToken: String, clearToken: Boolean, trustedLan: Boolean) {
        if ((mutable.value.generating && mutable.value.connected) || mutable.value.busy) return
        mutable.update { it.copy(busy = true, error = null) }
        viewModelScope.launch {
            try {
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
                withContext(Dispatchers.IO) {
                    if (newToken.isNotEmpty() || clearToken) settings.storeToken(newToken)
                    settings.url = url
                    settings.trustedLan = trustedLan
                }
                if (url != mutable.value.url) {
                    pending = null
                    pendingConversation = null
                    mutable.update {
                        UiState(
                            url = url,
                            trustedLan = trustedLan,
                            theme = it.theme,
                            language = it.language,
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

    fun parameters(value: Parameters) {
        mutable.update { it.copy(parameters = value) }
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

    fun refresh() = action { refresh(it) }

    private suspend fun refresh(service: OmniApi) {
        val conversations = service.conversations()
        val models = service.models()
        val engines = service.engines()
        mutable.update { previous ->
            previous.copy(
                conversations = conversations,
                models = models,
                engines = engines,
                selectedModel =
                    previous.selectedModel?.takeIf { id -> models.any { it.id == id } }
                        ?: models.firstOrNull()?.id,
            )
        }
        mutable.value.selectedConversation?.let { id ->
            if (conversations.any { it.id == id }) loadMessages(service, id)
            else
                mutable.update {
                    it.copy(
                        selectedConversation = null,
                        messages = emptyList(),
                        generation = null,
                        draft = "",
                    )
                }
        }
        mutable.value.generation?.takeIf { !it.terminal }?.let { accept(service.generation(it.id)) }
    }

    fun createConversation(title: String) = action { service ->
        val conversation = service.create(title.take(256), mutable.value.selectedModel)
        mutable.update {
            it.copy(
                conversations = listOf(conversation) + it.conversations,
                selectedConversation = conversation.id,
                messages = emptyList(),
                generation = null,
                draft = "",
            )
        }
    }

    fun openConversation(id: String) {
        if (mutable.value.generating || mutable.value.busy) return
        mutable.update { previous ->
            previous.copy(
                selectedConversation = id,
                messages = emptyList(),
                generation = null,
                selectedModel =
                    previous.conversations.find { it.id == id }?.modelId ?: previous.selectedModel,
                draft = "",
            )
        }
        action { loadMessages(it, id) }
    }

    private suspend fun loadMessages(service: OmniApi, id: String) {
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
        val request =
            pending?.takeIf {
                pendingConversation == conversation &&
                    it.content == state.draft &&
                    it.modelId == model
            } ?: GenerationRequest(state.draft, UUID.randomUUID().toString(), model)
        pending = request
        pendingConversation = conversation
        action { service ->
            val record = service.generate(conversation, request)
            pending = null
            pendingConversation = null
            mutable.update { it.copy(draft = "", generation = record) }
            loadMessages(service, conversation)
            if (paused) {
                accept(service.cancel(record.id))
                return@action
            }
            watch(service, record)
        }
    }

    private fun watch(service: OmniApi, record: Generation) {
        epoch++
        val current = epoch
        events?.cancel()
        if (record.terminal || mutable.value.generation?.terminal == true) return
        events =
            service.watch(
                record.id,
                snapshot = { snapshot ->
                    viewModelScope.launch { if (epoch == current) accept(snapshot) }
                },
                failure = { code ->
                    viewModelScope.launch {
                        if (epoch == current && mutable.value.generation?.terminal == false) {
                            mutable.update { it.copy(error = code) }
                            try {
                                val next = service.generation(record.id)
                                if (epoch == current) accept(next)
                                if (epoch == current && !next.terminal) {
                                    kotlinx.coroutines.delay(500)
                                    val final = service.generation(record.id)
                                    if (epoch == current) accept(final)
                                }
                            } catch (e: Exception) {
                                if (epoch == current) error(e)
                            }
                        }
                    }
                },
            )
    }

    private fun accept(record: Generation) {
        val previous = mutable.value.generation
        if (previous?.id != record.id || !acceptSnapshot(previous, record)) return
        mutable.update { it.copy(generation = record) }
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
        cancel()
        epoch++
        events?.cancel()
        events = null
    }

    fun resume() {
        paused = false
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
        api?.close()
    }
}
