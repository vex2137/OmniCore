# OmniCore — PROGRESS

## Project Status

- **Current version:** 0.1.0 Alpha (`0.1.0a0`), fundament; bez wydania produktu.
- **Current milestone:** Etap 2 A–F — backend Text AI; część A zaimplementowana i przetestowana.
- **Current development branch:** `feature/0.1.0-alpha`.
- **Last verified commit:** `59dd09f87b793a86dd3059dd64b7d7823311744c`
  (fundament Etapu 1; lokalny HEAD, zdalny ref i ponownie pobrany commit są zgodne).
- **Last update:** 2026-10-28 (Europe/Warsaw).

## Completed

### Etap 2 D — rozmowy i historia

- Rozmowy, model/parametry, role, znaczniki czasu, Unicode search, zmiana nazwy,
  usuwanie kaskadowe i zachowanie historii po zmianie modelu oraz restarcie.
- JSON import/eksport waliduje role/czas/pola, zachowuje treść i tworzy nowe ID;
  zapis odpowiedzi po generation_id jest idempotentny i zachowuje częściowy tekst.
- Regresja: 97 PASS, Ruff PASS. GUI i inferencja nie są częścią tych testów.

### Etap 2 C — pobieranie Hugging Face

- Wyszukiwanie repozytoriów i GGUF, przypięcie rewizji, rozmiar/licencja i checksum.
- Jawne potwierdzenie rozmiaru, prywatne pliki częściowe, resume Range/If-Range,
  checksum, walidacja GGUF, atomowy zapis, anulowanie i stan trwały po restarcie.
- Brak uruchamiania kodu modeli; kontrola redirectów nie przekazuje tokenu innym hostom.
- Regresja: 92 PASS; transport HF sprawdzony kontrolowanymi odpowiedziami HTTP.
- Zbudowany llama-server: 0.8.0-dev, c3df4b7e22a1ac38da663552d19e649dd97ca936,
  CPU-only; --version i --list-devices uruchomione. Rzeczywista inferencja jeszcze niewykonana.

### Etap 2 A — adaptery i procesy (2026-10-28)

- Dodano transporty llama.cpp SSE i Ollama NDJSON, wykrywanie wersji i możliwości,
  parametry, anulowanie, diagnostykę zasobów, własny proces loopback i bezpieczny stop.
- Naprawiono błąd zamykania WebSocket przez ustrukturyzowaną grupę zadań AnyIO.
- Regresja: 75 PASS, w tym wszystkie 65 dotychczasowych testów; Ruff PASS.
- Testy protokołów i procesu używają kontrolowanych fixture — nie są dowodem inferencji.
- Build CPU llama.cpp z oficjalnego źródła w toku; HF pozostaje zablokowany (403).

### Zachowany fundament i wcześniejsze prace

### Etap 2 B — katalog modeli i GGUF

- Import przez referencję, parser GGUF v2/v3 z limitami i walidacją struktury,
  metadane/licencja/kwantyzacja oraz katalog SQLite z wyszukiwaniem i filtrami.
- Kontrola katalogów, traversal, symlinków i zmiany tożsamości pliku; domyślne
  usunięcie dotyczy wpisu, usunięcie wag wymaga potwierdzenia nazwy.
- Wersjonowana migracja modułu tekstowego zachowuje bazę i kontrakt fundamentu.
- Regresja: 85 PASS; sztuczne GGUF są fixture, nie testowanymi modelami inferencji.

### Historia fundamentu

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
- Zapisano audyt/architekturę w `cbd36fc`, a fundament w
  `59dd09f87b793a86dd3059dd64b7d7823311744c`. Push gałęzi funkcjonalnej powiódł się;
  ponownie pobrano ref i porównano SHA oraz kluczowe pliki źródłowe i kontrakty.
- Rozszerzono [ARCHITECTURE.md](ARCHITECTURE.md#opcjonalna-warstwa-rust--decyzja-architektoniczna)
  i ROADMAP.md o podział Python/Rust, PyO3/maturin oraz osobny proces API,
  priorytety, koszty budowania i utrzymania oraz plan warunkowego wdrożenia.
- Określono bramkę: profilowanie rzeczywistego workloadu, porównanie z bibliotekami
  natywnymi i poolami Pythona, cel ustalony przed prototypem oraz testowany fallback.
  Przykładowe 20% poprawy p95 lub peak RSS jest propozycją celu, nie wynikiem pomiaru.
- Ponownie uruchomiono wszystkie 65 dotychczasowych testów, lint/format,
  kontrolę kontraktów, smoke testy procesu i istniejącego pakietu oraz build.
  Wszystkie sprawdzenia przeszły; kod, zależności i snapshoty API pozostają bez zmian.

## In Progress

- Etap 2: A zakończone na poziomie transportów/procesów; B–F w kolejności docs/TEXT_AI.md.
- Rzeczywisty scenariusz GGUF bez Ollamy wymaga binarki i modelu; nie jest jeszcze PASS.

## Planned Next

1. Przejrzeć rezultat Etapu 1 na gałęzi funkcjonalnej; nie rozpoczynać Etapu 2 w tej sesji.
2. W następnym zadaniu: adaptery Ollama/llama.cpp, menedżer modeli, czat,
   streaming, historia i import/eksport rozmów wraz z testami rzeczywistej inferencji.
3. Dopiero w Etapie 3: ComfyUI i sprawdzone workflowy, kolejka, obrazy, LoRA.
4. Dopiero w Etapie 4: natywne Linux/Android i Web; renderowanie oraz testy motywów.
5. Profilować duże pliki dopiero po powstaniu rzeczywistego importu. Rozważyć
   opcjonalny Rust tylko po zapisaniu konkretnej potrzeby i mierzalnego celu;
   kolejka, zasoby i współbieżność mają niższy priorytet analizy. Rust nie blokuje Alpha.

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
- Nie ma własnych komponentów Rust, ich benchmarków ani testów kompilacji.
  Projekt architektury nie potwierdza przyspieszenia, izolacji ani zgodności platformowej.

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
| Push `feature/0.1.0-alpha` i niezależny odczyt SHA | PASS — `59dd09f87b793a86dd3059dd64b7d7823311744c` |

Regresja po analizie Rust, 2026-10-28, to samo środowisko Python 3.12.14:
`pytest -q`: **65 passed**, bez pominięć i ostrzeżeń; Ruff, format, eksport kontraktów
w trybie `--check`, `scripts/smoke.py`, `uv build` oraz smoke test z `.venv-package`
zakończyły się powodzeniem. Sprawdzono lokalne odnośniki i `git diff --check`.
Zmiany obejmują tylko ARCHITECTURE.md, ROADMAP.md i PROGRESS.md; brak zmian kodu,
testów, migracji, manifestów, lockfile i kontraktów. Nie uruchamiano benchmarków
ani testów Rust, ponieważ nie wdrożono komponentu natywnego.

## GitHub Status

- **Branch:** `feature/0.1.0-alpha`.
- **Local commit SHA:** `59dd09f87b793a86dd3059dd64b7d7823311744c` — punkt kontrolny fundamentu.
- **Remote commit SHA:** `59dd09f87b793a86dd3059dd64b7d7823311744c` — potwierdzony przez `git ls-remote` i fetch.
- **Push status:** sukces; porównano zdalny commit z lokalnym i obecność kluczowych plików.
- **Pull request status:** nie utworzono w tej sesji.
- **Main:** podczas audytu `0f91a3e9a7ba28cac3324238248e1fda75fdb174`, nie zmieniano.
- **Access test:** historyczny push potwierdzony na `test/omnicore-github-access`,
  SHA `53cd9ed0cb1fa17e4c81b4ffe860c934978ae43d`.

SHA w tym dokumencie są zweryfikowanymi punktami kontrolnymi. Commit zapisujący
wynik weryfikacji może być późniejszy; nie próbować wpisywać hasha commita do niego samego.

## Session Handoff

Najpierw przeczytać AGENTS.md, ROADMAP.md, PROGRESS.md i ARCHITECTURE.md.
Fundament jest zaimplementowany, przetestowany i opublikowany na gałęzi funkcjonalnej.
Następnie dopisano projekt opcjonalnej warstwy Rust i ponownie zweryfikowano
regresję. Nie dodawać crate'ów ani zależności bez potrzeby potwierdzonej pomiarami.
Priorytetem kolejnego zadania funkcjonalnego pozostają adaptery tekstowe w Pythonie.
Ten dokument zapisuje wynik weryfikacji wcześniejszego commita; aktualny HEAD
raportu sprawdzić poniższymi poleceniami i porównać ze zdalnym refem.
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
