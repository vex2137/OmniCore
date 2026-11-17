package io.github.vex2137.omnicore

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.OpenableColumns
import java.io.DataInputStream
import java.io.File
import java.io.FileNotFoundException
import java.io.FileOutputStream
import java.io.InputStream
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.util.UUID
import kotlinx.serialization.Serializable

@Serializable
data class LocalModelRecord(
    val id: String,
    val name: String,
    val path: String,
    val uri: String? = null,
    val sizeBytes: Long,
    val quantization: String? = null,
    val architecture: String? = null,
    val contextLength: Int? = null,
    val hasTokenizer: Boolean = true,
    val managedFile: Boolean = false,
)

/**
 * Manages on-device GGUF models with bounded GGUF metadata/completeness validation,
 * SAF URI permission persistence, cleanup of failed imports, and zero duplicate copies.
 */
class LocalModelStore(private val rootDir: File) {
    private val modelsDir = File(rootDir, "omnicore-models").apply { mkdirs() }
    private val catalogFile = File(rootDir, "omnicore-local-models.json")
    private val lock = Any()

    init {
        // Clean up leftover partial files from interrupted imports without touching registered models.
        modelsDir.listFiles { f -> f.name.endsWith(".gguf.partial") }?.forEach { it.delete() }
    }

    fun list(): List<LocalModelRecord> = synchronized(lock) { loadAndEnrichCatalog() }

    fun find(id: String): LocalModelRecord? =
        synchronized(lock) { loadAndEnrichCatalog().firstOrNull { it.id == id } }

    fun fileFor(id: String): File? = find(id)?.let { File(it.path) }

    fun importLocalFile(source: File, displayName: String? = null): LocalModelRecord {
        if (!source.isFile || !source.canRead()) throw ApiFailure("model_not_found")
        val meta = GgufReader.inspect(source)
        val name =
            (displayName ?: source.nameWithoutExtension)
                .removeSuffix(".gguf")
                .removeSuffix(".GGUF")
                .ifBlank { meta.name.ifBlank { source.nameWithoutExtension } }
        val record =
            LocalModelRecord(
                id = UUID.randomUUID().toString().replace("-", ""),
                name = name,
                path = source.absolutePath,
                uri = null,
                sizeBytes = source.length(),
                quantization = inferQuantization(source.name) ?: meta.quantization,
                architecture = meta.architecture,
                contextLength = meta.contextLength,
                hasTokenizer = meta.hasTokenizer,
                managedFile = false,
            )
        synchronized(lock) {
            val existing = loadCatalog().filterNot { it.path == record.path }
            saveCatalog(existing + record)
        }
        return record
    }

    fun importContentUri(
        context: Context,
        uri: Uri,
        onProgress: (Float, String) -> Unit = { _, _ -> },
    ): LocalModelRecord {
        runCatching {
            context.contentResolver.takePersistableUriPermission(
                uri,
                Intent.FLAG_GRANT_READ_URI_PERMISSION,
            )
        }
        val (displayName, reportedSize) = queryUriMeta(context, uri)
        val fallbackName = uri.lastPathSegment?.substringAfterLast(':')?.substringAfterLast('/')
        val cleanName =
            (displayName ?: fallbackName ?: "model.gguf")
                .substringAfterLast('/')
                .ifBlank { "model.gguf" }
        val baseName = cleanName.removeSuffix(".gguf").removeSuffix(".GGUF").ifBlank { "Model" }

        synchronized(lock) {
            loadAndEnrichCatalog()
                .firstOrNull { it.uri == uri.toString() && File(it.path).isFile }
                ?.let { return it }
        }

        if (reportedSize > 0 && modelsDir.usableSpace < reportedSize + 64L * 1024L * 1024L) {
            throw ApiFailure("insufficient_storage")
        }

        val id = UUID.randomUUID().toString().replace("-", "")
        val part = File(modelsDir, "$id.gguf.partial")
        val target = File(modelsDir, "$id.gguf")
        onProgress(0f, baseName)
        try {
            val stream =
                try {
                    context.contentResolver.openInputStream(uri)
                } catch (_: SecurityException) {
                    throw ApiFailure("model_permission_denied")
                } catch (_: FileNotFoundException) {
                    throw ApiFailure("model_not_found")
                } ?: throw ApiFailure("model_not_found")

            stream.use { input ->
                val header = ByteArray(8)
                DataInputStream(input).let { data ->
                    try {
                        data.readFully(header)
                    } catch (_: Exception) {
                        throw ApiFailure("invalid_gguf")
                    }
                }
                GgufReader.validateMagicHeader(header)
                var copied = 8L
                var lastPct = -1
                FileOutputStream(part).use { out ->
                    out.write(header)
                    val buf = ByteArray(1024 * 1024)
                    while (true) {
                        val n = input.read(buf)
                        if (n == -1) break
                        out.write(buf, 0, n)
                        copied += n
                        if (reportedSize > 0) {
                            val progress = (copied.toDouble() / reportedSize).toFloat().coerceIn(0f, 0.99f)
                            val pct = (progress * 100).toInt()
                            if (pct != lastPct) {
                                lastPct = pct
                                onProgress(progress, baseName)
                            }
                        }
                    }
                    out.fd.sync()
                }
            }
            val meta = GgufReader.inspect(part)
            try {
                Files.move(
                    part.toPath(),
                    target.toPath(),
                    StandardCopyOption.REPLACE_EXISTING,
                    StandardCopyOption.ATOMIC_MOVE,
                )
            } catch (_: UnsupportedOperationException) {
                Files.move(part.toPath(), target.toPath(), StandardCopyOption.REPLACE_EXISTING)
            }
            onProgress(1f, baseName)
            val record =
                LocalModelRecord(
                    id = id,
                    name = baseName,
                    path = target.absolutePath,
                    uri = uri.toString(),
                    sizeBytes = target.length(),
                    quantization = inferQuantization(cleanName) ?: meta.quantization,
                    architecture = meta.architecture,
                    contextLength = meta.contextLength,
                    hasTokenizer = meta.hasTokenizer,
                    managedFile = true,
                )
            synchronized(lock) { saveCatalog(loadCatalog() + record) }
            return record
        } catch (e: Exception) {
            part.delete()
            target.delete()
            if (e is ApiFailure) throw e
            if (e is SecurityException) throw ApiFailure("model_permission_denied")
            if (e is FileNotFoundException) throw ApiFailure("model_not_found")
            throw ApiFailure("model_import_failed")
        }
    }

    fun remove(context: Context?, id: String) {
        val removed =
            synchronized(lock) {
                val items = loadCatalog()
                val target = items.firstOrNull { it.id == id } ?: return
                saveCatalog(items.filterNot { it.id == id })
                target
            }
        if (removed.managedFile) {
            File(removed.path).delete()
        }
        if (context != null && removed.uri != null) {
            runCatching {
                context.contentResolver.releasePersistableUriPermission(
                    Uri.parse(removed.uri),
                    Intent.FLAG_GRANT_READ_URI_PERMISSION,
                )
            }
        }
    }

    private fun queryUriMeta(context: Context, uri: Uri): Pair<String?, Long> {
        if ("file".equals(uri.scheme, ignoreCase = true)) {
            val f = uri.path?.let { File(it) }
            return f?.name to (f?.length() ?: -1L)
        }
        var name: String? = null
        var size = -1L
        runCatching {
            context.contentResolver.query(
                uri,
                arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE),
                null,
                null,
                null,
            )?.use { cursor ->
                if (cursor.moveToFirst()) {
                    val nameIdx = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    val sizeIdx = cursor.getColumnIndex(OpenableColumns.SIZE)
                    if (nameIdx >= 0) name = cursor.getString(nameIdx)
                    if (sizeIdx >= 0 && !cursor.isNull(sizeIdx)) size = cursor.getLong(sizeIdx)
                }
            }
        }
        return name to size
    }

    private fun loadAndEnrichCatalog(): List<LocalModelRecord> {
        val records = loadCatalog()
        var changed = false
        val enriched =
            records.map { rec ->
                if (rec.architecture == null || rec.contextLength == null) {
                    val inspected = runCatching { GgufReader.inspect(File(rec.path)) }.getOrNull()
                    if (inspected != null) {
                        changed = true
                        rec.copy(
                            architecture = rec.architecture ?: inspected.architecture,
                            quantization = rec.quantization ?: inspected.quantization,
                            contextLength = rec.contextLength ?: inspected.contextLength,
                            hasTokenizer = inspected.hasTokenizer,
                        )
                    } else rec
                } else rec
            }
        if (changed) runCatching { saveCatalog(enriched) }
        return enriched
    }

    private fun loadCatalog(): List<LocalModelRecord> {
        if (!catalogFile.isFile) return emptyList()
        return runCatching {
            WireJson.decodeFromString<List<LocalModelRecord>>(catalogFile.readText())
                .filter { File(it.path).isFile }
        }.getOrElse { emptyList() }
    }

    private fun saveCatalog(records: List<LocalModelRecord>) {
        val tmp = File(rootDir, "omnicore-local-models.json.tmp")
        tmp.writeText(WireJson.encodeToString(records))
        runCatching {
            Files.move(
                tmp.toPath(),
                catalogFile.toPath(),
                StandardCopyOption.REPLACE_EXISTING,
                StandardCopyOption.ATOMIC_MOVE,
            )
        }.onFailure {
            Files.move(tmp.toPath(), catalogFile.toPath(), StandardCopyOption.REPLACE_EXISTING)
        }
    }

    companion object {
        private val QUANT_RE = Regex("(?i)(IQ[1-4]_[A-Z0-9_]+|Q[2-8]_[A-Z0-9_]+|F16|F32|BF16)")

        fun validateGgufHeader(stream: InputStream) {
            val header = ByteArray(8)
            val data = DataInputStream(stream)
            try {
                data.readFully(header)
            } catch (_: Exception) {
                throw ApiFailure("invalid_gguf")
            }
            GgufReader.validateMagicHeader(header)
        }

        fun inferQuantization(filename: String): String? =
            QUANT_RE.find(filename)?.value?.uppercase()
    }
}
