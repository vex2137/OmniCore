package io.github.vex2137.omnicore

import androidx.lifecycle.ViewModelStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.emitAll
import kotlinx.coroutines.test.*
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

private class MemorySettings : ClientSettings {
    override var url = "http://127.0.0.1:8000"
    override var trustedLan = true
    override var theme = "system"
    override var language = "en-US"
    override var conversationId: String? = "c"
    override var generationId: String? = null
    override var parameters = Parameters()
    private var token = ""

    override fun storeToken(token: String) {
        this.token = token
    }

    override fun readToken() = token
}

private class FakeRepository : OmniRepository {
    var chats = listOf(Conversation("c", "Saved chat", modelId = "m"))
    var history = emptyList<Message>()
    var current = Generation("g", "c", "running", sequence = 1)
    var sent = 0
    var cancelled = 0
    var watched = 0
    var streamFailures = 0
    var offline = false
    var rejected = false
    var throwAfterSubmit = false
    val keys = mutableListOf<String>()
    var parameters: Parameters? = null
    val stream = MutableSharedFlow<Generation>()
    var transfers = emptyList<Download>()

    override suspend fun health(): Health {
        if (offline) throw ApiFailure("connection_error")
        if (rejected) throw ApiFailure("unauthorized")
        return Health("ok", "fixture")
    }

    override suspend fun conversations() = chats

    override suspend fun models() =
        listOf(ModelInfo("m", "GGUF", "llama.cpp"), ModelInfo("m2", "Other", "llama.cpp"))

    override suspend fun engines() = emptyList<EngineDiagnostic>()

    override suspend fun messages(id: String) = history

    override suspend fun create(
        title: String,
        model: String?,
        parameters: Parameters?,
    ): Conversation =
        Conversation("new", title, parameters ?: Parameters(), model).also { chats = chats + it }

    override suspend fun rename(id: String, title: String) {
        chats = chats.map { if (it.id == id) it.copy(title = title) else it }
    }

    override suspend fun selectModel(conversationId: String, modelId: String) {
        chats = chats.map { if (it.id == conversationId) it.copy(modelId = modelId) else it }
    }

    override suspend fun saveParameters(id: String, parameters: Parameters) {
        this.parameters = parameters
        chats = chats.map { if (it.id == id) it.copy(parameters = parameters) else it }
    }

    override suspend fun delete(id: String) {
        chats = chats.filterNot { it.id == id }
    }

    override suspend fun generate(id: String, payload: GenerationRequest): Generation {
        sent++
        keys += payload.requestKey
        if (throwAfterSubmit) throw ApiFailure("connection_error")
        return current
    }

    override suspend fun generation(id: String): Generation {
        if (offline) throw ApiFailure("connection_error")
        return current
    }

    override suspend fun cancel(id: String): Generation {
        cancelled++
        current = current.copy(state = "cancelled", sequence = 100)
        return current
    }

    override suspend fun load(id: String, parameters: Parameters) {
        this.parameters = parameters
    }

    override suspend fun unload(id: String) {}

    override suspend fun removeModel(id: String) {}

    override suspend fun importModel(path: String) {}

    override suspend fun search(query: String) = listOf(HubRepository("owner/repo"))

    override suspend fun files(repository: String) =
        listOf(RemoteFile(repository, "abc", "model.gguf", 123))

    override suspend fun downloads() = transfers

    override suspend fun download(file: RemoteFile): Download =
        Download("d", file, "running").also { transfers = listOf(it) }

    override suspend fun cancelDownload(id: String) =
        transfers.first().copy(state = "cancelled").also { transfers = listOf(it) }

    override suspend fun resumeDownload(id: String) =
        transfers.first().copy(state = "running").also { transfers = listOf(it) }

    override suspend fun diagnostics() = Diagnostics()

    override fun watch(
        id: String,
        snapshot: (Generation) -> Unit,
        failure: (String) -> Unit,
    ): StreamHandle = error("Use Flow")

    override fun snapshots(id: String): Flow<Generation> {
        watched++
        return kotlinx.coroutines.flow.flow {
            if (streamFailures > 0) {
                streamFailures--
                throw ApiFailure("stream_disconnected")
            }
            emitAll(stream)
        }
    }

    override fun close() {}
}

@OptIn(ExperimentalCoroutinesApi::class)
class ViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    private val store = ViewModelStore()
    private val settings = MemorySettings()
    private val repo = FakeRepository()
    private lateinit var vm: OmniViewModel

    @Before
    fun setup() {
        Dispatchers.setMain(dispatcher)
        vm = OmniViewModel(settings, { _, _ -> repo }, dispatcher)
        store.put("vm", vm)
    }

    @After
    fun cleanup() {
        store.clear()
        Dispatchers.resetMain()
    }

    private fun runVmTest(block: suspend TestScope.() -> Unit) =
        runTest(dispatcher) {
            try {
                block()
            } finally {
                store.clear()
            }
        }

    @Test
    fun restoresServerHistoryAndSelectedModel() = runVmTest {
        repo.history = listOf(Message(role = "user", content = "Saved"))
        runCurrent()
        assertTrue(vm.state.value.connected)
        assertEquals("Saved", vm.state.value.messages.single().content)
        assertEquals("m", vm.state.value.selectedModel)
    }

    @Test
    fun backgroundDetachesWithoutCancellingAndResumeRestoresCompletedAnswer() = runVmTest {
        runCurrent()
        vm.draft("Hi")
        vm.send()
        runCurrent()
        vm.pause()
        runCurrent()
        assertEquals(0, repo.cancelled)
        assertEquals("g", settings.generationId)
        repo.current =
            repo.current.copy(state = "completed", content = "Real server answer", sequence = 3)
        repo.history =
            listOf(Message(role = "assistant", content = "Real server answer", generationId = "g"))
        vm.resume()
        runCurrent()
        assertEquals("completed", vm.state.value.generation?.state)
        assertEquals(1, repo.sent)
        assertEquals(0, repo.cancelled)
        assertNull(settings.generationId)
    }

    @Test
    fun explicitStopIsTheOnlyCancelRequest() = runVmTest {
        runCurrent()
        vm.draft("Hi")
        vm.send()
        runCurrent()
        vm.cancel()
        runCurrent()
        assertEquals(1, repo.cancelled)
        assertEquals("cancelled", vm.state.value.generation?.state)
    }

    @Test
    fun streamingReplacesSnapshotsAndRejectsStaleSequence() = runVmTest {
        runCurrent()
        vm.draft("Hi")
        vm.send()
        runCurrent()
        repo.stream.emit(repo.current.copy(content = "Answer", sequence = 4))
        runCurrent()
        repo.stream.emit(repo.current.copy(content = "Stale", sequence = 2))
        runCurrent()
        assertEquals("Answer", vm.state.value.generation?.content)
    }

    @Test
    fun processRecreationFindsActiveServerTaskWithoutResubmittingPrompt() = runVmTest {
        settings.generationId = "g"
        vm.connect()
        runCurrent()
        assertEquals("g", vm.state.value.generation?.id)
        assertTrue(vm.state.value.generating)
        assertEquals(0, repo.sent)
    }

    @Test
    fun openingChatStartedByAnotherClientResumesItsLiveStream() = runVmTest {
        runCurrent()
        repo.history =
            listOf(Message(role = "user", content = "Desktop prompt", generationId = "g"))
        vm.openConversation("c")
        runCurrent()
        assertEquals(1, repo.watched)
        repo.stream.emit(repo.current.copy(content = "Live answer", sequence = 2))
        runCurrent()
        assertEquals("Live answer", vm.state.value.generation?.content)
        assertEquals(0, repo.sent)
        assertEquals(0, repo.cancelled)
    }

    @Test
    fun refreshingSharedChatAttachesOnceAndContinuesReceivingSnapshots() = runVmTest {
        runCurrent()
        repo.history =
            listOf(Message(role = "user", content = "Desktop prompt", generationId = "g"))
        vm.refresh()
        runCurrent()
        vm.refresh()
        runCurrent()
        assertEquals(1, repo.watched)
        repo.stream.emit(repo.current.copy(content = "Another client", sequence = 2))
        runCurrent()
        assertEquals("Another client", vm.state.value.generation?.content)
        assertEquals(0, repo.sent)
    }

    @Test
    fun reconnectAfterOfflineStartupKeepsHistoryAndNeverSendsPrompt() = runVmTest {
        repo.offline = true
        runCurrent()
        assertFalse(vm.state.value.connected)
        repo.offline = false
        advanceTimeBy(3100)
        runCurrent()
        assertTrue(vm.state.value.connected)
        assertEquals(0, repo.sent)
    }

    @Test
    fun streamFailureReconnectsWithoutResubmission() = runVmTest {
        runCurrent()
        repo.streamFailures = 1
        vm.draft("Hi")
        vm.send()
        runCurrent()
        assertTrue(vm.state.value.reconnecting)
        advanceTimeBy(600)
        runCurrent()
        assertTrue(repo.watched >= 2)
        repo.stream.emit(
            repo.current.copy(state = "completed", content = "Recovered", sequence = 9)
        )
        runCurrent()
        assertEquals("Recovered", vm.state.value.generation?.content)
        assertEquals(1, repo.sent)
        assertEquals(0, repo.cancelled)
    }

    @Test
    fun authenticationFailureDoesNotRetryForever() = runVmTest {
        repo.rejected = true
        runCurrent()
        advanceTimeBy(20000)
        runCurrent()
        assertEquals("unauthorized", vm.state.value.error)
        assertFalse(vm.state.value.reconnecting)
    }

    @Test
    fun ambiguousPostRetryUsesTheSameIdempotencyKey() = runVmTest {
        runCurrent()
        vm.draft("Hi")
        repo.throwAfterSubmit = true
        vm.send()
        runCurrent()
        repo.throwAfterSubmit = false
        vm.send()
        runCurrent()
        assertEquals(2, repo.keys.size)
        assertEquals(repo.keys[0], repo.keys[1])
    }

    @Test
    fun parameterEditPreservesGpuAndOtherBackendFields() = runVmTest {
        repo.chats =
            listOf(
                repo.chats
                    .first()
                    .copy(parameters = Parameters(gpuLayers = 12, topK = 77, device = "auto"))
            )
        runCurrent()
        vm.parameters(vm.state.value.parameters.copy(temperature = 1.2))
        runCurrent()
        assertEquals(12, repo.parameters?.gpuLayers)
        assertEquals(77, repo.parameters?.topK)
        assertEquals("auto", repo.parameters?.device)
        vm.parameters(Parameters(temperature = Double.NaN))
        runCurrent()
        assertEquals("invalid_parameters", vm.state.value.error)
    }

    @Test
    fun deletingChatClearsLastAnswerAndPersistentSelection() = runVmTest {
        runCurrent()
        vm.draft("Hi")
        vm.send()
        runCurrent()
        vm.cancel()
        runCurrent()
        vm.delete("c")
        runCurrent()
        assertNull(vm.state.value.generation)
        assertNull(settings.conversationId)
        assertTrue(vm.state.value.messages.isEmpty())
    }

    @Test
    fun selectedModelAndThemeRemainAcrossReconnect() = runVmTest {
        runCurrent()
        vm.selectModel("m2")
        runCurrent()
        vm.setTheme("dark")
        vm.setLanguage("pl-PL")
        vm.connect()
        runCurrent()
        assertEquals("m2", vm.state.value.selectedModel)
        assertEquals("dark", settings.theme)
        assertEquals("pl-PL", settings.language)
    }

    @Test
    fun downloadCancelResumeRemainServerOwned() = runVmTest {
        runCurrent()
        vm.hubFiles("owner/repo")
        runCurrent()
        vm.download(vm.state.value.remoteFiles.single())
        runCurrent()
        vm.pause()
        runCurrent()
        assertEquals("running", repo.transfers.single().state)
        vm.cancelDownload("d")
        runCurrent()
        assertEquals("cancelled", vm.state.value.downloads.single().state)
        vm.resumeDownload("d")
        runCurrent()
        assertEquals("running", vm.state.value.downloads.single().state)
    }

    @Test
    fun lostNetworkReconnectsAndKeepsServerGeneration() = runVmTest {
        runCurrent()
        vm.draft("Hello")
        vm.send()
        runCurrent()
        vm.networkLost()
        runCurrent()
        assertEquals(ConnectionStatus.Connecting, vm.state.value.connectionStatus)
        assertEquals(0, repo.cancelled)
        advanceTimeBy(3100)
        runCurrent()
        assertEquals(ConnectionStatus.Connected, vm.state.value.connectionStatus)
        assertEquals(1, repo.sent)
        assertTrue(repo.watched >= 2)
    }

    @Test
    fun dismissingAuthenticationBannerDoesNotHideStatusOrAutoRetry() = runVmTest {
        repo.rejected = true
        runCurrent()
        vm.dismissError()
        vm.networkAvailable()
        advanceTimeBy(10000)
        runCurrent()
        assertEquals(ConnectionStatus.Unauthorized, vm.state.value.connectionStatus)
        assertFalse(vm.state.value.reconnecting)
    }

    @Test
    fun explicitRetryOfPreviousMessageGetsNewIdempotencyKey() = runVmTest {
        repo.history = listOf(Message(role = "user", content = "Repeat me"))
        runCurrent()
        vm.retryMessage()
        runCurrent()
        assertEquals(1, repo.sent)
        vm.cancel()
        runCurrent()
        vm.retryMessage()
        runCurrent()
        assertEquals(2, repo.sent)
        assertNotEquals(repo.keys[0], repo.keys[1])
    }

    @Test
    fun manualRefreshSynchronizesAnotherClientsConversationWithoutSubmitting() = runVmTest {
        runCurrent()
        repo.chats = repo.chats + Conversation("shared", "Other client", modelId = "m2")
        vm.refresh()
        runCurrent()
        assertTrue(vm.state.value.conversations.any { it.id == "shared" })
        assertEquals(0, repo.sent)
    }
}
