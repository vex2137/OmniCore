"""Structured, sanitized technical descriptions for UI and agent error cards."""

from __future__ import annotations

import re

SAFE_COMPONENT_RE = re.compile(r"[^A-Za-z0-9_.:/-]+")


def sanitize_component(value: str | None) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = SAFE_COMPONENT_RE.sub("", value.strip())
    return cleaned[:64]


def _default_component(code: str) -> str:
    if code in {"agent_folder_not_granted", "agent_invalid_grant", "agent_permission_denied"}:
        return "file_permissions"
    if code in {"agent_path_not_found", "agent_sensitive_file", "agent_file_limit"}:
        return "file_tools"
    if code.startswith("agent_web_"):
        return "web_tools"
    if code.startswith("agent_protocol") or code in {
        "agent_incomplete_response",
        "agent_model_unsupported",
        "agent_model_error",
    }:
        return "agent_protocol"
    if code.startswith("agent_"):
        return "agent_loop"
    if code in {
        "out_of_memory",
        "model_load_failed",
        "cuda_runtime_unavailable",
        "gpu_unavailable",
        "llama_unavailable",
        "engine_unavailable",
    }:
        return "llama.cpp"
    if code in {"connection_error", "backend_exited", "backend_process_error"}:
        return "backend_api"
    return "omnicore"


def _cause_and_solution(code: str, is_pl: bool) -> tuple[str, str]:
    table_pl = {
        "agent_folder_not_granted": (
            "Rozmowa nie posiada aktywnego dostępu do folderu docelowego.",
            "Kliknij „Udostępnij folder”, wskaż katalog i wybierz „Kontynuuj zadanie”.",
        ),
        "agent_invalid_grant": (
            "Użyty identyfikator uprawnienia (grant_id) jest nieaktualny lub błędny.",
            "Sprawdź listę udostępnionych folderów albo udostępnij docelowy katalog ponownie.",
        ),
        "agent_permission_denied": (
            "Dostęp odrzucony przez ograniczenia zakresu "
            "(np. tylko odczyt, brak podfolderów lub cofnięte uprawnienie).",
            "Rozszerz zakres uprawnień wybranego folderu albo udostępnij właściwy katalog.",
        ),
        "agent_path_not_found": (
            "Wskazany plik lub podkatalog nie istnieje w obrębie udostępnionego folderu.",
            "Sprawdź poprawność nazwy pliku/ścieżki lub wylistuj zawartość folderu.",
        ),
        "agent_sensitive_file": (
            "Plik pasuje do wzorca wrażliwej konfiguracji (np. klucze, sekrety, ukryte pliki).",
            "Jeśli świadomie chcesz na nim pracować, udostępnij folder ze zgodą na pliki wrażliwe.",
        ),
        "agent_invalid_arguments": (
            "Model przekazał niepoprawne lub brakujące argumenty wywołania narzędzia.",
            "Ponów próbę albo sprawdź zgodność modelu / przełącz protokół na JSON.",
        ),
        "agent_tool_invalid_arguments": (
            "Model przekazał niepoprawne lub brakujące argumenty wywołania narzędzia.",
            "Ponów próbę albo sprawdź zgodność modelu / przełącz protokół na JSON.",
        ),
        "agent_unknown_tool": (
            "Model próbował wywołać narzędzie spoza dozwolonego zestawu OmniCore.",
            "Ponów zadanie lub użyj modelu zgodnego z narzędziami (Qwen / DeepSeek / JSON).",
        ),
        "agent_protocol_invalid": (
            "Odpowiedź modelu nie spełniła formatu protokołu narzędzi agenta.",
            "Przełącz protokół na JSON w ustawieniach agenta lub wybierz zgodny model.",
        ),
        "agent_incomplete_response": (
            "Generowanie przerwane po osiągnięciu limitu tokenów przed domknięciem wywołania.",
            "Zwiększ limit długości odpowiedzi/kontekstu lub uprość polecenie.",
        ),
        "agent_model_unsupported": (
            "Bieżący model nie przeszedł testu wywoływania narzędzi w trybie Auto.",
            "Uruchom test zgodności modelu lub przełącz protokół agenta na JSON.",
        ),
        "agent_step_limit": (
            "Zadanie osiągnęło limit kroków agenta przed uzyskaniem finalnej odpowiedzi.",
            "Zwiększ limit kroków w ustawieniach agenta albo doprecyzuj polecenie.",
        ),
        "agent_context_limit": (
            "Suma promptu i wyników narzędzi przekroczyła wybrany limit kontekstu modelu.",
            "Zwiększ kontekst modelu w ustawieniach (⚙) albo rozpocznij nową rozmowę.",
        ),
        "agent_timeout": (
            "Zadanie agenta przekroczyło maksymalny dozwolony czas wykonania.",
            "Sprawdź działanie silnika lub uruchom zadanie o mniejszym zakresie.",
        ),
        "agent_tool_timeout": (
            "Pojedyncze narzędzie nie zakończyło pracy w wymaganym limicie czasu.",
            "Sprawdź czy folder nie ma bardzo głębokich katalogów albo powolnych dysków.",
        ),
        "agent_tool_execution_failed": (
            "System lub narzędzie zgłosiło nieoczekiwany błąd operacji wejścia/wyjścia.",
            "Zweryfikuj stan docelowego pliku/katalogu oraz logi diagnostyczne.",
        ),
        "agent_tool_error": (
            "Operacja narzędzia zakończyła się niepowodzeniem.",
            "Sprawdź szczegóły kroku oraz uprawnienia folderu.",
        ),
        "agent_web_disabled": (
            "Narzędzia internetowe są wyłączone dla bieżącej rozmowy.",
            "Włącz opcję „Dostęp do internetu” w ustawieniach agenta (⚙), aby korzystać z sieci.",
        ),
        "out_of_memory": (
            "Zabrakło pamięci VRAM (GPU) lub RAM dla wybranego kontekstu i warstw modelu.",
            "Ustaw tryb warstw na Auto, zmniejsz warstwy GPU albo wybierz mniejszy kontekst.",
        ),
        "model_load_failed": (
            "Silnik llama-server zakończył uruchamianie błędem przed gotowością.",
            "Sprawdź kompletność pliku GGUF, zmniejsz kontekst lub sprawdź diagnostykę silnika.",
        ),
        "cuda_runtime_unavailable": (
            "Silnik CUDA nie mógł zainicjalizować bibliotek lub sterownika GPU.",
            "Sprawdź sterownik NVIDIA w Diagnostyce lub wybierz tryb Auto / CPU.",
        ),
        "gpu_unavailable": (
            "Brak działającego urządzenia GPU w konfiguracji silnika.",
            "Przełącz tryb pracy na Auto lub CPU albo sprawdź sekcję Diagnostyka.",
        ),
        "llama_unavailable": (
            "Plik binarny llama-server jest niedostępny lub nie odpowiada.",
            "Zweryfikuj ścieżkę silnika w Ustawieniach oraz status w Diagnostyce.",
        ),
        "engine_unavailable": (
            "Wybrany backend modelu nie odpowiada.",
            "Sprawdź czy usługa silnika działa i kliknij Odśwież / Diagnostyka.",
        ),
        "connection_error": (
            "Aplikacja desktopowa utraciła połączenie z lokalnym API backendu.",
            "Kliknij „Połącz ponownie” w górnym pasku lub sprawdź zakładkę Diagnostyka.",
        ),
        "model_required": (
            "Nie wybrano żadnego aktywnego modelu dla rozmowy.",
            "Wybierz model na pasku u góry czatu lub zaimportuj plik GGUF w zakładce Modele.",
        ),
        "conversation_busy": (
            "W tej rozmowie nadal trwa aktywne generowanie albo zadanie agenta.",
            "Zaczekaj na zakończenie lub kliknij „Zatrzymaj”.",
        ),
        "busy": (
            "Backend wykonuje obecnie inną operację blokującą zmianę zasobu.",
            "Zaczekaj chwilę na zakończenie bieżącego zadania.",
        ),
    }
    table_en = {
        "agent_folder_not_granted": (
            "This conversation does not have active access to the requested folder.",
            "Click “Share folder”, pick the target directory, then click “Continue task”.",
        ),
        "agent_invalid_grant": (
            "The supplied folder permission grant (grant_id) is invalid, stale, or ambiguous.",
            "Review shared folders or grant access to the target folder again.",
        ),
        "agent_permission_denied": (
            "Path access was blocked by grant restrictions (read-only, no subfolders, or revoked).",
            "Adjust permissions or re-share the target folder with required access.",
        ),
        "agent_path_not_found": (
            "The requested file or subdirectory does not exist in the granted folder.",
            "Check the filename/path or list the directory first.",
        ),
        "agent_sensitive_file": (
            "The file matches a sensitive configuration pattern (keys, secrets, dotfiles).",
            "Re-share the folder with sensitive file access enabled only if intended.",
        ),
        "agent_invalid_arguments": (
            "The model provided invalid or missing tool arguments.",
            "Retry the task, or switch the agent protocol to JSON.",
        ),
        "agent_tool_invalid_arguments": (
            "The model provided invalid or missing tool arguments.",
            "Retry the task, or switch the agent protocol to JSON.",
        ),
        "agent_unknown_tool": (
            "The model called an unknown tool name.",
            "Retry the task or use a model with stronger tool calling support.",
        ),
        "agent_protocol_invalid": (
            "Model output did not match the expected agent tool protocol.",
            "Switch agent protocol to JSON or run the compatibility check.",
        ),
        "agent_incomplete_response": (
            "Generation hit the output token limit before completing a valid call or answer.",
            "Increase max output tokens / model context or narrow the task.",
        ),
        "agent_model_unsupported": (
            "This model failed the tool compatibility check in Auto mode.",
            "Run the model compatibility test or switch protocol to JSON.",
        ),
        "agent_step_limit": (
            "The agent reached its step budget before producing a final answer.",
            "Increase the step limit in Agent settings or refine your prompt.",
        ),
        "agent_context_limit": (
            "Conversation plus tool output exceeded the configured model context size.",
            "Increase the model context size (⚙) or start a new conversation.",
        ),
        "agent_timeout": (
            "The agent run exceeded the overall execution timeout.",
            "Try a smaller task or verify model speed in Diagnostics.",
        ),
        "agent_tool_timeout": (
            "A tool invocation timed out before finishing.",
            "Verify the target folder is accessible and not excessively large.",
        ),
        "agent_tool_execution_failed": (
            "A local I/O or execution error occurred inside the tool.",
            "Check target file/directory permissions and Diagnostic logs.",
        ),
        "agent_tool_error": (
            "Tool execution reported an error.",
            "Inspect step details and folder permissions.",
        ),
        "agent_web_disabled": (
            "Web search and fetch tools are disabled for this conversation.",
            "Enable “Web access” in Agent settings (⚙) if online lookup is intended.",
        ),
        "out_of_memory": (
            "Insufficient VRAM or system RAM for the model, context size, and GPU layers.",
            "Use Auto GPU offload, reduce GPU layers, or lower the context window.",
        ),
        "model_load_failed": (
            "llama-server exited with an error while loading the GGUF model.",
            "Verify the GGUF file integrity, reduce context size, or check Diagnostics.",
        ),
        "cuda_runtime_unavailable": (
            "CUDA engine could not initialize its runtime libraries or GPU driver.",
            "Check NVIDIA driver status in Diagnostics or switch to Auto / CPU.",
        ),
        "gpu_unavailable": (
            "No usable GPU device was found by the engine.",
            "Use Auto / CPU mode or inspect Diagnostics.",
        ),
        "llama_unavailable": (
            "The llama-server binary is missing or failed to respond.",
            "Check engine path in Settings and inspect Diagnostics.",
        ),
        "engine_unavailable": (
            "The selected inference backend did not respond.",
            "Ensure the local engine is available and refresh status.",
        ),
        "connection_error": (
            "Desktop client lost connection to the local backend API.",
            "Click “Reconnect” or check Diagnostics.",
        ),
        "model_required": (
            "No active model is selected for this conversation.",
            "Choose a model from the header selector or import a GGUF in Models.",
        ),
        "conversation_busy": (
            "A generation or agent run is already active in this conversation.",
            "Wait for completion or click “Stop”.",
        ),
        "busy": (
            "Backend is currently busy with an active task.",
            "Wait for the active task to finish before modifying this resource.",
        ),
    }
    table = table_pl if is_pl else table_en
    if code in table:
        return table[code]
    if is_pl:
        return (
            "Operacja zwróciła błąd zgłoszony przez backend lub warstwę interfejsu.",
            "Sprawdź szczegóły techniczne, ustawienia trybu oraz ekran Diagnostyka.",
        )
    return (
        "The backend or UI layer reported an execution error.",
        "Review technical details, current settings, and Diagnostics.",
    )


def describe_error(
    code: str | None,
    tr,
    *,
    component: str | None = None,
    target: str | None = None,
) -> dict[str, str]:
    """Return structured, secret-free card fields for any error code."""
    catalog = getattr(tr, "catalog", {})
    safe_code = code if (isinstance(code, str) and code in catalog) else "unknown_error"
    is_pl = tr("you") == "Ty"
    title = tr(safe_code)
    comp = sanitize_component(component) or _default_component(safe_code)
    cause, solution = _cause_and_solution(safe_code, is_pl)
    if target and isinstance(target, str):
        safe_target = target.strip().splitlines()[0][:80]
        if safe_target:
            comp = f"{comp} ({safe_target})" if safe_target not in comp else comp
    return {
        "title": title,
        "code": safe_code,
        "component": comp,
        "cause": cause,
        "solution": solution,
    }
