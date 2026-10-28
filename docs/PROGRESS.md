# OmniCore — PROGRESS

## Project Status

- **Current version:** 0.1.0 Alpha (`0.1.0a0`), backend headless; bez wydania produktu.
- **Current milestone:** Etap 2 A–F zaimplementowany i przetestowany bez modeli.
  **Akceptacja rzeczywistego GGUF pozostaje zablokowana**; nie oznaczamy całego Etapu 2 jako ukończonego.
- **Current development branch:** `feature/0.1.0-alpha`.
- **Last verified commit:** `4622eb35369c3373a63d2ba7ac60d765c1e0bc64` — implementacja Text AI;
  lokalny HEAD, ref GitHub i ponownie pobrany commit są zgodne.
- **Last update:** 2026-10-28 (Europe/Warsaw).

## Completed

Zachowano fundament Etapu 1: FastAPI, SQLite, ustawienia PL/EN i motywów,
REST/WebSocket, zabezpieczenia i wszystkie 65 oryginalnych testów. Zachowano
projekt opcjonalnego Rust; nie wdrożono żadnego własnego komponentu natywnego Rust.

| Część | Zaimplementowane i sprawdzone komponenty | Commit |
| --- | --- | --- |
| A | HTTP/SSE llama.cpp, NDJSON Ollamy, wersja/detekcja, parametry, własny proces loopback, stop, naprawa zamykania WS | `917372c` |
| B | Referencje GGUF, ograniczony parser v2/v3, metadane i katalog SQLite, kontrola ścieżek/symlinków, potwierdzane usunięcie pliku | `eba274f` |
| C | HF search/pliki, przypięty commit, rozmiar/licencja/checksum, potwierdzany download, postęp, resume i cancel, atomowy zapis | `0e166f6` |
| D | Rozmowy/model/parametry, role i czas, trwała historia, wyszukiwanie, import/eksport JSON i idempotentny zapis asystenta | `9518e77` |
| E | Kolejka, request_key/fingerprint, snapshoty, streaming, timeout/OOM/cancel, częściowa odpowiedź, odzyskiwanie po restarcie | `01fdfc8` |
| F | API `/api/v1/text`, stary WS plus generation.updated/watch, SSE, kontrakty, lokalizacja, security, osobne scenariusze realne | `4622eb3` |

Checkboxy i tabela A–F dotyczą kodu i testów komponentów. Kontrolowany adapter,
syntetyczny GGUF i odpowiedzi HTTP nie są testem działania realnego modelu.

Dodatkowo zweryfikowano:

- Rzeczywisty build CPU oficjalnego llama.cpp z commita
  `c3df4b7e22a1ac38da663552d19e649dd97ca936`; `llama-server --version`:
  `0.8.0-dev`, GNU 14.2.0, Linux x86_64; `--list-devices`: brak GPU.
- SHA-256 zbudowanej lokalnie binarki:
  `6f0d350146a6ad171347918ca86fbd5b40957bb3651eb8701bfbf89bbb2f4f83`.
  To identyfikator własnego builda, nie uniwersalna checksum wersji upstream.
- Sprawdzono detekcję tej binarki z backendu oraz z pakietu wheel.
- Dodano Linux parent-death guard; test dowodzi zakończenia własnego dziecka
  po śmierci rodzica. Normalny stop kończy tylko własny proces i jego grupę.
- API health, text/status i diagnostyka prawdziwego silnika działają w chmurze.
  Katalog realnych modeli pozostaje pusty; nie publikowano fałszywej zgodności.
- Zbudowano sdist/wheel, zainstalowano wheel w oddzielnym środowisku tylko runtime
  z zależnościami/hashes z locka; smoke sprawdził HTTP, WS i rozmowę po restarcie.
- Zapisano szkic środowiska: install_script, aktualny start_skill,
  OMNICORE_LLAMA_SERVER oraz domeny HF. Nie opublikowano snapshotu środowiska.
- Wysłano commity A–F, potwierdzono SHA przez ls-remote i fetch oraz porównano
  pliki API, guard, kontrakty, dokumentację i test akceptacyjny z GitHub.

## In Progress

- Akceptacja rzeczywistej inferencji bez Ollamy jest otwarta; nie ma aktywnego
  generowania i nie pobierano wag. Etapu 3 nie rozpoczęto.

## Planned Next

1. Zastosować zapisane domeny HF w ustawieniach środowiska; aktualny runtime nadal
   raportuje politykę rewizji 1 bez tych domen (CONNECT do HF zwraca 403).
2. Udostępnić istniejący zgodny GGUF lub pobrać mały model po otwarciu sieci,
   z weryfikacją checksum/licencji. Pobranie wielogigabajtowe wymaga potwierdzenia.
3. Uruchomić `integration/test_llama_real.py`: bez Ollamy, import/load realnego
   GGUF, odpowiedź, trwała historia oraz unload. Dopiero wynik tego scenariusza
   może zamknąć kryterium akceptacji.
4. Oddzielnie uruchomić test rzeczywistej Ollamy z już zainstalowanym modelem.
5. Zweryfikować docelowy CachyOS/RTX 4060, GPU/VRAM, OOM i anulowanie na sprzęcie.
   Nie rozpoczynać Image AI ani klientów w ramach bieżącego zadania.

## Known Issues

- **Bloker środowiska:** HF jest niedostępny przez egzekwowaną politykę proxy.
  Zapis szkicu nie zastosował zmian do runtime. Publiczny model nie wymaga
  dopisywania fikcyjnego tokenu. Brak dostępnych wag uniemożliwia realny test GGUF.
- **Nieweryfikowane integracje:** nie uruchomiono rzeczywistej inferencji llama.cpp,
  transferu z publicznego HF ani rzeczywistej Ollamy; nie są oznaczone jako PASS.
- Testy fixture potwierdzają protokoły, stan i błędy, nie zgodność modelu.
  GGUF ma status unverified po imporcie; load_verified i tested wymagają
  odpowiednio udanego load i zakończonej generacji rzeczywistej treści.
- Parser sprawdza ograniczoną strukturę i zakresy GGUF, nie każdą kwantyzację
  ani obsługę architektury. O zgodności rozstrzyga też wersja i konfiguracja silnika.
- Jeden proces API; jedna generacja, kolejka maksymalnie 16. Model może pozostać
  załadowany po poprawnej odpowiedzi do jawnego unload. Nie obiecujemy zdalnego
  zabicia obcej Ollamy przy awarii sieci.
- Vision/embeddings/tools/structured-output są opisem możliwości wykrytych w silniku
  lub przygotowaniem kontraktu; brak działających endpointów tych funkcji.
- JSON import podlega limitowi żądania (domyślnie 64 KiB). Import tworzy nowe ID;
  binding modelu może wymagać ponownego wybrania po przeniesieniu na inną instalację.
- TLS zdalnego dostępu nadal wymaga reverse proxy. Tokeny procesu nie są zapisywane
  do DB. Brak GUI, Image AI i pomiarów CachyOS/RTX 4060.
- Wynik GitHub Actions oraz przywrócenie nowego snapshotu w osobnym zadaniu niepotwierdzone.

## Test Results

Środowisko: zarządzany Linux, Python 3.12.14, uv 0.12.23, FastAPI 0.162.0,
Pydantic 2.14.1, HTTPX 0.28.1 i SQLite z biblioteki standardowej. Bez wag modeli.

| Sprawdzenie | Wynik |
| --- | --- |
| Bazowy audyt przed zmianą | 64 PASS i 1 błąd teardown WS; naprawiony w A, bez usuwania testu |
| Regresja po A / B / C / D / E | 75 / 85 / 92 / 97 / 104 PASS |
| Końcowe `uv run --frozen pytest -q` | **115 PASS**, 0 FAIL, 0 skipped, bez ostrzeżeń |
| Wszystkie oryginalne pliki 65 testów | Bez zmian względem `1a2826b` |
| Ścieżki i modele | Traversal, symlinki/rodzice/FIFO, zmiana inode, usuwanie tylko po potwierdzeniu, niepoprawny/truncated GGUF |
| Silniki | Brak llama/Ollama/GPU, SSE/NDJSON, parametry, wersja, OOM, proces load/switch/stop (kontrolowany serwer) |
| Pobieranie | Potwierdzenie, checksum, Range/resume i restart bez Range, cancel, redirect, ponowienie uszkodzonego partial |
| SQLite i rozmowy | Migracje z zachowaniem danych, rollback, nowszy schemat, historia/restart, role/czas, Unicode search, JSON round-trip |
| Generowanie | Idempotencja, kolejka, częściowy tekst, timeout, OOM/błędy, restart i anulowanie |
| Rozłączenie | WS watch oraz SSE z rzeczywistym połączeniem HTTP; anulowanie i zdrowy backend |
| Lifecycle procesu | Linux parent-death guard: własne dziecko nie pozostaje aktywne po śmierci rodzica |
| Security | Stare auth/Host/Origin/CORS/limity plus nowe trasy, brak ekspozycji HF/API tokenu, brak shell |
| Kontrakty | Snapshoty zgodne; stare REST paths/operation IDs/responses i bazowe schematy zachowane; WS rozszerzony addytywnie |
| Ruff / format / git diff --check | PASS |
| `python scripts/smoke.py` | PASS — prawdziwy CLI, HTTP/WS, PL, preferencje i rozmowa po restarcie |
| `uv build`, izolowana instalacja wheel i jego smoke | PASS |
| Detekcja prawdziwego llama-server z wheel i API | PASS — wersja c3df4b7, CPU, brak modeli |
| Realny GGUF bez Ollamy | **NIEWYKONANY / BLOKADA ŚRODOWISKA**, nie PASS |
| Realny HF / Ollama / GPU | Niewykonane; nie zastąpiono ich mockami jako dowodem |

Testy realne są poza domyślnym zestawem w `integration/`. Nie mają fallbacku
ani automatycznego pobierania modeli; brak warunku wstępnego powoduje błąd testu.

## GitHub Status

- **Branch:** `feature/0.1.0-alpha`.
- **Local commit SHA / Remote commit SHA:** zweryfikowany punkt kontrolny implementacji
  `4622eb35369c3373a63d2ba7ac60d765c1e0bc64`. Ten raport zapisuje wynik w późniejszym commicie.
- **Push status:** sukces; zdalny ref, fetch i lokalny HEAD implementacji zgodne.
- **Pull request status:** nie utworzono w tej sesji.
- **Main:** `0f91a3e9a7ba28cac3324238248e1fda75fdb174`, nie zmieniano.
- **Wydanie/tag Alpha:** nie opublikowano.

SHA są punktami kontrolnymi; commit zapisujący raport może być późniejszy.
Bieżący HEAD i ref zdalny zawsze sprawdzać poleceniami Git.

## Session Handoff

Przeczytać AGENTS.md, ARCHITECTURE.md, ROADMAP.md, PROGRESS.md, TEXT_AI.md i ENGINES.md.
Backend A–F jest zaimplementowany i ma 115 testów bez GPU. Najważniejszym otwartym
warunkiem jest rzeczywisty scenariusz GGUF bez Ollamy po zastosowaniu polityki HF
lub udostępnieniu istniejącego modelu. Nie deklarować pełnej akceptacji Etapu 2.

```sh
cd /workspace/OmniCore
git status --short --branch
git log -7 --oneline
git rev-parse HEAD
git ls-remote --exit-code origin refs/heads/feature/0.1.0-alpha
uv sync --frozen
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen python scripts/export_contracts.py --check
uv run --frozen pytest -q
uv run --frozen python scripts/smoke.py
uv run --frozen omnicore --data-dir .local-data
```

Silnik cloud: `/workspace/omnicore-engines/llama.cpp/build/bin/llama-server`.
Do importu plików spoza `.local-data/models` wymagane OMNICORE_MODEL_ROOTS.
Szkic środowiska zawiera aktualne install_script/start_skill, ścieżkę silnika i domeny HF;
przejrzeć, zapisać i opublikować w ustawieniach. Sam zapis szkicu nie stosuje sieci.
Przed inferencją sprawdzić rzeczywisty runtime, wersję silnika i checksum/licencję modelu.
Zachować cudze zmiany, istniejący checkout, brak sekretów/wag w Git i brak force push.
