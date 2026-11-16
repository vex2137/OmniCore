package io.github.vex2137.omnicore

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.OpenableColumns
import java.io.DataInputStream
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.io.InputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
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
    val managedFile: Boolean = false,
)

/**
 * Manages on-device GGUF models with GGUF header validation, SAF URI permission
 * persistence, and zero unnecessary duplicate copies.
 */
class LocalModelStore(private val rootDir: File) {
    private val modelsDir = File(rootDir, "omnicore-models").apply { mkdirs() }
    private val catalogFile = File(rootDir, "omnicore-local-models.json")
    private val lock = Any()

    fun list(): List<LocalModelRecord> = synchronized(lock) { loadCatalog() }

    fun find(id: String): LocalModelRecord? = synchronized(lock) { loadCatalog().firstOrNull { it.id == id } }

    fun fileFor(id: String): File? = find(id)?.let { File(it.path) }

    fun importLocalFile(source: File, displayName: String? = null): LocalModelRecord {
        if (!source.isFile || !source.canRead()) throw ApiFailure("model_not_found")
        FileInputStream(source).use { validateGgufHeader(it) }
        val name =
            (displayName ?: source.nameWithoutExtension)
                .removeSuffix(".gguf")
                .ifBlank { source.nameWithoutExtension }
        val record =
            LocalModelRecord(
                id = UUID.randomUUID().toString().replace("-", ""),
                name = name,
                path = source.absolutePath,
                uri = null,
                sizeBytes = source.length(),
                quantization = inferQuantization(source.name),
                managedFile = false,
            )
        synchronized(lock) {
            val existing = loadCatalog().filterNot { it.path == record.path }
            saveCatalog(existing + record)
        }
        return record
    }

    fun importContentUri(context: Context, uri: Uri): LocalModelRecord {
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
            loadCatalog().firstOrNull { it.uri == uri.toString() && File(it.path).isFile }?.let {
                return it
            }
        }

        if (reportedSize > 0 && modelsDir.usableSpace < reportedSize + 64L * 1024L * 1024L) {
            throw ApiFailure("insufficient_storage")
        }

        val id = UUID.randomUUID().toString().replace("-", "")
        val part = File(modelsDir, "$id.gguf.partial")
        val target = File(modelsDir, "$id.gguf")
        try {
            val stream =
                try {
                    context.contentResolver.openInputStream(uri)
                } catch (_: SecurityException) {
                    throw ApiFailure("model_permission_denied")
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
                validateGgufHeaderBytes(header)
                FileOutputStream(part).use { out ->
                    out.write(header)
                    val buf = ByteArray(1024 * 1024)
                    while (true) {
                        val n = input.read(buf)
                        if (n == -1) break
                        out.write(buf, 0, n)
                    }
                    out.fd.sync()
                }
            }
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
        } catch (e: Exception) {
            part.delete()
            target.delete()
            if (e is ApiFailure) throw e
            if (e is SecurityException) throw ApiFailure("model_permission_denied")
            if (e is java.io.FileNotFoundException) throw ApiFailure("model_not_found")
            throw ApiFailure("model_import_failed")
        }

        val record =
            LocalModelRecord(
                id = id,
                name = baseName,
                path = target.absolutePath,
                uri = uri.toString(),
                sizeBytes = target.length(),
                quantization = inferQuantization(cleanName),
                managedFile = true,
            )
        synchronized(lock) { saveCatalog(loadCatalog() + record) }
        return record
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
        Files.move(
            tmp.toPath(),
            catalogFile.toPath(),
            StandardCopyOption.REPLACE_EXISTING,
            StandardCopyOption.ATOMIC_MOVE,
        )
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
            validateGgufHeaderBytes(header)
        }

        fun validateGgufHeaderBytes(header: ByteArray) {
            if (
                header.size < 8 ||
                    header[0] != 'G'.code.toByte() ||
                    header[1] != 'G'.code.toByte() ||
                    header[2] != 'U'.code.toByte() ||
                    header[3] != 'F'.code.toByte()
            ) {
                throw ApiFailure("invalid_gguf")
            }
            val version = ByteBuffer.wrap(header, 4, 4).order(ByteOrder.LITTLE_ENDIAN).int
            if (version !in 1..3) throw ApiFailure("invalid_gguf")
        }

        fun inferQuantization(filename: String): String? =
            QUANT_RE.find(filename)?.value?.uppercase()
    }
}
