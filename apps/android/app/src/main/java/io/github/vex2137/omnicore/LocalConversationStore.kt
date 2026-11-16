package io.github.vex2137.omnicore

import java.io.File
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.util.UUID
import kotlinx.serialization.Serializable

@Serializable
private data class StoredConversationEntry(
    val conversation: Conversation,
    val messages: List<Message> = emptyList(),
)

/** Atomic JSON persistence for offline on-device conversations and history. */
class LocalConversationStore(private val rootDir: File) {
    private val file = File(rootDir, "omnicore-local-conversations.json")
    private val lock = Any()

    fun list(): List<Conversation> = synchronized(lock) { load().map { it.conversation } }

    fun messages(conversationId: String): List<Message> =
        synchronized(lock) {
            load().firstOrNull { it.conversation.id == conversationId }?.messages ?: emptyList()
        }

    fun get(conversationId: String): Conversation? =
        synchronized(lock) {
            load().firstOrNull { it.conversation.id == conversationId }?.conversation
        }

    fun create(title: String, modelId: String?, parameters: Parameters?): Conversation =
        synchronized(lock) {
            val conv =
                Conversation(
                    id = UUID.randomUUID().toString().replace("-", ""),
                    title = title,
                    parameters = parameters ?: Parameters(),
                    modelId = modelId,
                )
            val entries = listOf(StoredConversationEntry(conv, emptyList())) + load()
            save(entries)
            conv
        }

    fun rename(id: String, title: String) =
        synchronized(lock) {
            update(id) { it.copy(conversation = it.conversation.copy(title = title)) }
        }

    fun selectModel(id: String, modelId: String) =
        synchronized(lock) {
            update(id) { it.copy(conversation = it.conversation.copy(modelId = modelId)) }
        }

    fun saveParameters(id: String, parameters: Parameters) =
        synchronized(lock) {
            update(id) { it.copy(conversation = it.conversation.copy(parameters = parameters)) }
        }

    fun appendMessage(conversationId: String, message: Message) =
        synchronized(lock) {
            update(conversationId) { it.copy(messages = it.messages + message) }
        }

    fun delete(id: String) =
        synchronized(lock) { save(load().filterNot { it.conversation.id == id }) }

    private fun update(
        id: String,
        transform: (StoredConversationEntry) -> StoredConversationEntry,
    ) {
        val items = load()
        val idx = items.indexOfFirst { it.conversation.id == id }
        if (idx < 0) throw ApiFailure("not_found")
        val next = items.toMutableList()
        next[idx] = transform(next[idx])
        save(next)
    }

    private fun load(): List<StoredConversationEntry> {
        if (!file.isFile) return emptyList()
        return runCatching {
            WireJson.decodeFromString<List<StoredConversationEntry>>(file.readText())
        }.getOrElse { emptyList() }
    }

    private fun save(entries: List<StoredConversationEntry>) {
        rootDir.mkdirs()
        val tmp = File(rootDir, "omnicore-local-conversations.json.tmp")
        tmp.writeText(WireJson.encodeToString(entries))
        Files.move(
            tmp.toPath(),
            file.toPath(),
            StandardCopyOption.REPLACE_EXISTING,
            StandardCopyOption.ATOMIC_MOVE,
        )
    }
}
