# OmniCore 0.2.0 — Agents Beta 1 (source checkpoint)

Base: RC8 `e0e968682f4019c3775d80c5f696451e21b3a2a9`.
No release, installer, dependency update or stable version change.

## Local test (Linux)

Run from this branch, using the existing engine configuration:

```fish
uv sync --frozen --group gui-test
uv run --frozen omnicore-desktop
```

1. Import/select a compatible local GGUF (llama.cpp), or select a discovered
   Ollama model. Preserve your existing CPU/GPU and generation parameters.
2. Create a conversation, select **Agent**, and **Share folder**. Use a scratch
   directory containing `notes.txt`; leave private configuration access disabled.
3. Ask: “Read notes.txt, calculate (2 + 3) * 7, then propose saving a summary
   to summary.txt.” Review the tool history, diff and **Approve / Reject**.
   The model must obtain a successful tool result before claiming a write.
4. Try rejection, Stop, revoking the folder, and reopening the conversation.
   Previous statuses and mode remain; backend restart requires granting folders
   again. Pending writes are interrupted/cancelled, never automatically replayed.

The fallback requires a complete JSON object, for example:
`{"kind":"tool","name":"read_text","arguments":{"grant_id":"ID","path":"notes.txt"}}`
or `{"kind":"final","text":"Answer"}`. Native tool calls are enabled for
Ollama models advertising tool-calling; llama.cpp uses the strict JSON adapter.
Plain text, malformed JSON and truncated responses do not execute tools.
Use a model with sufficient context for tool schemas, history and results.
Model compatibility is not inferred from its filename or GGUF format alone.

## Boundaries

- Six tools only: listing, UTF-8 reading, filename search, file metadata,
  proposed text replacement/creation, bounded AST arithmetic. No shell, scripts,
  internet, desktop automation or tool for granting/approving its own access.
- Folder capabilities are conversation-scoped and held as directory descriptors.
  Absolute paths, traversal, symlinks and hard-linked text files are rejected.
  Hidden/configuration-secret filenames need separate explicit consent.
- Text reads/writes: 64 KiB; listing: 200 entries; search: 4,000 visits,
  depth 12 and two seconds. Tool timeout: five seconds; approval: 180 seconds;
  overall run: ten minutes. Default eight tool steps, configurable 1–32.
- Writes are approved once against an ephemeral proposal nonce. Paths and
  contents are rechecked at commit. Creation cannot overwrite an existing file;
  Linux atomic exchange detects edit conflicts and retains the original inode
  as a hidden `.omnicore-backup-*` file (original permissions). These backups are not auto-deleted.
  Cancellation waits for an already approved atomic commit before acknowledging;
  a completed approved write is recorded as completed, not falsely “cancelled”.
- SQLite keeps mode, limits, statuses, timings and result summaries in existing
  job records. Tool file contents, diffs and approval tokens are transient.
  The user's prompt and final answer remain ordinary conversation messages.
  Existing conversation JSON export remains the RC8 format (agent audit/settings
  are not included). Deleting a conversation also deletes its agent audit.
- File capabilities intentionally fail closed on systems without the required
  descriptor operations; atomic editing currently requires Linux renameat2.
  This is an application access boundary, not an OS sandbox against malicious
  processes already running as the same OS user.

## Verification limits

Automated tests use synthetic GGUF headers and controlled model transports.
Qt offscreen exercises actual HTTP, orchestration, filesystem reads, approval
and committed writes. This does not establish real GGUF tool-calling quality,
CUDA behavior, or native CachyOS/KDE/Wayland behavior. Those remain owner tests.
The desktop shows tool progress and the final answer; intermediate model planning
and partial protocol JSON are intentionally not displayed as chat messages.
