package io.github.vex2137.omnicore

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import java.net.URI

private val providerEndpoints = mapOf(
    "openai" to "https://api.openai.com/v1",
    "anthropic" to "https://api.anthropic.com/v1",
    "gemini" to "https://generativelanguage.googleapis.com/v1beta",
    "openrouter" to "https://openrouter.ai/api/v1",
)

@Composable
private fun ProviderChoice(items: List<Pair<String, String>>, selected: String, choose: (String) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    Box(Modifier.fillMaxWidth()) {
        OutlinedButton(onClick = { expanded = true }, modifier = Modifier.fillMaxWidth()) {
            Text(items.firstOrNull { it.first == selected }?.second.orEmpty(), maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        DropdownMenu(expanded, { expanded = false }, Modifier.heightIn(max = 280.dp)) {
            items.forEach { (id, label) -> DropdownMenuItem(text = { Text(label, maxLines = 2, overflow = TextOverflow.Ellipsis) }, onClick = { expanded = false; choose(id) }) }
        }
    }
}

@Composable
fun ProviderSettings(s: UiState, vm: OmniViewModel) {
    var selected by remember { mutableStateOf("") }
    LaunchedEffect(s.providerEditingId) { s.providerEditingId?.let { selected = it } }
    val existing = s.providers.firstOrNull { it.id == selected }
    var kind by remember(selected, existing) { mutableStateOf(existing?.kind ?: "openai") }
    var label by remember(selected, existing) { mutableStateOf(existing?.label ?: "") }
    var endpoint by remember(selected, existing) { mutableStateOf(existing?.endpoint ?: providerEndpoints.getValue("openai")) }
    // Provider secrets are intentionally never rememberSaveable or part of UiState.
    var key by remember(selected) { mutableStateOf("") }
    var clear by remember(selected) { mutableStateOf(false) }
    var sampling by remember(selected, existing) { mutableStateOf(existing?.sampling ?: false) }
    var model by remember(selected) { mutableStateOf("") }
    var confirmAdd by remember { mutableStateOf(false) }
    var confirmDelete by remember { mutableStateOf(false) }
    val secure = try { val uri = URI(s.url); uri.scheme == "https" || uri.host in listOf("127.0.0.1", "localhost", "[::1]") } catch (_: Exception) { false }
    Text(stringResource(R.string.providers_title), style = MaterialTheme.typography.titleLarge)
    Text(stringResource(R.string.providers_security_hint))
    if (!secure) Text(stringResource(R.string.provider_key_requires_https), style = MaterialTheme.typography.bodySmall)
    ProviderChoice(listOf("" to stringResource(R.string.provider_new)) + s.providers.map { it.id to it.label }, selected) {
        selected = it; key = ""; vm.clearProviderStatus()
    }
    ProviderChoice(listOf("openai" to "OpenAI", "anthropic" to "Anthropic", "gemini" to "Google Gemini", "openrouter" to "OpenRouter", "custom" to "OpenAI-compatible"), kind) {
        kind = it; endpoint = providerEndpoints[it].orEmpty(); key = ""
    }
    OutlinedTextField(label, { label = it.take(80) }, label = { Text(stringResource(R.string.provider_label)) }, modifier = Modifier.fillMaxWidth())
    OutlinedTextField(endpoint, { endpoint = it.take(2048) }, label = { Text(stringResource(R.string.provider_endpoint)) }, enabled = kind == "custom" && !s.busy,
        singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri), modifier = Modifier.fillMaxWidth())
    OutlinedTextField(key, { key = it.take(8192) }, label = { Text(stringResource(R.string.provider_key)) }, enabled = secure && !s.busy,
        visualTransformation = PasswordVisualTransformation(), singleLine = true, modifier = Modifier.fillMaxWidth().testTag("provider_key"))
    Text(stringResource(if (existing?.keyPresent == true) R.string.provider_key_saved else R.string.provider_key_missing))
    Row {
        Checkbox(clear, { clear = it }, enabled = !s.busy)
        Text(stringResource(R.string.provider_clear_key), modifier = Modifier.weight(1f))
    }
    Row {
        Checkbox(sampling, { sampling = it }, enabled = !s.busy)
        Text(stringResource(R.string.provider_sampling), modifier = Modifier.weight(1f))
    }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Button(onClick = {
            val value = ProviderInput(kind, label, endpoint, key.takeIf { it.isNotEmpty() }, clear, sampling)
            key = ""; vm.saveProvider(selected.takeIf { it.isNotEmpty() }, value)
        }, enabled = s.connected && !s.busy && (!clear || key.isEmpty()), modifier = Modifier.testTag("provider_save")) { Text(stringResource(R.string.save)) }
        OutlinedButton(onClick = { confirmDelete = true }, enabled = existing != null && !s.busy) { Text(stringResource(R.string.delete)) }
    }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedButton(onClick = { vm.testProvider(selected) }, enabled = existing != null && !s.busy, modifier = Modifier.testTag("provider_test")) { Text(stringResource(R.string.test_connection)) }
        OutlinedButton(onClick = { vm.providerModels(selected) }, enabled = existing != null && !s.busy) { Text(stringResource(R.string.provider_list_models)) }
    }
    if (s.providerTest == "ok") Text(stringResource(R.string.provider_test_ok))
    if (s.providerModels.isNotEmpty()) ProviderChoice(s.providerModels.map { it to it }, model) { model = it }
    OutlinedTextField(model, { model = it.take(256) }, label = { Text(stringResource(R.string.provider_model_id)) }, modifier = Modifier.fillMaxWidth().testTag("provider_model_id"))
    Button(onClick = { confirmAdd = true }, enabled = existing != null && model.isNotBlank() && !s.busy, modifier = Modifier.testTag("provider_add_model")) { Text(stringResource(R.string.provider_add_model)) }
    if (confirmAdd) AlertDialog(onDismissRequest = { confirmAdd = false }, title = { Text(stringResource(R.string.provider_add_model)) },
        text = { Text(stringResource(R.string.provider_cost_confirm)) },
        confirmButton = { TextButton(onClick = { confirmAdd = false; vm.addProviderModel(selected, model.trim()) }) { Text(stringResource(R.string.confirm)) } },
        dismissButton = { TextButton(onClick = { confirmAdd = false }) { Text(stringResource(R.string.cancel)) } })
    if (confirmDelete) AlertDialog(onDismissRequest = { confirmDelete = false }, title = { Text(stringResource(R.string.delete)) },
        text = { Text(stringResource(R.string.provider_delete_confirm)) },
        confirmButton = { TextButton(onClick = { confirmDelete = false; vm.deleteProvider(selected); selected = "" }) { Text(stringResource(R.string.delete)) } },
        dismissButton = { TextButton(onClick = { confirmDelete = false }) { Text(stringResource(R.string.cancel)) } })
}
