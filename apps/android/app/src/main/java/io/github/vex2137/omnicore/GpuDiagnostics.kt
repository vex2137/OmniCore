package io.github.vex2137.omnicore

import java.util.ArrayDeque
import java.util.Locale
import java.util.regex.Pattern

/** Bounded startup-only evidence for native llama-server GPU/CPU initialization. */
internal class GpuDiagnostics(
    private val requestedLayers: Int,
    private val contextLength: Int,
) {
    private val startedNs = System.nanoTime()
    private val lines = ArrayDeque<String>()
    private val stages = ArrayList<String>()
    private var stage = "device-probe"
    private var status = "initializing"
    private var code: String? = null
    private var nativeCode: String? = null
    private var message: String? = null
    private var device: String? = null
    private var offloaded = 0
    private var exitCode: Int? = null
    private var logBytes = 0

    init {
        recordStage("device-probe")
    }

    @Synchronized
    fun recordStage(next: String) {
        if (status == "failed") return
        stage = next
        if (stages.isEmpty() || stages.last() != next) {
            if (stages.size == 20) stages.removeAt(0)
            stages.add(next)
        }
    }

    @Synchronized
    fun selected(id: String) {
        device = id
        recordStage("device-selection")
    }

    @Synchronized
    fun loaded(layers: Int) {
        offloaded = layers
        status = "loaded"
        recordStage("loaded-awaiting-inference")
    }

    @Synchronized
    fun confirmed() {
        status = "confirmed"
        recordStage("inference-confirmed")
    }

    @Synchronized
    fun line(raw: String) {
        if (status == "failed" || status == "confirmed") return
        val s = raw.replace(ANSI_RE, "").trim()
        if (s.contains("tokenizer.") || s.contains("chat_template")) return
        val lower = s.lowercase(Locale.ROOT)
        val matcher = OFFLOAD_PATTERN.matcher(s)
        if (matcher.find()) {
            offloaded = matcher.group(1)?.toIntOrNull() ?: offloaded
        }
        val relevant =
            lower.startsWith("ggml_") ||
                lower.startsWith("vulkan") ||
                lower.startsWith("vk::") ||
                lower.startsWith("error:") ||
                lower.startsWith("libc++abi:") ||
                s.contains("GGML_ASSERT") ||
                s.contains("GGML_ABORT") ||
                lower.startsWith("terminate") ||
                lower.startsWith("what():") ||
                lower.startsWith("llama_context:") ||
                lower.startsWith("load_tensors:") ||
                s.contains("VK_ERROR_") ||
                lower.contains("offloaded ")
        if (!relevant) return

        when {
            lower.contains("createcomputepipeline") ||
                (lower.contains("shader") && lower.contains("fail")) ->
                recordStage("shader-pipeline-create")
            lower.contains("createdevice") ||
                lower.contains("required feature") ||
                lower.contains("required extension") -> recordStage("vulkan-device-create")
            lower.startsWith("llama_context:") -> recordStage("context-create")
            lower.startsWith("load_tensors:") -> recordStage("model-load-offload")
        }
        val clean = sanitize(s)
        lines.addLast(clean)
        logBytes += clean.length
        while (lines.size > 64 || logBytes > 12_000) {
            logBytes -= lines.removeFirst().length
        }
    }

    @Synchronized
    fun fail(error: Throwable, processExit: Int?) {
        if (status == "failed") return
        status = "failed"
        code = error.message
        message = sanitize(error.message)
        exitCode = processExit
        val combined = lines.joinToString("\n") + "\n" + (message ?: "")
        val vk = VK_ERROR_PATTERN.matcher(combined)
        while (vk.find()) nativeCode = vk.group()
        if (nativeCode == null) {
            val hpp = CPP_ERROR_PATTERN.matcher(combined)
            while (hpp.find()) nativeCode = hpp.group()
        }
    }

    @Synchronized
    fun fallbackReason(): String {
        val normalized =
            (lines.joinToString(" ") + " " + (message ?: ""))
                .lowercase(Locale.ROOT)
                .replace(Regex("[^a-z0-9]"), "")
        return when {
            normalized.contains("outofdevicememory") ||
                normalized.contains("outofhostmemory") ||
                normalized.contains("outofmemory") ||
                normalized.contains("badalloc") ||
                normalized.contains("allocationfailed") -> "insufficient-vram"
            normalized.contains("vkerror") ||
                normalized.contains("errorinitializationfailed") ||
                normalized.contains("errorfeature") ||
                normalized.contains("errorextension") ||
                normalized.contains("errordevicelost") ||
                normalized.contains("gpudriver") -> "gpu-driver-failed"
            else -> "gpu-start-failed"
        }
    }

    @Synchronized
    fun summary(): String {
        val elapsedMs = ((System.nanoTime() - startedNs) / 1_000_000L)
        return buildString {
            append("stage=").append(stage)
            append(", status=").append(status)
            device?.let { append(", device=").append(it) }
            append(", layers=").append(offloaded).append("/").append(requestedLayers)
            append(", ctx=").append(contextLength)
            nativeCode?.let { append(", native=").append(it) }
            exitCode?.let { append(", exit=").append(it) }
            append(", elapsedMs=").append(elapsedMs)
        }
    }

    companion object {
        private val ANSI_RE = Regex("\\x1B\\[[0-9;]*[A-Za-z]")
        private val OFFLOAD_PATTERN = Pattern.compile("offloaded\\s+(\\d+)/(\\d+)\\s+layers to GPU")
        private val VK_ERROR_PATTERN = Pattern.compile("VK_ERROR_[A-Z0-9_]+")
        private val CPP_ERROR_PATTERN = Pattern.compile("\\bError[A-Z][A-Za-z]+\\b")

        fun sanitize(input: String?): String {
            if (input == null) return ""
            var s = input.replace(ANSI_RE, "")
            s =
                s.replace(
                    Regex("(?i)(bearer\\s+|api[-_]key[\\s:=]+|authorization[\\s:=]+)[^\\s,;]+"),
                    "$1<redacted>",
                )
            s = s.replace(Regex("https?://[^\\s]+"), "<url>")
            s = s.replace(Regex("(?<![A-Za-z0-9])/(?:[^\\s,;:]+)"), "<path>")
            return if (s.length > 512) s.substring(0, 512) else s
        }
    }
}
