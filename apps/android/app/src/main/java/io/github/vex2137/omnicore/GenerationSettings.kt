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
    var defaults by rememberSaveable { mutableStateOf(false) }
    val editingDefaults = defaults || s.selectedConversation == null
    val effective = if (editingDefaults) s.defaultParameters else s.parameters
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        FilterChip(selected = editingDefaults, onClick = { defaults = true }, label = { Text(stringResource(R.string.parameters_defaults)) })
        if (s.selectedConversation != null) FilterChip(selected = !editingDefaults, onClick = { defaults = false }, label = { Text(stringResource(R.string.parameters_conversation)) })
    }
    var temperature by
        remember(s.selectedConversation, editingDefaults, effective) { mutableStateOf(effective.temperature.toString()) }
    var topP by remember(s.selectedConversation, editingDefaults, effective) { mutableStateOf(effective.topP.toString()) }
    var tokens by
        remember(s.selectedConversation, editingDefaults, effective) { mutableStateOf(effective.maxTokens.toString()) }
    var context by
        remember(s.selectedConversation, editingDefaults, effective) { mutableStateOf(effective.context.toString()) }
    // Device selection is the saved backend/default snapshot, never a restored form draft.
    val device = effective.device
    var layers by remember(s.selectedConversation, editingDefaults, effective) {
        mutableStateOf(effective.gpuLayers.toString())
    }
    val llama = s.models.firstOrNull { it.id == s.selectedModel }?.backend != "ollama"
    var thinking by remember(s.selectedConversation, editingDefaults, effective) { mutableStateOf(effective.thinking) }
    var prompt by remember(s.selectedConversation, editingDefaults, effective) { mutableStateOf(effective.systemPrompt) }
    val parameters =
        effective.copy(
            temperature = temperature.toDoubleOrNull() ?: Double.NaN,
            topP = topP.toDoubleOrNull() ?: Double.NaN,
            maxTokens = tokens.toIntOrNull() ?: 0,
            context = context.toIntOrNull() ?: 0,
            systemPrompt = prompt,
            thinking = thinking,
            device = if (llama) device else effective.device,
            gpuLayers =
                if (!llama) effective.gpuLayers
                else if (device == "cpu") 0 else layers.toIntOrNull() ?: -1,
        )
    Text(stringResource(R.string.generation), style = MaterialTheme.typography.titleMedium)
    Text(
        stringResource(
            if (!editingDefaults) R.string.parameters_conversation
            else R.string.parameters_defaults
        ),
        style = MaterialTheme.typography.bodySmall,
    )
    if (llama) {
        Text(stringResource(R.string.selected_device))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf(
                    "auto" to R.string.mode_auto,
                    "cpu" to R.string.mode_cpu,
                    "cuda" to R.string.mode_cuda,
                )
                .forEach { (mode, label) ->
                    FilterChip(
                        selected = device == mode || (mode == "cuda" && device.startsWith("CUDA")),
                        onClick = {
                            val count = if (mode == "cpu") 0 else layers.toIntOrNull()?.takeIf { it > 0 } ?: 99
                            // Persist selection before leaving this screen or sending a prompt.
                            vm.parameters(parameters.copy(device = mode, gpuLayers = count), editingDefaults)
                        },
                        enabled = !s.busy && !s.generating && (s.connected || editingDefaults),
                        label = { Text(stringResource(label)) },
                        modifier = Modifier.testTag("device_$mode"),
                    )
                }
        }
        OutlinedTextField(
            layers,
            { layers = it.take(3) },
            label = { Text(stringResource(R.string.gpu_layers)) },
            supportingText = { Text(stringResource(R.string.gpu_layers_hint)) },
            enabled = device != "cpu",
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            modifier = Modifier.fillMaxWidth().testTag("gpu_layers"),
        )
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
        onClick = { vm.parameters(parameters, editingDefaults) },
        enabled =
            parameters.valid() &&
                !s.busy &&
                !s.generating &&
                (s.connected || editingDefaults),
        modifier = Modifier.testTag("parameters_save"),
    ) {
        Text(stringResource(R.string.save_parameters))
    }
}
