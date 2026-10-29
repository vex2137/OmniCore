package io.github.vex2137.omnicore

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp

/** All weights, Range retries and checksum verification stay on the backend. */
@Composable
fun ModelDownloads(s: UiState, vm: OmniViewModel) {
    var expanded by rememberSaveable { mutableStateOf(false) }
    var query by rememberSaveable { mutableStateOf("") }
    var confirmation by remember { mutableStateOf<RemoteFile?>(null) }
    OutlinedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            TextButton(
                onClick = { expanded = !expanded },
                modifier = Modifier.testTag("hub_toggle"),
            ) {
                Text(stringResource(R.string.huggingface))
            }
            if (expanded) {
                Text(stringResource(R.string.hub_hint))
                OutlinedTextField(
                    query,
                    { query = it.take(256) },
                    label = { Text(stringResource(R.string.hub_query)) },
                    modifier = Modifier.fillMaxWidth().testTag("hub_query"),
                    singleLine = true,
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(
                        onClick = { vm.searchHub(query) },
                        enabled = s.connected && !s.busy && query.isNotBlank(),
                        modifier = Modifier.testTag("hub_search"),
                    ) {
                        Text(stringResource(R.string.search))
                    }
                    OutlinedButton(
                        onClick = { vm.hubFiles(query) },
                        enabled = s.connected && !s.busy && query.contains('/'),
                        modifier = Modifier.testTag("hub_files"),
                    ) {
                        Text(stringResource(R.string.list_files))
                    }
                }
                s.repositories.forEach { repository ->
                    TextButton(
                        onClick = {
                            query = repository.id
                            vm.hubFiles(repository.id)
                        },
                        enabled = !s.busy,
                    ) {
                        Text(repository.id)
                    }
                }
                s.remoteFiles.forEach { file ->
                    HorizontalDivider()
                    Text(file.filename, style = MaterialTheme.typography.titleSmall)
                    Text(
                        "${file.sizeBytes} B · ${file.license ?: stringResource(R.string.unknown)}",
                        style = MaterialTheme.typography.bodySmall,
                    )
                    OutlinedButton(
                        onClick = { confirmation = file },
                        enabled = !s.busy && s.connected,
                        modifier = Modifier.testTag("download_file"),
                    ) {
                        Text(stringResource(R.string.download))
                    }
                }
            }
            if (s.downloads.isNotEmpty())
                Text(
                    stringResource(R.string.downloads),
                    style = MaterialTheme.typography.titleMedium,
                )
            s.downloads.forEach { record ->
                HorizontalDivider()
                Text(record.source.filename)
                Text(
                    stringResource(downloadStatus(record.state)) +
                        " · ${record.receivedBytes} / ${record.source.sizeBytes} B"
                )
                LinearProgressIndicator(
                    progress = { (record.percent / 100).toFloat().coerceIn(0f, 1f) },
                    modifier = Modifier.fillMaxWidth(),
                )
                record.errorCode?.let {
                    Text(
                        stringResource(R.string.error_generic, it),
                        color = MaterialTheme.colorScheme.error,
                    )
                }
                when (record.state) {
                    "queued",
                    "running" ->
                        TextButton(
                            onClick = { vm.cancelDownload(record.id) },
                            enabled = !s.busy && s.connected,
                            modifier = Modifier.testTag("download_cancel"),
                        ) {
                            Text(stringResource(R.string.cancel_download))
                        }
                    "failed",
                    "interrupted",
                    "cancelled" ->
                        TextButton(
                            onClick = { vm.resumeDownload(record.id) },
                            enabled = !s.busy && s.connected,
                            modifier = Modifier.testTag("download_resume"),
                        ) {
                            Text(stringResource(R.string.resume_download))
                        }
                    "completed" -> {
                        Text(
                            stringResource(
                                if (record.integrityVerified) R.string.integrity_verified
                                else R.string.integrity_unavailable
                            )
                        )
                        record.path?.let { path ->
                            TextButton(
                                onClick = { vm.importModel(path) },
                                enabled = !s.busy && !s.generating && s.connected,
                                modifier = Modifier.testTag("download_import"),
                            ) {
                                Text(stringResource(R.string.import_download))
                            }
                        }
                    }
                }
            }
        }
    }
    confirmation?.let { file ->
        AlertDialog(
            onDismissRequest = { confirmation = null },
            title = { Text(stringResource(R.string.confirm_download)) },
            text = {
                Text(
                    stringResource(
                        R.string.download_consent,
                        file.repository,
                        file.filename,
                        file.sizeBytes,
                        file.license ?: stringResource(R.string.unknown),
                    )
                )
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        vm.download(file)
                        confirmation = null
                    },
                    modifier = Modifier.testTag("download_confirm"),
                ) {
                    Text(stringResource(R.string.confirm))
                }
            },
            dismissButton = {
                TextButton(onClick = { confirmation = null }) {
                    Text(stringResource(R.string.cancel))
                }
            },
        )
    }
}

private fun downloadStatus(state: String) =
    when (state) {
        "queued" -> R.string.queued
        "running" -> R.string.downloading
        "completed" -> R.string.completed
        "cancelled" -> R.string.cancelled
        "interrupted" -> R.string.interrupted
        else -> R.string.failed
    }
