package io.github.vex2137.omnicore

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp

@Composable
fun GenerationSettings(s: UiState, vm: OmniViewModel) {
    var temperature by
        rememberSaveable(s.parameters) { mutableStateOf(s.parameters.temperature.toString()) }
    var topP by rememberSaveable(s.parameters) { mutableStateOf(s.parameters.topP.toString()) }
    var tokens by
        rememberSaveable(s.parameters) { mutableStateOf(s.parameters.maxTokens.toString()) }
    var context by
        rememberSaveable(s.parameters) { mutableStateOf(s.parameters.context.toString()) }
    var device by rememberSaveable(s.parameters) { mutableStateOf(s.parameters.device) }
    val llama = s.models.firstOrNull { it.id == s.selectedModel }?.backend != "ollama"
    var thinking by rememberSaveable(s.parameters) { mutableStateOf(s.parameters.thinking) }
    var prompt by rememberSaveable(s.parameters) { mutableStateOf(s.parameters.systemPrompt) }
    val parameters =
        s.parameters.copy(
            temperature = temperature.toDoubleOrNull() ?: Double.NaN,
            topP = topP.toDoubleOrNull() ?: Double.NaN,
            maxTokens = tokens.toIntOrNull() ?: 0,
            context = context.toIntOrNull() ?: 0,
            systemPrompt = prompt,
            thinking = thinking,
            device = if (llama) device else s.parameters.device,
            gpuLayers =
                if (!llama) s.parameters.gpuLayers
                else if (device == "cpu") 0 else s.parameters.gpuLayers.takeIf { it > 0 } ?: 99,
        )
    Text(stringResource(R.string.generation), style = MaterialTheme.typography.titleMedium)
    Text(
        stringResource(
            if (s.selectedConversation != null) R.string.parameters_conversation
            else R.string.parameters_defaults
        ),
        style = MaterialTheme.typography.bodySmall,
    )
    if (llama) {
        Text(stringResource(R.string.processing_backend))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf(
                    "auto" to R.string.mode_auto,
                    "cpu" to R.string.mode_cpu,
                    "cuda" to R.string.mode_cuda,
                )
                .forEach { (mode, label) ->
                    FilterChip(
                        selected = device == mode || (mode == "cuda" && device.startsWith("CUDA")),
                        onClick = { device = mode },
                        label = { Text(stringResource(label)) },
                    )
                }
        }
    }
    listOf(
            Triple(R.string.temperature, temperature, { value: String -> temperature = value }),
            Triple(R.string.top_p, topP, { value: String -> topP = value }),
            Triple(R.string.max_tokens, tokens, { value: String -> tokens = value }),
            Triple(R.string.context, context, { value: String -> context = value }),
        )
        .forEach { (label, value, update) ->
            OutlinedTextField(
                value,
                { update(it.take(16)) },
                label = { Text(stringResource(label)) },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                modifier = Modifier.fillMaxWidth().testTag("parameter_$label"),
            )
        }
    OutlinedTextField(
        prompt,
        { prompt = it.take(16384) },
        label = { Text(stringResource(R.string.system_prompt)) },
        modifier = Modifier.fillMaxWidth(),
        minLines = 2,
        maxLines = 5,
    )
    androidx.compose.foundation.layout.Row {
        Switch(checked = thinking, onCheckedChange = { thinking = it })
        Text(stringResource(R.string.thinking))
    }
    if (!parameters.valid())
        Text(stringResource(R.string.error_parameters), color = MaterialTheme.colorScheme.error)
    Button(
        onClick = { vm.parameters(parameters) },
        enabled =
            parameters.valid() &&
                !s.busy &&
                !s.generating &&
                (s.connected || s.selectedConversation == null),
        modifier = Modifier.testTag("parameters_save"),
    ) {
        Text(stringResource(R.string.save_parameters))
    }
}
