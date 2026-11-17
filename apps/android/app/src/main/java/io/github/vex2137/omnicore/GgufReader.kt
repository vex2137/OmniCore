package io.github.vex2137.omnicore

import java.io.DataInputStream
import java.io.EOFException
import java.io.File
import java.io.InputStream
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.charset.StandardCharsets

data class GgufMetadata(
    val version: Int,
    val tensorCount: Long,
    val architecture: String,
    val name: String,
    val quantization: String?,
    val contextLength: Int?,
    val blockCount: Int?,
    val hasTokenizer: Boolean,
)

/**
 * Bounded GGUF v2/v3 parser and structural completeness validator.
 * Mirrors OmniCore backend's GGUF validator without loading tensor weights.
 */
object GgufReader {
    private const val MAX_METADATA_BYTES = 64L * 1024L * 1024L
    private const val MAX_STRING_BYTES = 4 * 1024 * 1024

    private val QUANTIZATION_NAMES =
        mapOf(
            0 to "F32",
            1 to "F16",
            2 to "Q4_0",
            3 to "Q4_1",
            7 to "Q8_0",
            8 to "Q5_0",
            9 to "Q5_1",
            10 to "Q2_K",
            11 to "Q3_K_S",
            12 to "Q3_K_M",
            13 to "Q3_K_L",
            14 to "Q4_K_S",
            15 to "Q4_K_M",
            16 to "Q5_K_S",
            17 to "Q5_K_M",
            18 to "Q6_K",
            19 to "IQ2_XXS",
            20 to "IQ2_XS",
            21 to "IQ3_XXS",
            22 to "IQ1_S",
            23 to "IQ4_NL",
            24 to "IQ3_S",
            25 to "IQ2_S",
            26 to "IQ4_XS",
            27 to "I8",
            28 to "I16",
            29 to "I32",
            30 to "I64",
            31 to "F64",
            32 to "IQ1_M",
            33 to "BF16",
        )

    fun validateMagicHeader(header: ByteArray) {
        if (
            header.size < 8 ||
                header[0] != 'G'.code.toByte() ||
                header[1] != 'G'.code.toByte() ||
                header[2] != 'U'.code.toByte() ||
                header[3] != 'F'.code.toByte()
        ) {
            throw ApiFailure("invalid_gguf")
        }
        val le = ByteBuffer.wrap(header, 4, 4).order(ByteOrder.LITTLE_ENDIAN).int
        val be = ByteBuffer.wrap(header, 4, 4).order(ByteOrder.BIG_ENDIAN).int
        if (le !in 2..3 && be !in 2..3) {
            if (le == 1 || be == 1) throw ApiFailure("unsupported_gguf_version")
            throw ApiFailure("invalid_gguf")
        }
    }

    fun inspect(file: File): GgufMetadata {
        if (!file.isFile || !file.canRead()) throw ApiFailure("model_not_found")
        val totalSize = file.length()
        RandomAccessFile(file, "r").use { raf ->
            val stream =
                object : InputStream() {
                    override fun read(): Int = raf.read()

                    override fun read(b: ByteArray, off: Int, len: Int): Int = raf.read(b, off, len)

                    override fun skip(n: Long): Long {
                        if (n <= 0) return 0L
                        val cur = raf.filePointer
                        val target = (cur + n).coerceAtMost(totalSize)
                        raf.seek(target)
                        return target - cur
                    }
                }
            return parse(stream, totalSize, position = { raf.filePointer }, validateTensors = true)
        }
    }

    fun inspectStream(stream: InputStream, totalSize: Long? = null): GgufMetadata {
        var offset = 0L
        val counting =
            object : InputStream() {
                override fun read(): Int {
                    val b = stream.read()
                    if (b >= 0) offset++
                    return b
                }

                override fun read(b: ByteArray, off: Int, len: Int): Int {
                    val n = stream.read(b, off, len)
                    if (n > 0) offset += n
                    return n
                }

                override fun skip(n: Long): Long {
                    if (n <= 0) return 0L
                    var remaining = n
                    val buf = ByteArray(minOf(8192L, remaining).toInt())
                    while (remaining > 0) {
                        val read = read(buf, 0, minOf(buf.size.toLong(), remaining).toInt())
                        if (read <= 0) break
                        remaining -= read
                    }
                    return n - remaining
                }
            }
        return parse(counting, totalSize, position = { offset }, validateTensors = false)
    }

    private fun parse(
        stream: InputStream,
        totalSize: Long?,
        position: () -> Long,
        validateTensors: Boolean,
    ): GgufMetadata {
        val data = DataInputStream(stream)
        val magic = ByteArray(4)
        var magicRead = 0
        while (magicRead < 4) {
            val n = stream.read(magic, magicRead, 4 - magicRead)
            if (n < 0) break
            magicRead += n
        }
        val expectedMagic = byteArrayOf('G'.code.toByte(), 'G'.code.toByte(), 'U'.code.toByte(), 'F'.code.toByte())
        for (i in 0 until magicRead) {
            if (magic[i] != expectedMagic[i]) {
                throw ApiFailure("invalid_gguf")
            }
        }
        if (magicRead < 4) {
            throw ApiFailure("incomplete_gguf")
        }

        val verBytes = ByteArray(4)
        try {
            data.readFully(verBytes)
        } catch (_: EOFException) {
            throw ApiFailure("incomplete_gguf")
        }
        var order = ByteOrder.LITTLE_ENDIAN
        var version = ByteBuffer.wrap(verBytes).order(order).int
        if (version !in 2..3) {
            val be = ByteBuffer.wrap(verBytes).order(ByteOrder.BIG_ENDIAN).int
            if (be in 2..3) {
                order = ByteOrder.BIG_ENDIAN
                version = be
            } else if (version == 1 || be == 1) {
                throw ApiFailure("unsupported_gguf_version")
            } else {
                throw ApiFailure("invalid_gguf")
            }
        }

        fun checkBounds(count: Long) {
            val pos = position()
            if (count < 0 || pos + count > MAX_METADATA_BYTES) {
                throw ApiFailure("invalid_gguf")
            }
            if (totalSize != null && pos + count > totalSize) {
                throw ApiFailure("incomplete_gguf")
            }
        }

        fun readBytes(count: Int): ByteArray {
            checkBounds(count.toLong())
            val buf = ByteArray(count)
            try {
                data.readFully(buf)
            } catch (_: EOFException) {
                throw ApiFailure("incomplete_gguf")
            }
            return buf
        }

        fun readU32(): Int = ByteBuffer.wrap(readBytes(4)).order(order).int

        fun readU64(): Long = ByteBuffer.wrap(readBytes(8)).order(order).long

        fun readF32(): Float = ByteBuffer.wrap(readBytes(4)).order(order).float

        fun readF64(): Double = ByteBuffer.wrap(readBytes(8)).order(order).double

        fun skipExactly(count: Long) {
            checkBounds(count)
            var left = count
            while (left > 0) {
                val skipped = stream.skip(left)
                if (skipped > 0) {
                    left -= skipped
                } else {
                    val b = stream.read()
                    if (b < 0) throw ApiFailure("incomplete_gguf")
                    left -= 1L
                }
            }
        }

        fun readString(keep: Boolean): String? {
            val len = readU64()
            if (len < 0 || len > MAX_STRING_BYTES) throw ApiFailure("invalid_gguf")
            if (!keep) {
                skipExactly(len)
                return null
            }
            val bytes = readBytes(len.toInt())
            return String(bytes, StandardCharsets.UTF_8)
        }

        fun scalarByteSize(type: Int): Int? =
            when (type) {
                0,
                1,
                7 -> 1
                2,
                3 -> 2
                4,
                5,
                6 -> 4
                10,
                11,
                12 -> 8
                else -> null
            }

        fun readOrSkipValue(type: Int, keep: Boolean, depth: Int = 0): Any? {
            if (type == 8) return readString(keep)
            if (type == 9) {
                if (depth > 0) throw ApiFailure("invalid_gguf")
                val elemType = readU32()
                val count = readU64()
                if (count < 0 || count > 2_000_000L) throw ApiFailure("invalid_gguf")
                val fixedSize = scalarByteSize(elemType)
                if (fixedSize != null) {
                    val bytes = count * fixedSize
                    skipExactly(bytes)
                    return count
                }
                if (elemType == 8) {
                    for (i in 0L until count) {
                        readString(false)
                    }
                    return count
                }
                throw ApiFailure("invalid_gguf")
            }
            val size = scalarByteSize(type) ?: throw ApiFailure("invalid_gguf")
            return when (type) {
                0 -> readBytes(1)[0].toInt() and 0xFF
                1 -> readBytes(1)[0].toInt()
                2 -> ByteBuffer.wrap(readBytes(2)).order(order).short.toInt() and 0xFFFF
                3 -> ByteBuffer.wrap(readBytes(2)).order(order).short.toInt()
                4 -> readU32()
                5 -> readU32()
                6 -> {
                    val v = readF32()
                    if (!v.isFinite()) throw ApiFailure("invalid_gguf")
                    v
                }
                7 -> readBytes(1)[0].toInt() != 0
                10,
                11 -> readU64()
                12 -> {
                    val v = readF64()
                    if (!v.isFinite()) throw ApiFailure("invalid_gguf")
                    v
                }
                else -> {
                    skipExactly(size.toLong())
                    null
                }
            }
        }

        val tensorCount = readU64()
        val keyCount = readU64()
        if (tensorCount !in 1L..200_000L || keyCount !in 1L..4096L) {
            throw ApiFailure("invalid_gguf")
        }

        var architecture: String? = null
        var name: String? = null
        var fileType: Int? = null
        var splitCount: Long? = null
        var alignment = 32L
        var contextLength: Int? = null
        var blockCount: Int? = null
        var hasTokenizer = false
        val seenKeys = HashSet<String>(keyCount.toInt())

        for (i in 0L until keyCount) {
            val key = readString(true) ?: throw ApiFailure("invalid_gguf")
            if (key.length > 256 || !seenKeys.add(key)) throw ApiFailure("invalid_gguf")
            val valType = readU32()
            val keep =
                key in
                    setOf(
                        "general.architecture",
                        "general.name",
                        "general.file_type",
                        "general.alignment",
                        "split.count",
                        "tokenizer.ggml.model",
                        "tokenizer.ggml.tokens",
                    ) ||
                    key.endsWith(".context_length") ||
                    key.endsWith(".block_count")
            val value = readOrSkipValue(valType, keep)
            when {
                key == "general.architecture" && value is String -> architecture = value
                key == "general.name" && value is String -> name = value
                key == "general.file_type" && value is Number -> fileType = value.toInt()
                key == "general.alignment" && value is Number -> alignment = value.toLong()
                key == "split.count" && value is Number -> splitCount = value.toLong()
                key == "tokenizer.ggml.model" || key == "tokenizer.ggml.tokens" -> hasTokenizer = true
                key.endsWith(".context_length") && value is Number ->
                    if (architecture == null || key == "$architecture.context_length") {
                        contextLength = value.toInt()
                    }
                key.endsWith(".block_count") && value is Number ->
                    if (architecture == null || key == "$architecture.block_count") {
                        blockCount = value.toInt()
                    }
            }
        }

        if (splitCount != null && splitCount > 1L) throw ApiFailure("multipart_gguf_unsupported")
        val arch =
            architecture?.takeIf { it.isNotBlank() && it.length <= 128 }
                ?: throw ApiFailure("invalid_gguf")
        if (alignment !in 1L..4096L || (alignment and (alignment - 1L)) != 0L) {
            throw ApiFailure("invalid_gguf")
        }

        if (validateTensors && totalSize != null) {
            val tensorOffsets = ArrayList<Pair<Long, Long>>(tensorCount.toInt().coerceAtMost(4096))
            for (i in 0L until tensorCount) {
                readString(false)
                val dims = readU32()
                if (dims !in 1..4) throw ApiFailure("invalid_gguf")
                var elements = 1L
                for (d in 0 until dims) {
                    val dim = readU64()
                    if (dim <= 0L) throw ApiFailure("invalid_gguf")
                    elements =
                        if (elements > Long.MAX_VALUE / dim) Long.MAX_VALUE else elements * dim
                }
                val kind = readU32()
                val offset = readU64()
                if (offset < 0 || offset % alignment != 0L) throw ApiFailure("invalid_gguf")
                val minBytes =
                    when (kind) {
                        0 -> if (elements > Long.MAX_VALUE / 4L) Long.MAX_VALUE else elements * 4L
                        1 -> if (elements > Long.MAX_VALUE / 2L) Long.MAX_VALUE else elements * 2L
                        else -> 1L
                    }
                tensorOffsets.add(offset to minBytes)
            }
            val pos = position()
            val dataStart = ((pos + alignment - 1L) / alignment) * alignment
            for ((offset, minBytes) in tensorOffsets) {
                if (dataStart > totalSize - offset || dataStart + offset > totalSize - minBytes) {
                    throw ApiFailure("incomplete_gguf")
                }
            }
        }

        val quant = fileType?.let { QUANTIZATION_NAMES[it] ?: "file_type_$it" }
        return GgufMetadata(
            version = version,
            tensorCount = tensorCount,
            architecture = arch,
            name = (name ?: arch).take(256),
            quantization = quant,
            contextLength = contextLength,
            blockCount = blockCount,
            hasTokenizer = hasTokenizer,
        )
    }
}
