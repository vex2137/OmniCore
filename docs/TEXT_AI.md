> Aktualizacja Linux GUI (2026-10-28): realny GGUF SmolLM2-135M-Instruct Q4_K_M,
> llama.cpp CPU, streaming/anulowanie/historia w GUI i rzeczywisty HF download
> zostały sprawdzone. Poprzednie opisy blokady poniżej są historycznym raportem
> Etapu 2. Bieżące instrukcje: [LINUX_DESKTOP.md](LINUX_DESKTOP.md),
> [APPIMAGE.md](APPIMAGE.md). Oficjalny CDN `us.aws.cdn.hf.co` jest również obsługiwany.

# Etap 2 — Text AI: plan, integracje i weryfikacja

Gałąź: `feature/0.1.0-alpha`. Punkt wejścia: `1a2826b55efa419629f462233e1e56f29d10fa79`.
Etap 1 i projekt opcjonalnego Rust pozostają zachowane. Bez GUI i Image AI.

## Audyt przed implementacją (2026-10-28)

Odczytano AGENTS.md, ARCHITECTURE.md, ROADMAP.md, PROGRESS.md, historię i kod
backendu, schematy, migrację 001, zabezpieczenia oraz kontrakty.
GitHub read działa; lokalny HEAD odpowiada zdalnej gałęzi. `main` pozostaje
`0f91a3e9a7ba28cac3324238248e1fda75fdb174`.

Bazowe testy: 64 PASS i 1 błąd `CancelledError` podczas zamykania WebSocket
(`test_invalid_websocket_payload_is_error_and_connection_remains_usable`).
Naprawa cyklu życia połączenia należy do części A/F; nie usuwać asercji ani testu.

Brak zainstalowanych llama-server i Ollamy, brak potwierdzonego GPU.
Przygotowywany build CPU z oficjalnego repozytorium ggml-org/llama.cpp.
Sieć blokuje Hugging Face (CONNECT 403); wymagania domen zapisano w szkicu
konfiguracji. Sam zapis szkicu nie otwiera dostępu ani nie potwierdza inferencji.

## Kolejność A–F i warunki przejścia

| Część | Zakres | Walidacja przed commitem |
| --- | --- | --- |
| A | Asynchroniczne adaptery HTTP, llama-server jako własny proces loopback, diagnostyka wersji i CPU/GPU, opcjonalna Ollama | Testy protokołów i błędów, brak silników nie blokuje fundamentu, regresja 65 testów |
| B | Bezpieczny import przez referencję, ograniczony parser GGUF, katalog modeli w SQLite | Dobre/złe GGUF, metadane, symlinki/traversal, migracja i katalog bez kopiowania wag |
| C | Wyszukiwanie HF i plików GGUF, potwierdzone pobrania, resume/checksum/progress/cancel | Kontrolowany serwer HTTP i błędy sieci; realny HF tylko gdy polityka pozwala |
| D | Rozmowy i wiadomości, parametry, wyszukiwanie, JSON import/eksport | Trwałość po restarcie, zachowanie danych, walidacja i transakcje |
| E | Kolejka generowania, zdarzenia, streaming, stany, anulowanie i zapis historii | Testy obu protokołów, brak duplikatów, rozłączenie, timeout, OOM, restart |
| F | Wersjonowane API i kontrakty, lokalizacja, dokumentacja i testy rzeczywistych silników | Pełna regresja, smoke, build; osobno scenariusz GGUF bez Ollamy |

Testy protokołów z kontrolowanym serwerem i sztucznymi plikami są testami
jednostkowymi/integracji komponentów, nie dowodem rzeczywistej inferencji.
Rzeczywiste testy modeli muszą wskazać binarkę, wersję/commit, model, checksum,
sprzęt i wynik. Brak sieci/modelu/GPU oznacza niewykonany test, nie PASS.

## Decyzje

- Python 3.12/FastAPI pozostaje hostem. HTTP do silników jest asynchroniczne;
  lokalne połączenia omijają proxy egress, HTTPS do HF zachowuje proxy i CA.
- Proces jest uruchamiany wyłącznie z wcześniej skonfigurowanej zaufanej binarki,
  listą argumentów, bez powłoki. OmniCore zamyka tylko własny proces.
- Ścieżki modeli ogranicza konfigurowana przez administratora lista katalogów;
  API nie może rozszerzać tej listy. Import nie kopiuje wag.
- Istniejący kontrakt `/api/v1` pozostaje działający; nowe trasy i schematy są
  dodatkiem. Health nadal raportuje wersję schematu fundamentu, a nowe migracje
  modułu Text AI mają własny jawny marker w tej samej SQLite, aby zachować testy
  i znaczenie istniejącego pola `database_version`.
- Katalog, rozmowy i zadania są trwałe. Stan zadania po przerwaniu procesu
  backendu zostaje oznaczony jako przerwany, a częściowa odpowiedź zachowana.
- Maksymalnie jedna generacja jednocześnie domyślnie. Pełne fragmenty tekstu
  są odtwarzalne z historii zadania; WS nie jest jedynym źródłem prawdy.
- Nie uznajemy GGUF za obsługiwany tylko na podstawie rozszerzenia/metadanych.
  Udane załadowanie i rzeczywista generacja są osobnymi dowodami kompatybilności.

## Stan bieżący

A–E zapisano w osobnych commitach; API, zabezpieczenia i testy F są zaimplementowane.
Wymagany scenariusz rzeczywistej inferencji GGUF **nie został wykonany**: brak wag
i blokada HF (CONNECT 403). Nie uznajemy Etapu 2 za akceptacyjnie ukończony.
llama-server CPU został zbudowany i sprawdzony (`--version`, `--list-devices`),
ale nie jest to dowód poprawnego ładowania/generowania z modelem.

## Konfiguracja modułu

| Zmienna | Znaczenie |
| --- | --- |
| `OMNICORE_LLAMA_SERVER` | Zaufana binarka; bez wartości szukamy `llama-server` w PATH |
| `OMNICORE_MODEL_ROOTS` | Katalogi z istniejącymi modelami, separator `:`; brak domyślnego dostępu do całego dysku |
| `OMNICORE_LLAMA_CHAT_TEMPLATE` | Opcjonalny szablon zgodny z konkretnym modelem; nie wymuszamy go globalnie bez konfiguracji |
| `OMNICORE_OLLAMA_URL` | Domyślnie `http://127.0.0.1:11434` |
| `OMNICORE_OLLAMA_ENABLED` | `0` wyłącza Ollamę; domyślnie lokalna detekcja |
| `OMNICORE_GENERATION_TIMEOUT` | Całkowity czas pracy aktywnego zadania, domyślnie 300 s (1–3600); nie obejmuje czekania w kolejce |
| `OMNICORE_MAX_BODY_BYTES` | Limit wejściowego HTTP/WS, domyślnie 65536; dotyczy również importu JSON |
| `HF_TOKEN` | Opcjonalny sekret procesu dla modeli prywatnych/gated; nie trafia do SQLite ani odpowiedzi |

Katalog pobrań `<data-dir>/models` jest dozwolony automatycznie. Pozostałe pliki
GGUF wymagają jawnego rootu. Administrator konfiguruje silniki i katalogi przed
startem; publiczne API nie może rozszerzać uprawnień ani uruchamiać dowolnych programów.
Szczegóły i instalacja: [ENGINES.md](ENGINES.md).

## Nowe REST API

Wszystkie poniższe ścieżki mają prefiks `/api/v1/text` i zachowują zabezpieczenia
Etapu 1, w tym auth, Host, Origin/CORS i limit rzeczywistego rozmiaru żądania.
Schematy i parametry są w [OpenAPI](../contracts/openapi.json).

| Operacja | Funkcja |
| --- | --- |
| `GET /status` | Wersja schematu modułu, równoczesność 1, limit kolejki 16 |
| `GET /engines` | Dostępność, wersja, ścieżka binarki i wykryte urządzenia GPU |
| `GET /models?query=&backend=&format=` | Katalog, wyszukiwanie nazwy i filtrowanie |
| `POST /models/import` | GGUF przez referencję `{path}`; bez kopiowania wag |
| `POST /models/sync-ollama` | Rejestracja modeli z opcjonalnego serwera Ollama |
| `GET /models/{id}` | Metadane, źródło, licencja, kwantyzacja, możliwości i status weryfikacji |
| `PUT /models/{id}/parameters` | Trwałe domyślne parametry modelu |
| `POST /models/{id}/load` | Load GGUF z parametrami; tylko llama.cpp |
| `POST /models/{id}/unload` | Stop własnego llama-server / unload modelu Ollamy |
| `DELETE /models/{id}` | Domyślnie tylko wpis; JSON `{delete_file,confirm_name}` dla dodatkowo potwierdzonego usunięcia pliku GGUF |
| `GET /huggingface/search?query=` | Wyszukiwanie repozytoriów GGUF |
| `GET /huggingface/files?repository=&revision=` | Konkretne GGUF, commit, rozmiar, licencja i dostępna checksum |
| `POST /downloads` | Potwierdzone pobranie: repozytorium, plik, rewizja, `confirmed=true`, zgodny `expected_size` |
| `GET /downloads`, `GET /downloads/{id}` | Stan, procent, bajty, błąd, wynik integralności i końcowa ścieżka |
| `POST /downloads/{id}/cancel`, `/resume` | Anulowanie z zachowaniem częściowego pliku lub wznowienie |
| `POST /conversations`, `GET /conversations?query=` | Tworzenie i wyszukiwanie rozmów, także w treści wiadomości |
| `GET/PATCH/DELETE /conversations/{id}` | Odczyt, nazwa/model/parametry, usunięcie z historią |
| `GET/POST /conversations/{id}/messages` | Historia lub dodanie wiadomości system/user/assistant |
| `GET /conversations/{id}/export`, `POST /conversations/import` | Przenośny format JSON v1; nowe ID przy imporcie |
| `POST /conversations/{id}/generations` | Utworzenie zadania z `content`, `request_key` i opcjonalnym modelem/parametrami |
| `GET /generations/{id}` | Trwały snapshot, tekst, sekwencja, stan, metryki i błąd |
| `POST /generations/{id}/cancel` | Idempotentne anulowanie |
| `GET /generations/{id}/stream` | SSE pełnych snapshotów; domyślnie anulowanie przy odłączeniu |

Usuwanie modelu nie usuwa historycznych rozmów. Stary identyfikator może pozostać
w przeniesionej historii; użytkownik wybiera inny zarejestrowany model przed
kontynuacją. Zmiany zasobu używanego przez aktywną generację zwracają 409.
Domyślne parametry modelu są używane przy tworzeniu rozmowy, chyba że podano inne;
potem rozmowa ma własną, trwałą konfigurację.

## Minimalny przepływ GGUF bez Ollamy

1. Wskaż binarkę i dozwolony katalog według ENGINES.md; uruchom OmniCore.
2. `POST /api/v1/text/models/import` z `{"path":"/dozwolony/model.gguf"}`.
3. `POST /api/v1/text/conversations` z otrzymanym `model_id`.
4. `POST /api/v1/text/conversations/{id}/generations`, np.:

```json
{
  "content": "Cześć!",
  "request_key": "unikalny-klucz-zadania-1",
  "parameters": {
    "temperature": 0.7, "top_p": 0.9, "top_k": 40,
    "repeat_penalty": 1.1, "max_tokens": 128, "context_size": 2048,
    "seed": 42, "system_prompt": "Odpowiadaj po polsku.",
    "gpu_layers": 0, "device": "cpu"
  }
}
```

5. Obserwuj zwrócony ID przez REST, SSE lub istniejący WebSocket.
6. Użyj cancel do przerwania lub unload do zwolnienia załadowanego modelu.

Ponowienie tego samego `request_key` z tym samym wejściem zwraca istniejące zadanie
bez drugiej wiadomości. Inne wejście dla tego klucza daje 409. Klucz jest wspólny
dla instancji, więc klient powinien używać unikalnych UUID.

## Streaming, rozłączenie i trwałość

Stany generacji: `queued`, `running`, `completed`, `cancelled`, `failed`, `interrupted`.
Jedna aktywna generacja i maksymalnie 16 zadań; jedna generacja na rozmowę.
Assistant i snapshot zadania są zapisywane w jednej transakcji; `generation_id`
zapobiega duplikowaniu. Timeout, błąd i anulowanie zachowują częściowy tekst.
Po nieczystym restarcie zadania nie są automatycznie ponawiane: otrzymują `interrupted`.

`WS /api/v1/events` zachowuje stare komunikaty. Dodatkowe `generation.updated`
ma pole `task` zgodne z GenerationRecord, z pełnym tekstem i rosnącą sekwencją.
Klient zastępuje snapshot zamiast dopisywać go ponownie. Bufor WS jest ograniczony;
przy luce lub reconnect odczytaj GET zadania. `hello` zawsze poprzedza zdarzenia.

```json
{"type":"generation.watch","job_id":"ID-zadania","cancel_on_disconnect":true}
```

Watch powiązany z połączeniem anuluje zadanie przy zamknięciu WS. Zwykłe REST POST
tworzy trwałe zadanie niezależne od połączenia; zamknięcie przypadkowego WS nie
anuluje cudzej pracy. SSE domyślnie anuluje przy odłączeniu; można jawnie ustawić
`cancel_on_disconnect=false`. Każda aktywna praca ma limit czasu.

Po poprawnej generacji model może pozostać załadowany do ponownego użycia;
zamknięcie strumienia zwalnia połączenie HTTP. Anulowanie/błąd/timeout zamykają
własny proces llama.cpp, a jawny unload i shutdown zwalniają jego pamięć.
Zdalnej Ollamy nie można przymusowo zatrzymać przy utracie sieci.

TPS jest opcjonalne: używamy liczby tokenów i czasu z silnika, nie liczby chunków.
Nieznane pomiary RAM/VRAM pozostają null. CPU, brak GPU i OOM nie są maskowane
fałszywym sukcesem.
Diagnostyka pokazuje RSS własnego procesu llama.cpp, a dla Ollamy sumę raportowanych
alokacji VRAM modeli z `/api/ps`; to nie są wymyślone szacunki ani całkowita pamięć GPU.

## Bezpieczeństwo, zgodność i ograniczenia

- Ścieżki otwieramy po deskryptorach z O_NOFOLLOW, odrzucamy traversal, symlinki
  i pliki specjalne. Silnik dziedziczy zweryfikowany deskryptor GGUF.
- Parser GGUF v2/v3 ma limit 64 MiB metadanych oraz limity liczby kluczy,
  tensorów, tablic i długości pól. Waliduje strukturę i granice; nie potwierdza
  wszystkich układów kwantyzacji ani obsługi architektury przez konkretny silnik.
- `compatibility=unverified` po imporcie, `load_verified` po load i `tested`
  dopiero po zakończonej generacji rzeczywistej treści w używanym silniku.
  Nie oznacza to wsparcia wszystkich modeli ani aktualnego rezydowania w pamięci.
- Możliwości Ollamy pochodzą z /api/show; tekst llama.cpp potwierdza generacja.
  Brak dowodu to pusta lista. Vision/embeddings/tools/structured-output są
  przygotowaniem modelu możliwości, nie nowymi działającymi endpointami.
- Przyszłe wejścia multimodalne mogą dodać opcjonalne referencje załączników do
  wiadomości przy zachowaniu dotychczasowego pola tekstowego i sprawdzaniu możliwości.
- Baza zachowuje PRAGMA user_version=1 dla kontraktu fundamentu; tabela
  `text_schema` osobno wersjonuje migracje modułu w tej samej SQLite. Obie ścieżki
  są transakcyjne, a nowsze schematy odrzucane. Zrób backup przed aktualizacją.
- HF zapisuje prywatny `.part`, sprawdza Range/rozmiar/SHA-256 (gdy znana), GGUF
  i atomowo zmienia nazwę. Ignorowane Range restartuje transfer; błąd integralności
  przy ponowieniu resetuje uszkodzony plik częściowy. Bez checksumy wynik nie jest
  oznaczany jako w pełni zweryfikowany. Pobrany plik importuje się osobnym żądaniem.
- Jedna instancja API/worker; brak GUI, Image AI i własnych komponentów Rust.
- Testy bez GPU i fixture protokołów nie zastępują inferencji z modelem.
