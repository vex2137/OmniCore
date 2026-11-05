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
    var failSecretWrite = false
    var pairing: String? = null
    override fun readPendingPairing() = pairing
    override fun storePendingPairing(value: String?) { if (failSecretWrite) throw ApiFailure("token_unavailable"); pairing = value }
    override fun hasPendingPairing() = pairing != null

    override fun storeToken(token: String) {
        this.token = token
    }

    override fun readToken() = token
}

private class FakeRepository : OmniRepository {
    var chats = listOf(Conversation("c", "Saved chat", modelId = "m"))
    var history = emptyList<Message>()
    var current = Generation("g", "c", "running", sequence = 1)
    var lastRequest: GenerationRequest? = null
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
    var healthCalls = 0
    var pairCalls = 0
    var firstNonce: String? = null
    var pairError: String? = null
    var pairResponseLoss = false
    var pairHealthFailures = 0
    var historySettings = HistorySettings()
    var deletedAll = 0

    override suspend fun health(): Health {
        healthCalls++
        if (pairCalls > 0 && pairHealthFailures > 0) { pairHealthFailures--; throw ApiFailure("connection_error") }
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

    override suspend fun redeemPairing(code: String, nonce: String): PairingCredential {
        pairCalls++
        pairError?.let { throw ApiFailure(it) }
        if (firstNonce == null) firstNonce = nonce
        if (firstNonce != nonce) throw ApiFailure("pairing_used")
        if (pairResponseLoss && pairCalls == 1) throw ApiFailure("connection_error")
        return PairingCredential("phone", PairingPolicy.credential(code, nonce))
    }

    override suspend fun historySettings() = historySettings

    override suspend fun saveHistorySettings(value: HistorySettings) { historySettings = value }

    override suspend fun deleteAll(expectedCount: Int) {
        if (expectedCount != chats.size) throw ApiFailure("history_changed")
        deletedAll++
        chats = emptyList()
        history = emptyList()
        current = current.copy(state = "cancelled")
    }

    override suspend fun generate(id: String, payload: GenerationRequest): Generation {
        sent++
        lastRequest = payload
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
        assertFalse(vm.state.value.connected)
        advanceTimeBy(2600)
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
    fun connectionTestDoesNotSaveCandidateOrReplaceActiveChat() = runVmTest {
        runCurrent()
        vm.draft("Hi")
        vm.send()
        runCurrent()
        val current = vm.state.value.generation
        val originalUrl = settings.url
        vm.testConnection("https://other.example", "a".repeat(48), false, false)
        runCurrent()
        assertEquals("passed", vm.state.value.connectionTest)
        assertEquals(originalUrl, settings.url)
        assertEquals("", settings.readToken())
        assertEquals(current, vm.state.value.generation)
        assertTrue(vm.state.value.connected)
        assertEquals(0, repo.cancelled)
    }

    @Test
    fun rejectedCandidateDoesNotInvalidateTheActiveConnection() = runVmTest {
        runCurrent()
        repo.rejected = true
        vm.testConnection(settings.url, "", false, true)
        runCurrent()
        assertEquals("failed", vm.state.value.connectionTest)
        assertEquals("unauthorized", vm.state.value.error)
        assertTrue(vm.state.value.connected)
        assertFalse(vm.state.value.authorizationFailed)
    }

    @Test
    fun connectionTestCannotForwardStoredTokenToANewOrigin() = runVmTest {
        runCurrent()
        settings.storeToken("a".repeat(48))
        vm.testConnection("https://other.example", "", false, false)
        runCurrent()
        assertEquals("token_for_new_host", vm.state.value.error)
        assertEquals("failed", vm.state.value.connectionTest)
        assertTrue(vm.state.value.connected)
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
    fun cudaSaveRefreshSendReopenAndRecreationPreserveConversationParameters() = runVmTest {
        runCurrent()
        val defaults = settings.parameters
        val gpu = Parameters(device = "cuda", gpuLayers = 23)
        vm.parameters(gpu)
        runCurrent()
        vm.refresh()
        runCurrent()
        assertEquals(gpu, vm.state.value.parameters)
        assertEquals(defaults, settings.parameters)
        vm.selectModel("m2")
        runCurrent()
        vm.draft("GPU prompt")
        vm.send()
        runCurrent()
        assertEquals(gpu, repo.lastRequest?.parameters)
        vm.cancel()
        runCurrent()
        vm.openConversation("c")
        runCurrent()
        assertEquals(gpu, vm.state.value.parameters)
        store.clear()
        val restored = OmniViewModel(settings, { _, _ -> repo }, dispatcher)
        store.put("restored", restored)
        runCurrent()
        assertEquals(gpu, restored.state.value.parameters)
    }

    @Test
    fun newConversationsUseDefaultsInsteadOfLastEditedConversation() = runVmTest {
        runCurrent()
        settings.parameters = Parameters(device = "auto", gpuLayers = 99)
        vm.parameters(Parameters(device = "cuda", gpuLayers = 17))
        runCurrent()
        vm.createConversation("")
        runCurrent()
        assertEquals(settings.parameters, vm.state.value.parameters)
        assertEquals("cuda", repo.chats.first { it.id == "c" }.parameters.device)
    }

    @Test
    fun sendCannotRaceAnUnfinishedParameterSave() = runVmTest {
        runCurrent()
        vm.parameters(Parameters(device = "auto", gpuLayers = 99))
        vm.draft("Wait for save")
        vm.send()
        assertEquals(0, repo.sent)
        runCurrent()
        vm.send()
        runCurrent()
        assertEquals("auto", repo.lastRequest?.parameters?.device)
        assertEquals(99, repo.lastRequest?.parameters?.gpuLayers)
    }

    @Test
    fun editingDefaultsDoesNotChangeAnExistingConversation() = runVmTest {
        runCurrent()
        val conversation = vm.state.value.parameters
        val defaults = Parameters(device = "auto", gpuLayers = 99)
        vm.parameters(defaults, defaults = true)
        runCurrent()
        assertEquals(conversation, vm.state.value.parameters)
        assertEquals(defaults, settings.parameters)
        vm.createConversation("")
        runCurrent()
        assertEquals(defaults, vm.state.value.parameters)
    }

    @Test
    fun bulkDeletionClearsActiveStateAndSynchronizesSharedHistory() = runVmTest {
        runCurrent()
        vm.draft("Hi")
        vm.send()
        runCurrent()
        vm.deleteAll(1)
        runCurrent()
        assertEquals(1, repo.deletedAll)
        assertFalse(vm.state.value.generating)
        assertNull(settings.conversationId)
        assertNull(settings.generationId)
        assertTrue(vm.state.value.messages.isEmpty())
        assertTrue(vm.state.value.conversations.isEmpty())
    }

    @Test
    fun historySettingsAreSharedAndRefreshedFromBackend() = runVmTest {
        runCurrent()
        vm.autoTitle(false)
        runCurrent()
        assertFalse(repo.historySettings.autoTitle)
        repo.historySettings = HistorySettings(true)
        vm.refresh()
        runCurrent()
        assertTrue(vm.state.value.autoTitle)
    }

    private fun pairingQr() = WireJson.encodeToString(PairingQr.serializer(),
        PairingQr(1, "http://192.168.1.12:8000", "c".repeat(64), System.currentTimeMillis() / 1000.0 + 120))

    @Test
    fun pairingSucceedsFirstTimeAndDeduplicatesRepeatedCallbacks() = runVmTest {
        runCurrent()
        val qr = pairingQr()
        vm.pair(qr)
        vm.pair(qr)
        runCurrent()
        assertEquals(1, repo.pairCalls)
        assertEquals(PairingPolicy.credential("c".repeat(64), repo.firstNonce!!), settings.readToken())
        assertEquals("http://192.168.1.12:8000", settings.url)
        assertNull(settings.pairing)
        assertTrue(vm.state.value.connected)
    }

    @Test
    fun lostRedemptionResponseRetriesTheSameNonceAndDoesNotCreateAnotherIdentity() = runVmTest {
        runCurrent()
        repo.pairResponseLoss = true
        vm.pair(pairingQr())
        runCurrent()
        val nonce = repo.firstNonce
        assertNotNull(settings.pairing)
        advanceTimeBy(501)
        runCurrent()
        assertEquals(2, repo.pairCalls)
        assertEquals(nonce, repo.firstNonce)
        assertNull(settings.pairing)
        assertEquals(PairingPolicy.credential("c".repeat(64), repo.firstNonce!!), settings.readToken())
    }

    @Test
    fun failedHealthKeepsOriginalConnectionAndPendingPairingCanResume() = runVmTest {
        runCurrent()
        val old = settings.url
        repo.pairHealthFailures = 1
        vm.pair(pairingQr())
        runCurrent()
        assertEquals(old, settings.url)
        assertTrue(vm.state.value.pairingPending)
        val nonce = repo.firstNonce
        vm.retryPairing()
        runCurrent()
        assertEquals(nonce, repo.firstNonce)
        assertEquals(1, repo.pairCalls) // Recovery authenticates the issued credential, without consuming a new code.
        assertEquals("http://192.168.1.12:8000", settings.url)
        assertNull(settings.pairing)
    }

    @Test
    fun pairingFailuresKeepTheExistingAuthenticatedConnection() = runVmTest {
        runCurrent()
        assertTrue(vm.state.value.connected)
        for (code in listOf("pairing_expired", "pairing_used", "connection_error")) {
            repo.pairError = code
            vm.pair(pairingQr())
            if (code == "connection_error") advanceTimeBy(1600)
            runCurrent()
            assertTrue(vm.state.value.connected)
            assertFalse(vm.state.value.authorizationFailed)
            assertEquals(code, vm.state.value.error)
        }
    }

    @Test
    fun failedKeystoreWriteDoesNotConsumeTheCode() = runVmTest {
        runCurrent()
        settings.failSecretWrite = true
        vm.pair(pairingQr())
        runCurrent()
        assertEquals(0, repo.pairCalls)
        assertEquals("token_unavailable", vm.state.value.error)
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
        assertEquals(ConnectionStatus.Disconnected, vm.state.value.connectionStatus)
        assertEquals(0, repo.cancelled)
        advanceTimeBy(3100)
        assertFalse(vm.state.value.connected)
        vm.networkAvailable()
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
    fun offlineBackoffIsBoundedAndNetworkLossSuspendsAllRetries() = runVmTest {
        repo.offline = true
        runCurrent()
        advanceTimeBy(300_000)
        runCurrent()
        assertTrue(repo.healthCalls in 7..12)
        val before = repo.healthCalls
        vm.networkLost()
        advanceTimeBy(300_000)
        runCurrent()
        assertEquals(before, repo.healthCalls)
        repo.offline = false
        vm.networkAvailable()
        runCurrent()
        assertTrue(vm.state.value.connected)
        assertEquals(before + 1, repo.healthCalls)
    }

    @Test
    fun revokedTokenRemainsStoppedAcrossBackgroundAndNetworkChangesUntilManualRetry() = runVmTest {
        repo.rejected = true
        runCurrent()
        val before = repo.healthCalls
        vm.pause(); vm.networkLost(); vm.networkAvailable(); vm.resume()
        advanceTimeBy(180_000)
        runCurrent()
        assertEquals(before, repo.healthCalls)
        assertEquals(ConnectionStatus.Unauthorized, vm.state.value.connectionStatus)
        repo.rejected = false
        vm.connect()
        runCurrent()
        assertTrue(vm.state.value.connected)
        assertEquals(before + 1, repo.healthCalls)
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
