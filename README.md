# OmniCore
OmniCore is an open-source platform for running and managing AI models locally. It provides a modern, unified interface for text generation, image creation, and future AI capabilities, with a focus on privacy, performance, and ease of use.

## Stan: 0.1.0 Alpha — natywna aplikacja Linux

OmniCore ma działające GUI Qt6/PySide6: czat ze streamingiem i historią, menedżer
GGUF/Hugging Face, ustawienia PL/EN i motywów oraz diagnostykę. GUI Linux zostało
przesunięte przed Image AI. GGUF działa przez llama.cpp **bez Ollamy**; rzeczywisty
przepływ import/load/generowanie/anulowanie/historia przeszedł test na CPU ze
SmolLM2-135M-Instruct Q4_K_M. Nie oznacza to zgodności wszystkich modeli lub GPU.

```sh
uv sync --frozen --extra desktop --group gui-test --group packaging
uv run --frozen omnicore-desktop
```

Dostępny jest proces budowania samowystarczalnego AppImage z Pythonem, Qt,
backendem i opcjonalnym silnikiem CPU. Dane są przechowywane poza paczką.
[Linux — uruchomienie i obsługa](docs/LINUX_DESKTOP.md) ·
[AppImage — uruchomienie, budowanie i wymagania](docs/APPIMAGE.md).

Backend FastAPI/SQLite i dotychczasowe API pozostają zachowane. Rust jest
przygotowaną możliwością architektoniczną; [pomiary i decyzja](native/README.md)
nie uzasadniają teraz nowej implementacji. Image AI, Web i Android pozostają
planowane. To rozwojowa Alpha; publiczny release wymaga osobnego potwierdzenia.

- [Architektura, audyt, plan i ryzyka](docs/ARCHITECTURE.md)
- [Roadmapa](docs/ROADMAP.md)
- [Postęp i przekazanie kolejnej sesji](docs/PROGRESS.md)
- [Zasady pracy](AGENTS.md)
- [Kontrakty API](contracts/openapi.json)
- [Text AI: plan A–F, API i ograniczenia](docs/TEXT_AI.md)
- [Instalacja i konfiguracja llama.cpp / Ollamy](docs/ENGINES.md)

## Uruchomienie backendu na Linux

Wymagania: Python 3.12+ i uv (weryfikowano Python 3.12.14, uv 0.12.23).
Nie potrzeba GPU, Ollama, ComfyUI ani żadnych wag. Polecenia z katalogu repozytorium:

```sh
uv sync --frozen
uv run --frozen omnicore
```

Backend nasłuchuje domyślnie na `127.0.0.1:8000`. Baza znajduje się w
`$XDG_DATA_HOME/omnicore` lub `~/.local/share/omnicore`; ustawienia utrzymują się
po restarcie. Zatrzymanie: Ctrl+C. Alternatywny katalog/port:

```sh
uv run --frozen omnicore --data-dir .local-data --port 8001
```

Sprawdzenie gotowości: `curl --fail http://127.0.0.1:8000/api/v1/health`.
Odpowiedź `status=ok` potwierdza odczyt tabeli ustawień i wersji schematu bazy.
Nie potwierdza dostępności silników AI.

## API Etapu 1

| Operacja | Działanie |
| --- | --- |
| `GET /api/v1/health` | Stan backendu i wersja schematu SQLite |
| `GET /api/v1/settings` | Odczyt preferencji |
| `PUT /api/v1/settings` | Zastąpienie preferencji i zdarzenie dla podłączonych klientów |
| `GET /api/v1/locales` | Lista `en-US`, `pl-PL` |
| `GET /api/v1/locales/{locale}` | Katalog tekstów interfejsu i błędów |
| `GET /api/v1/backends` | Wykryte dostępne silniki; `[]`, gdy żaden nie jest dostępny |
| `GET /openapi.json` | Kontrakt REST, bez zewnętrznego CDN |
| `WS /api/v1/events` | `hello`, `settings.updated`, `generation.updated`, `pong`, `error` |

```sh
curl --fail -X PUT http://127.0.0.1:8000/api/v1/settings \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":1,"locale":"pl-PL","theme":"dark","mode":"advanced"}'
```

PUT zastępuje całe ustawienia; pominięte pola przyjmują wartości domyślne.
Motywy: `system/light/dark`; tryby: `simple/advanced`. Są to trwałe preferencje;
ich renderowanie jest już dostępne w kliencie Linux.

Klient WS otrzymuje aktualne ustawienia w `hello`. Może wysłać `{"type":"ping"}`
i otrzyma `pong`; zapis przez REST rozsyła `settings.updated`. Zdarzenia zawierają
`schema_version: 1`. Wolne połączenia mają bufor 32 zdarzeń; pełne snapshoty
ustawień zastępują najstarsze wpisy, więc klient powinien przyjmować ostatni stan.
Ponowne połączenie odtwarza stan przez `hello`, bez dziennika historii zdarzeń.

Błędy mają format `{"error":{"code":"...","message":"..."}}`.
`Accept-Language` wybiera PL/EN dla błędów niezależnie od zapisanej preferencji
interfejsu. Nieobsługiwany język nagłówka przechodzi na en-US; nieobsługiwane
`locale` w ustawieniach jest odrzucane.

## Konfiguracja i dostęp zdalny

| Zmienna | Domyślna wartość / znaczenie |
| --- | --- |
| `OMNICORE_DATA_DIR` | Katalog bazy; domyślnie ścieżka XDG opisana wyżej |
| `OMNICORE_HOST` | `127.0.0.1` |
| `OMNICORE_PORT` | `8000` |
| `OMNICORE_ALLOW_REMOTE` | Dostęp spoza loopback wyłączony; włączenie: `1` |
| `OMNICORE_API_TOKEN` | Brak; wymagany po włączeniu dostępu zdalnego |
| `OMNICORE_ALLOWED_ORIGINS` | Pusta lista; jawne origins rozdzielone przecinkami |
| `OMNICORE_ALLOWED_HOSTS` | `127.0.0.1,localhost,::1`; jawne nazwy lub IP backendu |

Zdalne bindowanie wymaga `OMNICORE_ALLOW_REMOTE=1` i losowego tokenu co najmniej
32 znaków ASCII (litery/cyfry, np. `secrets.token_hex(32)`). Wartość podawaj przez
bezpieczne ustawienia procesu; nie zapisuj w repozytorium, bazie, URL ani historii
poleceń. Jeśli token jest ustawiony, także lokalne żądania wymagają
`Authorization: Bearer <token>`. Token nie trafia do odpowiedzi ani `repr` konfiguracji.

WebSocket akceptuje nagłówek Authorization, a dla przeglądarki protokoły
`omnicore.v1` oraz `bearer.<token>`; negocjuje wyłącznie `omnicore.v1`.
Origin przeglądarki musi być jawnie dozwolony. Domyślnie dozwolony jest też własny
origin skonfigurowanego adresu loopback i portu. CORS nie jest uwierzytelnianiem.
Przed połączeniem przez niezaufaną sieć skonfiguruj TLS w zaufanym reverse proxy;
serwer sam nie kończy TLS. Nie wystawiaj niezabezpieczonego HTTP z tokenem w Internecie.
Kontrola nagłówka Host chroni przed DNS rebinding. Przy bindzie `0.0.0.0` lub `::`
dodaj adres/nazwę używaną przez klientów do `OMNICORE_ALLOWED_HOSTS`. Konkretna
nazwa lub IP ustawione jako host nasłuchu są dopuszczane automatycznie.

Limit żądań i komunikatów WS domyślnie wynosi 64 KiB
(`OMNICORE_MAX_BODY_BYTES`). Import GGUF używa ścieżki ograniczonej do katalogów
administratora; nie przesyła wag w JSON. Nie ma endpointu uruchamiania dowolnych poleceń.
Nie uruchamiaj wielu
workerów: ustawienia zdarzeń są rozsyłane w obrębie jednego procesu.
Nie edytuj SQLite ręcznie podczas działania; wykonuj kopię bazy przed migracjami.
Nowszy nieobsługiwany schemat bazy jest odrzucany bez automatycznego downgrade.

## Walidacja i rozwój

```sh
uv sync --frozen
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen python scripts/export_contracts.py --check
uv run --frozen pytest
uv run --frozen python scripts/smoke.py
uv build
```

Smoke test uruchamia prawdziwy proces CLI na wolnym porcie loopback,
sprawdza HTTP, WS, katalog PL, zapis ustawień, restart i zachowanie danych.
Używa tymczasowego katalogu i zatrzymuje wyłącznie własny proces.

Po zmianie schematów lub tłumaczeń uruchom
`uv run --frozen python scripts/export_contracts.py`, przejrzyj diff i zapisz
snapshoty z kodem. Katalogi źródłowe są w `backend/src/omnicore/locales`,
kopie dla klientów w `contracts/locales`. Protokół WS ma osobne schematy JSON,
ponieważ OpenAPI opisuje tylko HTTP.

CI uruchamia testy bez GPU, w tym protokoły silników i stan generowania na
kontrolowanych fixture. Rzeczywiste testy w `integration/` uruchamia się osobno
z własnym modelem; nie pobierają wag i nie zastępują silnika mockiem.
Nie deklarujemy weryfikacji CachyOS/RTX 4060, realnej inferencji ani interfejsów
Linux/Web/Android w tym środowisku. Publiczne wydanie
wymaga osobnej zgody właściciela.
