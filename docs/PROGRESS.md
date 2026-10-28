# OmniCore — PROGRESS

## Project Status

- **Current version:** 0.1.0 Alpha (`0.1.0a0`), fundament; bez wydania produktu.
- **Current milestone:** Etap 1 — Fundament: implementacja i walidacja wykonane,
  trwa zapis oraz publikacja etapu. Etapu 2 nie rozpoczęto.
- **Current development branch:** `feature/0.1.0-alpha`.
- **Last verified commit:** `270f2b924b6854c834a5472f7f39d05aea0a26dd`
  (zdalny punkt kontrolny dokumentacji, potwierdzony podczas bieżącego audytu).
- **Last update:** 2026-10-28 (Europe/Warsaw).

## Completed

- Zachowano wcześniejszą dokumentację, test dostępu GitHub i historię repozytorium.
- Odczytano wszystkie istniejące pliki i historię, wybrano zgodny z wymaganiami
  stos oraz zapisano plan i ryzyka w [ARCHITECTURE.md](ARCHITECTURE.md).
- Backend headless FastAPI z CLI, wersjonowanym REST i sprawdzaniem SQLite przez health.
- Trwałe ustawienia: PL/EN, system/light/dark, simple/advanced; zapis i odczyt po restarcie.
- SQLite: prywatny katalog i plik, transakcyjne migracje, rollback, zachowanie danych
  przy ponownym starcie i odmowa downgrade nowszej bazy.
- Schematy konfiguracji preferencji, metadanych modeli, adapterów i zdarzeń;
  snapshoty OpenAPI/JSON Schema oraz kontrola ich zgodności z kodem.
- Katalogi PL/EN z równymi kluczami, API tłumaczeń i wybór języka komunikatów błędów.
- WebSocket: powitanie z aktualnym stanem, ping/pong, rozsyłanie zmian ustawień,
  ograniczony bufor i sprzątanie po odłączeniu.
- Fundament bezpieczeństwa: domyślny loopback, jawny opt-in zdalnego dostępu,
  token, CORS, kontrola Origin/Host, limity żądań, brak sekretów w odpowiedziach.
- Interfejs adaptera i rejestr. Lista silników jest celowo pusta; nie ma atrap inferencji.
- Przypięte zależności uv.lock, instrukcje uruchamiania, workflow CI bez GPU,
  testy i działający smoke test prawdziwego procesu.
- Zbudowano sdist i wheel; wheel zainstalowano do osobnego środowiska bez narzędzi
  deweloperskich i uruchomiono jego HTTP/WS oraz test trwałości po restarcie.
- Uruchomiono także udokumentowane polecenie startu z katalogiem `.local-data`;
  działający proces odpowiedział poprawnie na health i żądanie katalogu PL.
- Zapisano w szkicu konfiguracji środowiska `install_script` i `start_skill`.
  Skrypt instalacji sprawdzono ponownie; zapis szkicu nie publikuje środowiska.

## In Progress

- Zapis etapu w Git, push gałęzi funkcjonalnej i potwierdzenie zdalnego SHA.

## Planned Next

1. Zakończyć raport Etapu 1 i zatrzymać pracę przed Etapem 2.
2. W następnym zadaniu: adaptery Ollama/llama.cpp, menedżer modeli, czat,
   streaming, historia i import/eksport rozmów wraz z testami rzeczywistej inferencji.
3. Dopiero w Etapie 3: ComfyUI i sprawdzone workflowy, kolejka, obrazy, LoRA.
4. Dopiero w Etapie 4: natywne Linux/Android i Web; renderowanie oraz testy motywów.

## Known Issues

- To fundament, nie kompletna Alpha. Brak inferencji, czatu, pobierania/importu
  modeli, ComfyUI, generowania obrazów, galerii i aplikacji klienckich.
- Nie potwierdzono zgodności żadnego modelu ani sprzętu GPU. CachyOS/RTX 4060,
  NVIDIA/AMD/Intel, OOM i anulowanie generowania wymagają późniejszych testów.
- Testy motywów w Etapie 1 dotyczą trwałych preferencji; nie testują wyglądu UI.
- Test rejestru używa test double tylko do probe; nie jest testem integracji silnika.
- Jeden proces backendu: bufor zdarzeń nie jest współdzielony między workerami.
  Wolny klient otrzymuje ostatnie snapshoty; nie jest to trwała historia zdarzeń.
- Zdalne użycie wymaga TLS w zaufanym reverse proxy; backend sam nie kończy TLS.
  Magazyny tokenów klientów będą wdrożone przy klientach; token procesu nie jest zapisywany do DB.
- Etap 1 nie ma uploadów ani endpointów operujących na ścieżkach. Izolacja plików,
  bezpieczne pobieranie i limity zadań muszą powstać przed tymi funkcjami.
- Workflow CI został dodany; wyniki uruchomienia na GitHub Actions nie są jeszcze znane.
- Szkic konfiguracji środowiska wymaga przeglądu, zapisania i publikacji w ustawieniach;
  nie weryfikowano przywrócenia snapshotu w nowym zadaniu.

## Test Results

Weryfikacja 2026-10-28: zarządzany Linux, Python 3.12.14, uv 0.12.23,
FastAPI 0.162.0, Pydantic 2.14.1, SQLite ze standardowej biblioteki Pythona;
bez modeli, silników inferencji i wymaganego GPU.

| Sprawdzenie | Wynik |
| --- | --- |
| `uv sync --frozen` | PASS — zależności z uv.lock |
| `uv run --frozen pytest -q` | PASS — 65 zaliczonych, 0 niezaliczonych, 0 pominiętych, bez ostrzeżeń |
| Migracje | Świeża baza, ponowna inicjalizacja, upgrade zachowujący dane, rollback DDL/danych/wersji, nowsza i uszkodzona baza, symlinki |
| API i kontrakty | Health, ustawienia po restarcie, walidacja, błędy, OpenAPI/JSON Schema, brak deklaracji silników |
| Lokalizacja i motywy | Identyczne klucze PL/EN, wybór języka bez restartu, zapis trzech preferencji motywu |
| WebSocket | Hello, ping/pong, fan-out, błędy, limity, rozłączenie, błąd DB, ograniczony bufor |
| Bezpieczeństwo | Odmowa zdalnego bindu bez opt-in/tokena, autoryzacja HTTP/WS, Origin, Host, CORS i limit rzeczywistego ciała żądania |
| `ruff check .` i `ruff format --check .` | PASS |
| `python scripts/export_contracts.py --check` | PASS |
| `python scripts/smoke.py` | PASS — proces CLI, HTTP/WS, PL, zapis, restart, trwałość |
| `uv build` | PASS — sdist i wheel |
| Instalacja wheel do `.venv-package` z zależnościami runtime z locka i hashami | PASS |
| `.venv-package/bin/python -I scripts/smoke.py` | PASS — bez importowania pakietu z checkoutu |
| GPU / silniki / anulowanie generowania / GUI | Niewykonane — moduły powstaną w kolejnych etapach |
| GitHub Actions | Nie potwierdzono wykonania workflow; lokalne polecenia CI wykonano |

## GitHub Status

- **Branch:** `feature/0.1.0-alpha`.
- **Local commit SHA:** `cbd36fc` — commit audytu/architektury; pełny SHA dostępny przez Git.
- **Remote commit SHA:** gałąź funkcjonalna nie została jeszcze opublikowana.
- **Push status:** oczekuje na commit i push fundamentu.
- **Pull request status:** nie utworzono w tej sesji.
- **Main:** podczas audytu `0f91a3e9a7ba28cac3324238248e1fda75fdb174`, nie zmieniano.
- **Access test:** historyczny push potwierdzony na `test/omnicore-github-access`,
  SHA `53cd9ed0cb1fa17e4c81b4ffe860c934978ae43d`.

SHA w tym dokumencie są zweryfikowanymi punktami kontrolnymi. Commit zapisujący
wynik weryfikacji może być późniejszy; nie próbować wpisywać hasha commita do niego samego.

## Session Handoff

Najpierw przeczytać AGENTS.md, ROADMAP.md, PROGRESS.md i ARCHITECTURE.md.
Fundament jest zaimplementowany i przetestowany; dokończyć commit, push i raport.
Nie rozpoczynać Etapu 2 w tym zadaniu. W nowym zadaniu porównać dokumentację
z rzeczywistym kodem i stanem Git; nie zakładać stałości gałęzi lub zdalnego HEAD.

```sh
cd /workspace/OmniCore
git status --short --branch
git log -3 --oneline
git rev-parse HEAD
git ls-remote --exit-code origin refs/heads/feature/0.1.0-alpha
uv sync --frozen
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen python scripts/export_contracts.py --check
uv run --frozen pytest
uv run --frozen python scripts/smoke.py
uv run --frozen omnicore --data-dir .local-data
```

Baza `.local-data` i środowiska `.venv*` są lokalnymi, ignorowanymi wynikami setupu;
nie commitować danych użytkownika, tokenów ani wag. Backend domyślnie jest lokalny.
Nie tworzyć dodatkowego worktree; zachować cudze zmiany i używać istniejącej autoryzacji.
Publiczne wydanie pozostaje nieautoryzowane.
