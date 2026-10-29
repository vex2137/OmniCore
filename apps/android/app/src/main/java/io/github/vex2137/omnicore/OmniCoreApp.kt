@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)

package io.github.vex2137.omnicore

import androidx.compose.foundation.background
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle

@Composable
fun OmniCoreApp(vm: OmniViewModel, onLanguage: (String) -> Unit) {
    val state by vm.state.collectAsStateWithLifecycle()
    val dark = state.theme == "dark" || (state.theme == "system" && isSystemInDarkTheme())
    val colors =
        if (dark)
            darkColorScheme(
                primary = Color(0xFFABA0FF),
                background = Color(0xFF10151F),
                surface = Color(0xFF161E2B),
            )
        else lightColorScheme(primary = Color(0xFF6957D9), background = Color(0xFFF5F6FA))
    MaterialTheme(colorScheme = colors) {
        var page by rememberSaveable { mutableIntStateOf(0) }
        val labels =
            listOf(
                R.string.home,
                R.string.chat,
                R.string.models,
                R.string.settings,
                R.string.diagnostics,
            )
        val icons =
            listOf(
                Icons.Default.Home,
                Icons.Default.Chat,
                Icons.Default.Storage,
                Icons.Default.Settings,
                Icons.Default.Info,
            )
        BoxWithConstraints(Modifier.fillMaxSize()) {
            val wide = maxWidth >= 800.dp
            Row(Modifier.fillMaxSize().background(colors.background)) {
                if (wide)
                    NavigationRail {
                        labels.forEachIndexed { i, label ->
                            NavigationRailItem(
                                selected = page == i,
                                onClick = { page = i },
                                icon = { Icon(icons[i], stringResource(label)) },
                                label = { Text(stringResource(label)) },
                            )
                        }
                    }
                Scaffold(
                    Modifier.weight(1f).testTag("app"),
                    topBar = {
                        TopAppBar(
                            title = {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Icon(
                                        painterResource(R.drawable.ic_omnicore),
                                        null,
                                        Modifier.size(34.dp),
                                        tint = Color.Unspecified,
                                    )
                                    Spacer(Modifier.width(10.dp))
                                    Text("OmniCore")
                                }
                            },
                            actions = {
                                TextButton(
                                    onClick = { if (state.connected) vm.refresh() else page = 3 },
                                    enabled = !state.busy,
                                ) {
                                    Text(
                                        stringResource(
                                            if (state.connected) R.string.connected
                                            else R.string.disconnected
                                        )
                                    )
                                }
                            },
                        )
                    },
                    bottomBar = {
                        if (!wide)
                            NavigationBar {
                                labels.forEachIndexed { i, label ->
                                    NavigationBarItem(
                                        selected = page == i,
                                        onClick = { page = i },
                                        icon = { Icon(icons[i], stringResource(label)) },
                                        label = {
                                            Text(
                                                stringResource(label),
                                                maxLines = 1,
                                                overflow = TextOverflow.Ellipsis,
                                            )
                                        },
                                        modifier = Modifier.testTag("nav_$i"),
                                    )
                                }
                            }
                    },
                ) { padding ->
                    Column(Modifier.padding(padding).fillMaxSize()) {
                        if (state.busy)
                            LinearProgressIndicator(Modifier.fillMaxWidth().testTag("busy"))
                        state.error?.let { ErrorBanner(it, vm::dismissError) }
                        Box(Modifier.weight(1f).fillMaxWidth()) {
                            when (page) {
                                0 -> HomeScreen(state, vm) { page = it }
                                1 -> ChatScreen(state, vm)
                                2 -> ModelsScreen(state, vm)
                                3 -> SettingsScreen(state, vm, onLanguage)
                                4 -> DiagnosticsScreen(state, vm)
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun ErrorBanner(code: String, dismiss: () -> Unit) {
    val text =
        when (code) {
            "connection_error",
            "not_connected" -> R.string.error_connection
            "token_for_new_host" -> R.string.error_new_host
            "unauthorized" -> R.string.error_auth
            "invalid_url" -> R.string.error_url
            "https_required" -> R.string.error_https
            "invalid_token" -> R.string.error_token
            "token_unavailable" -> R.string.error_keystore
            "model_required" -> R.string.error_model
            "conversation_required" -> R.string.error_conversation
            "out_of_memory" -> R.string.error_memory
            "engine_unavailable" -> R.string.error_engine
            "stream_disconnected" -> R.string.error_stream
            else -> R.string.error_generic
        }
    Surface(
        color = MaterialTheme.colorScheme.errorContainer,
        shape = MaterialTheme.shapes.medium,
        modifier = Modifier.fillMaxWidth().padding(12.dp),
    ) {
        Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(stringResource(text, code), Modifier.weight(1f).testTag("error"))
            IconButton(onClick = dismiss) {
                Icon(Icons.Default.Close, stringResource(R.string.dismiss))
            }
        }
    }
}

@Composable
private fun HomeScreen(s: UiState, vm: OmniViewModel, navigate: (Int) -> Unit) {
    val title = stringResource(R.string.new_chat)
    LazyColumn(
        Modifier.fillMaxSize().padding(horizontal = 20.dp),
        contentPadding = PaddingValues(vertical = 20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item {
            Text(stringResource(R.string.headline), style = MaterialTheme.typography.headlineMedium)
        }
        item { Text(stringResource(R.string.home_hint)) }
        item {
            ElevatedCard(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text(
                        stringResource(
                            if (s.connected) R.string.connected else R.string.disconnected
                        ),
                        style = MaterialTheme.typography.titleLarge,
                    )
                    Text(s.url.ifBlank { stringResource(R.string.url_example) })
                    Text(stringResource(R.string.models_count, s.models.size))
                    Button(onClick = { navigate(if (s.connected) 1 else 3) }) {
                        Text(stringResource(if (s.connected) R.string.chat else R.string.configure))
                    }
                }
            }
        }
        item {
            Button(
                onClick = {
                    vm.createConversation(title)
                    navigate(1)
                },
                enabled = s.connected && !s.busy && !s.generating,
                modifier = Modifier.fillMaxWidth().testTag("home_new"),
            ) {
                Icon(Icons.Default.Add, null)
                Text(title)
            }
        }
        item { Text(stringResource(R.string.recent), style = MaterialTheme.typography.titleLarge) }
        items(s.conversations.take(8), key = { it.id }) { c ->
            OutlinedCard(
                onClick = {
                    vm.openConversation(c.id)
                    navigate(1)
                },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(c.title.ifBlank { title }, Modifier.padding(20.dp))
            }
        }
    }
}

@Composable
private fun ChatScreen(s: UiState, vm: OmniViewModel) {
    val title = stringResource(R.string.new_chat)
    var rename by remember { mutableStateOf(false) }
    var remove by remember { mutableStateOf(false) }
    var edit by remember { mutableStateOf("") }
    Column(Modifier.fillMaxSize().padding(horizontal = 12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Choice(
                s.conversations.map { it.id to it.title.ifBlank { title } },
                s.selectedConversation,
                stringResource(R.string.choose_conversation),
                vm::openConversation,
                Modifier.weight(1f),
                !s.generating && !s.busy,
            )
            IconButton(
                onClick = { vm.createConversation(title) },
                enabled = s.connected && !s.busy && !s.generating,
                modifier = Modifier.testTag("new_chat"),
            ) {
                Icon(Icons.Default.Add, title)
            }
            IconButton(
                onClick = {
                    edit = s.conversations.find { it.id == s.selectedConversation }?.title.orEmpty()
                    rename = true
                },
                enabled = s.selectedConversation != null && !s.generating && !s.busy,
            ) {
                Icon(Icons.Default.Edit, stringResource(R.string.rename))
            }
            IconButton(
                onClick = { remove = true },
                enabled = s.selectedConversation != null && !s.generating && !s.busy,
            ) {
                Icon(Icons.Default.Delete, stringResource(R.string.delete))
            }
        }
        Choice(
            s.models.map { it.id to "${it.name} · ${it.backend}" },
            s.selectedModel,
            stringResource(R.string.choose_model),
            vm::selectModel,
            Modifier.fillMaxWidth(),
            !s.generating,
        )
        if (s.models.isEmpty())
            Text(
                stringResource(R.string.no_models),
                Modifier.padding(12.dp),
                style = MaterialTheme.typography.bodySmall,
            )
        val messages =
            s.messages.filterNot { it.generationId != null && it.generationId == s.generation?.id }
        val scroll = androidx.compose.foundation.lazy.rememberLazyListState()
        LaunchedEffect(messages.size, s.generation?.sequence) {
            val count = messages.size + if (s.generation != null) 1 else 0
            if (count > 0) scroll.animateScrollToItem(count - 1)
        }
        LazyColumn(
            Modifier.weight(1f).fillMaxWidth().testTag("messages"),
            state = scroll,
            verticalArrangement = Arrangement.spacedBy(12.dp),
            contentPadding = PaddingValues(vertical = 12.dp),
        ) {
            items(messages) { MessageBubble(it.role, it.content) }
            s.generation?.let { item { MessageBubble("assistant", it.content) } }
            if (s.selectedConversation == null)
                item { Text(stringResource(R.string.no_conversations), Modifier.padding(16.dp)) }
        }
        s.generation?.let { job ->
            Text(
                stringResource(
                    when (job.state) {
                        "queued" -> R.string.queued
                        "running" -> R.string.running
                        "completed" -> R.string.completed
                        "cancelled" -> R.string.cancelled
                        "interrupted" -> R.string.interrupted
                        else -> R.string.failed
                    }
                ) + (job.tokensPerSecond?.let { " · %.1f tok/s".format(it) } ?: ""),
                style = MaterialTheme.typography.labelMedium,
                modifier = Modifier.testTag("generation_status"),
            )
        }
        Row(Modifier.imePadding().padding(vertical = 8.dp), verticalAlignment = Alignment.Bottom) {
            OutlinedTextField(
                s.draft,
                vm::draft,
                label = { Text(stringResource(R.string.composer)) },
                modifier = Modifier.weight(1f).heightIn(max = 150.dp).testTag("composer"),
                maxLines = 5,
                enabled = !s.generating && !s.busy,
            )
            if (s.generating)
                IconButton(onClick = vm::cancel, modifier = Modifier.size(56.dp).testTag("stop")) {
                    Icon(Icons.Default.StopCircle, stringResource(R.string.stop))
                }
            else
                IconButton(
                    onClick = vm::send,
                    enabled = s.connected && !s.busy && s.draft.isNotBlank(),
                    modifier = Modifier.size(56.dp).testTag("send"),
                ) {
                    Icon(Icons.AutoMirrored.Filled.Send, stringResource(R.string.send))
                }
        }
    }
    if (rename)
        AlertDialog(
            onDismissRequest = { rename = false },
            title = { Text(stringResource(R.string.rename)) },
            text = {
                OutlinedTextField(
                    edit,
                    { edit = it.take(256) },
                    label = { Text(stringResource(R.string.conversation_title)) },
                )
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        s.selectedConversation?.let { vm.rename(it, edit) }
                        rename = false
                    },
                    enabled = edit.isNotBlank(),
                ) {
                    Text(stringResource(R.string.save))
                }
            },
            dismissButton = {
                TextButton(onClick = { rename = false }) { Text(stringResource(R.string.cancel)) }
            },
        )
    if (remove)
        ConfirmDialog(R.string.delete_chat, { remove = false }) {
            s.selectedConversation?.let(vm::delete)
            remove = false
        }
}

@Composable
private fun MessageBubble(role: String, content: String) {
    val clipboard = LocalClipboardManager.current
    Surface(
        shape = MaterialTheme.shapes.large,
        modifier = Modifier.fillMaxWidth(),
        color =
            if (role == "user") MaterialTheme.colorScheme.secondaryContainer
            else MaterialTheme.colorScheme.surfaceContainer,
    ) {
        Column(Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    stringResource(if (role == "user") R.string.you else R.string.assistant),
                    Modifier.weight(1f),
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.primary,
                )
                if (role != "user" && content.isNotBlank())
                    IconButton(
                        onClick = { clipboard.setText(AnnotatedString(content)) },
                        modifier = Modifier.size(40.dp),
                    ) {
                        Icon(
                            Icons.Default.ContentCopy,
                            stringResource(R.string.copy),
                            Modifier.size(18.dp),
                        )
                    }
            }
            SelectionContainer { Text(content, style = MaterialTheme.typography.bodyLarge) }
        }
    }
}

@Composable
private fun Choice(
    items: List<Pair<String, String>>,
    selected: String?,
    hint: String,
    select: (String) -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    var expanded by remember { mutableStateOf(false) }
    Box(modifier) {
        OutlinedButton(
            onClick = { expanded = true },
            enabled = enabled && items.isNotEmpty(),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text(
                items.find { it.first == selected }?.second ?: hint,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Icon(Icons.Default.ArrowDropDown, null)
        }
        DropdownMenu(expanded, { expanded = false }, Modifier.heightIn(max = 320.dp)) {
            items.forEach { item ->
                DropdownMenuItem(
                    text = { Text(item.second) },
                    onClick = {
                        expanded = false
                        select(item.first)
                    },
                )
            }
        }
    }
}

@Composable
private fun ModelsScreen(s: UiState, vm: OmniViewModel) {
    var importing by remember { mutableStateOf(false) }
    var path by remember { mutableStateOf("") }
    var removing by remember { mutableStateOf<ModelInfo?>(null) }
    LazyColumn(
        Modifier.fillMaxSize().padding(horizontal = 16.dp),
        contentPadding = PaddingValues(vertical = 16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item {
            Row {
                Text(
                    stringResource(R.string.models),
                    Modifier.weight(1f),
                    style = MaterialTheme.typography.headlineSmall,
                )
                IconButton(onClick = vm::refresh, enabled = s.connected && !s.busy) {
                    Icon(Icons.Default.Refresh, stringResource(R.string.refresh))
                }
            }
        }
        item {
            OutlinedButton(
                onClick = { importing = true },
                enabled = s.connected && !s.busy && !s.generating,
            ) {
                Text(stringResource(R.string.import_model))
            }
        }
        if (s.models.isEmpty()) item { Text(stringResource(R.string.no_models)) }
        items(s.models, key = { it.id }) { model ->
            ElevatedCard(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(model.name, style = MaterialTheme.typography.titleMedium)
                    Text(
                        "${model.backend} · ${model.format} · ${model.quantization.orEmpty()} · ${size(model.sizeBytes)}"
                    )
                    Text(
                        stringResource(
                            when (model.compatibility) {
                                "tested" -> R.string.tested
                                "load_verified" -> R.string.load_verified
                                "unsupported" -> R.string.unsupported
                                else -> R.string.unverified
                            }
                        )
                    )
                    Text(
                        stringResource(R.string.license) +
                            ": " +
                            (model.license ?: stringResource(R.string.unknown))
                    )
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        TextButton(onClick = { vm.selectModel(model.id) }) {
                            Text(stringResource(R.string.choose_model))
                        }
                        IconButton(
                            onClick = { removing = model },
                            enabled = !s.busy && !s.generating,
                        ) {
                            Icon(Icons.Default.Delete, stringResource(R.string.remove_entry))
                        }
                    }
                    Row {
                        if (model.backend == "llama.cpp")
                            TextButton(
                                onClick = { vm.loadModel(model.id) },
                                enabled = !s.busy && !s.generating,
                            ) {
                                Text(stringResource(R.string.load))
                            }
                        TextButton(
                            onClick = { vm.unloadModel(model.id) },
                            enabled = !s.busy && !s.generating,
                        ) {
                            Text(stringResource(R.string.unload))
                        }
                    }
                }
            }
        }
        item { Text(stringResource(R.string.engines), style = MaterialTheme.typography.titleLarge) }
        items(s.engines) { EngineCard(it) }
    }
    if (importing)
        AlertDialog(
            onDismissRequest = { importing = false },
            title = { Text(stringResource(R.string.import_model)) },
            text = {
                Column {
                    Text(stringResource(R.string.import_hint))
                    OutlinedTextField(
                        path,
                        { path = it },
                        label = { Text(stringResource(R.string.backend_path)) },
                    )
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        vm.importModel(path)
                        importing = false
                    },
                    enabled = path.startsWith('/'),
                ) {
                    Text(stringResource(R.string.confirm))
                }
            },
            dismissButton = {
                TextButton(onClick = { importing = false }) {
                    Text(stringResource(R.string.cancel))
                }
            },
        )
    removing?.let { model ->
        ConfirmDialog(R.string.remove_model, { removing = null }) {
            vm.removeModel(model.id)
            removing = null
        }
    }
}

@Composable
private fun SettingsScreen(s: UiState, vm: OmniViewModel, onLanguage: (String) -> Unit) {
    var url by remember(s.url) { mutableStateOf(s.url) }
    var token by remember { mutableStateOf("") }
    var clear by remember { mutableStateOf(false) }
    var trusted by remember(s.trustedLan) { mutableStateOf(s.trustedLan) }
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text(stringResource(R.string.settings), style = MaterialTheme.typography.headlineSmall)
        Text(stringResource(R.string.connection_hint))
        OutlinedTextField(
            url,
            { url = it },
            label = { Text(stringResource(R.string.backend_url)) },
            placeholder = { Text(stringResource(R.string.url_example)) },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
            modifier = Modifier.fillMaxWidth().testTag("url"),
        )
        OutlinedTextField(
            token,
            { token = it },
            label = { Text(stringResource(R.string.api_token)) },
            supportingText = { Text(stringResource(R.string.token_hint)) },
            visualTransformation = PasswordVisualTransformation(),
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
            modifier = Modifier.fillMaxWidth().testTag("token"),
        )
        if (s.hasToken)
            Text(stringResource(R.string.token_saved), style = MaterialTheme.typography.bodySmall)
        Row(verticalAlignment = Alignment.CenterVertically) {
            Checkbox(clear, { clear = it })
            Text(stringResource(R.string.clear_token))
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Checkbox(trusted, { trusted = it }, modifier = Modifier.testTag("trusted_lan"))
            Text(stringResource(R.string.trusted_lan))
        }
        Button(
            onClick = {
                vm.saveConnection(url, token, clear, trusted)
                token = ""
                clear = false
            },
            enabled = !s.busy && !s.generating,
            modifier = Modifier.fillMaxWidth().testTag("connect"),
        ) {
            Text(stringResource(R.string.connect))
        }
        Text(stringResource(R.string.theme), style = MaterialTheme.typography.titleMedium)
        Choice(
            listOf(
                "system" to stringResource(R.string.system),
                "light" to stringResource(R.string.light),
                "dark" to stringResource(R.string.dark),
            ),
            s.theme,
            stringResource(R.string.theme),
            vm::setTheme,
            Modifier.fillMaxWidth(),
        )
        Text(stringResource(R.string.language), style = MaterialTheme.typography.titleMedium)
        Choice(
            listOf("en-US" to "English", "pl-PL" to "Polski"),
            s.language,
            stringResource(R.string.language),
            onLanguage,
            Modifier.fillMaxWidth(),
        )
        Text(stringResource(R.string.about), style = MaterialTheme.typography.bodySmall)
        Spacer(Modifier.height(30.dp))
    }
}

@Composable
private fun DiagnosticsScreen(s: UiState, vm: OmniViewModel) {
    LazyColumn(
        Modifier.fillMaxSize().padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item {
            Text(
                stringResource(R.string.diagnostics),
                style = MaterialTheme.typography.headlineSmall,
            )
        }
        item {
            Text(stringResource(R.string.diagnostics_hint))
            Text(s.url)
            Text(stringResource(if (s.connected) R.string.connected else R.string.disconnected))
        }
        item {
            Button(onClick = vm::connect, enabled = !s.busy) {
                Text(stringResource(R.string.reconnect))
            }
        }
        s.generation?.let { record ->
            item { Text(stringResource(R.string.current_job) + ": ${record.id} · ${record.state}") }
        }
        items(s.engines) { EngineCard(it) }
    }
}

@Composable
private fun EngineCard(record: EngineDiagnostic) {
    OutlinedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(record.info.id, style = MaterialTheme.typography.titleMedium)
            Text(
                stringResource(
                    if (record.info.available) R.string.available else R.string.unavailable
                )
            )
            Text(record.info.version ?: stringResource(R.string.unknown))
            Text(
                stringResource(R.string.ram) +
                    ": " +
                    (record.info.resources.ram?.let(::size) ?: "—")
            )
            Text(
                stringResource(R.string.vram) +
                    ": " +
                    (record.info.resources.vram?.let(::size) ?: "—")
            )
            Text(
                stringResource(R.string.gpu) +
                    ": " +
                    record.gpuDevices.joinToString().ifBlank { stringResource(R.string.none) }
            )
        }
    }
}

@Composable
private fun ConfirmDialog(text: Int, dismiss: () -> Unit, confirm: () -> Unit) {
    AlertDialog(
        onDismissRequest = dismiss,
        title = { Text(stringResource(R.string.confirm)) },
        text = { Text(stringResource(text)) },
        confirmButton = {
            TextButton(onClick = confirm) { Text(stringResource(R.string.confirm)) }
        },
        dismissButton = { TextButton(onClick = dismiss) { Text(stringResource(R.string.cancel)) } },
    )
}

private fun size(bytes: Long): String =
    if (bytes >= 1024L * 1024 * 1024) "%.2f GiB".format(bytes / (1024.0 * 1024 * 1024))
    else "%.1f MiB".format(bytes / (1024.0 * 1024))
