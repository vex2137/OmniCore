package io.github.vex2137.omnicore

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource

@Composable
fun GenerationDetails(s: GenerationStatistics) {
    val parts = mutableListOf<String>()
    s.executionProvider?.let { parts.add("$it · ${s.executionModel.orEmpty()}") }
    fun add(label: String, value: Number?, unit: String = "") {
        if (value != null) {
            val number = if (value is Double) "%.2f".format(value) else value.toString()
            parts.add("$label: $number $unit".trim())
        }
    }
    add(stringResource(R.string.speed), s.tokensPerSecond, "tok/s")
    add(stringResource(R.string.input_tokens), s.inputTokens)
    add(stringResource(R.string.max_tokens), s.outputTokens)
    add(stringResource(R.string.ttft), s.ttftSeconds, "s")
    add(stringResource(R.string.first_answer), s.firstAnswerSeconds, "s")
    add(stringResource(R.string.generation_time), s.generationSeconds, "s")
    add(stringResource(R.string.model_load_time), s.modelLoadSeconds, "s")
    if (s.contextUsedTokens != null && s.contextLimitTokens != null)
        parts.add(
            "${stringResource(R.string.context)}: ${s.contextUsedTokens}/${s.contextLimitTokens}"
        )
    s.finishReason?.let { reason ->
        val display =
            when (reason) {
                "stop" -> stringResource(R.string.completed)
                "length" -> stringResource(R.string.finish_length)
                "cancelled" -> stringResource(R.string.cancelled)
                "error" -> stringResource(R.string.failed)
                else -> reason
            }
        parts.add("${stringResource(R.string.finish_reason)}: $display")
    }
    add(stringResource(R.string.offloaded_layers), s.gpuOffloadedLayers)
    s.executionDevice?.let { parts.add("${stringResource(R.string.execution_device)}: $it") }
    s.fallbackReason?.let { reason ->
        parts.add(stringResource(when (reason) {
            "gpu_unavailable" -> R.string.fallback_gpu_unavailable
            "gpu_offload_unverified" -> R.string.fallback_offload_unverified
            "cuda_runtime_unavailable" -> R.string.fallback_cuda_runtime
            else -> R.string.fallback_other
        }, reason))
    }
    if (parts.isNotEmpty())
        Text(
            parts.joinToString(" · "),
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
}
