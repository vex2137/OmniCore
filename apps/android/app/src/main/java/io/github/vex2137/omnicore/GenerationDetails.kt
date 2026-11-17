package io.github.vex2137.omnicore

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp

internal data class StatEntry(val label: String, val value: String)

internal data class StatLabels(
    val speed: String,
    val inputTokens: String,
    val outputTokens: String,
    val ttft: String,
    val firstAnswer: String,
    val generationTime: String,
    val modelLoadTime: String,
    val context: String,
    val finishReason: String,
    val completed: String,
    val finishLength: String,
    val cancelled: String,
    val failed: String,
    val offloadedLayers: String,
    val device: String,
    val cpuFallback: String,
)

internal fun formatCompactMetrics(
    s: GenerationStatistics,
    cancelledLabel: String,
): List<String> {
    val parts = mutableListOf<String>()
    if (s.finishReason == "cancelled") parts.add(cancelledLabel)
    s.tokensPerSecond?.let { parts.add("%.1f tok/s".format(it)) }
    s.generationSeconds?.let { parts.add("%.2f s".format(it)) }
    val hasPerfMetric = s.tokensPerSecond != null || s.generationSeconds != null
    if (!hasPerfMetric) {
        s.ttftSeconds?.let { parts.add("TTFT %.2f s".format(it)) }
            ?: s.outputTokens?.let { parts.add("$it tok") }
            ?: s.executionDevice?.let { parts.add(it) }
    }
    return parts
}

internal fun buildStatEntries(s: GenerationStatistics, labels: StatLabels): List<StatEntry> {
    val rows = mutableListOf<StatEntry>()
    fun addNum(label: String, value: Number?, unit: String = "") {
        if (value != null) {
            val number = if (value is Double) "%.2f".format(value) else value.toString()
            rows.add(StatEntry(label, "$number $unit".trim()))
        }
    }
    addNum(labels.speed, s.tokensPerSecond, "tok/s")
    addNum(labels.inputTokens, s.inputTokens)
    addNum(labels.outputTokens, s.outputTokens)
    addNum(labels.ttft, s.ttftSeconds, "s")
    addNum(labels.firstAnswer, s.firstAnswerSeconds, "s")
    addNum(labels.generationTime, s.generationSeconds, "s")
    addNum(labels.modelLoadTime, s.modelLoadSeconds, "s")
    if (s.contextUsedTokens != null && s.contextLimitTokens != null) {
        val ctxText =
            if (s.contextLimitTokens > 0) {
                val pct = ((s.contextUsedTokens * 100.0) / s.contextLimitTokens).toInt().coerceIn(0, 100)
                "${s.contextUsedTokens}/${s.contextLimitTokens} ($pct%)"
            } else {
                "${s.contextUsedTokens}/${s.contextLimitTokens}"
            }
        rows.add(StatEntry(labels.context, ctxText))
    }
    s.finishReason?.let { reason ->
        val display =
            when (reason) {
                "stop" -> labels.completed
                "length" -> labels.finishLength
                "cancelled" -> labels.cancelled
                "error" -> labels.failed
                else -> reason
            }
        rows.add(StatEntry(labels.finishReason, display))
    }
    addNum(labels.offloadedLayers, s.gpuOffloadedLayers)
    s.executionDevice?.let { rows.add(StatEntry(labels.device, it)) }
    if (s.fallbackReason != null) {
        rows.add(StatEntry(labels.device, labels.cpuFallback))
    }
    return rows
}

@Composable
fun GenerationDetails(s: GenerationStatistics, isStreaming: Boolean = false) {
    if (isStreaming) return

    val cancelledLabel = stringResource(R.string.cancelled)
    val labels =
        StatLabels(
            speed = stringResource(R.string.speed),
            inputTokens = stringResource(R.string.input_tokens),
            outputTokens = stringResource(R.string.max_tokens),
            ttft = stringResource(R.string.ttft),
            firstAnswer = stringResource(R.string.first_answer),
            generationTime = stringResource(R.string.generation_time),
            modelLoadTime = stringResource(R.string.model_load_time),
            context = stringResource(R.string.context),
            finishReason = stringResource(R.string.finish_reason),
            completed = stringResource(R.string.completed),
            finishLength = stringResource(R.string.finish_length),
            cancelled = cancelledLabel,
            failed = stringResource(R.string.failed),
            offloadedLayers = stringResource(R.string.offloaded_layers),
            device = stringResource(R.string.device),
            cpuFallback = stringResource(R.string.cpu_fallback),
        )
    val compactParts = formatCompactMetrics(s, cancelledLabel)
    val entries = buildStatEntries(s, labels)
    if (compactParts.isEmpty() && entries.isEmpty()) return

    var expanded by rememberSaveable { mutableStateOf(false) }
    val detailsLabel = stringResource(R.string.stats_details)
    val hideLabel = stringResource(R.string.stats_hide_details)

    Column(Modifier.fillMaxWidth().padding(top = 10.dp)) {
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.55f))
        Spacer(Modifier.height(2.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                text = compactParts.joinToString(" · "),
                modifier = Modifier.weight(1f).testTag("stats_compact"),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            if (entries.isNotEmpty()) {
                TextButton(
                    onClick = { expanded = !expanded },
                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp),
                    modifier =
                        Modifier.testTag("stats_toggle").semantics {
                            stateDescription = if (expanded) hideLabel else detailsLabel
                        },
                ) {
                    Text(
                        text = if (expanded) hideLabel else detailsLabel,
                        style = MaterialTheme.typography.labelMedium,
                    )
                    Spacer(Modifier.width(2.dp))
                    Icon(
                        imageVector =
                            if (expanded) Icons.Default.KeyboardArrowUp
                            else Icons.Default.KeyboardArrowDown,
                        contentDescription = null,
                        modifier = Modifier.size(16.dp),
                    )
                }
            }
        }
        AnimatedVisibility(visible = expanded && entries.isNotEmpty()) {
            Surface(
                shape = RoundedCornerShape(10.dp),
                color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.45f),
                border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
                modifier = Modifier.fillMaxWidth().padding(top = 6.dp).testTag("stats_expanded_panel"),
            ) {
                Column(
                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
                    verticalArrangement = Arrangement.spacedBy(5.dp),
                ) {
                    entries.forEach { entry ->
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(12.dp),
                            verticalAlignment = Alignment.Top,
                        ) {
                            Text(
                                text = entry.label,
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.weight(1f),
                            )
                            Text(
                                text = entry.value,
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurface,
                                fontWeight = FontWeight.Medium,
                            )
                        }
                    }
                }
            }
        }
    }
}
