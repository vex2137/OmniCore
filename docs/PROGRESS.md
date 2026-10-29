# OmniCore — PROGRESS

## Aktualizacja — Android, część 2 (2026-10-29)

Audyt: czysty main `2e78daa0035ff0858c33fc387468b078100e3fd8`, PR #3 scalony,
brak otwartych PR na starcie. GUI Linux i AppImage zachowane. Publiczna Alpha.1
została opublikowana po późniejszej, wyraźnej zgodzie właściciela; historyczne
opisy szkicu poniżej odnoszą się do wcześniejszego punktu kontrolnego.

Gałąź: `feature/android-part-2`. Rozwijamy istniejącego klienta, nie tworzymy go
od nowa. Implementacja: granica OmniRepository + Flow/StateFlow, odłączenie SSE
bez cancel w tle, ponowne obserwowanie zadania/historii, HF download manager,
parametry rozmowy zachowujące GPU, target/compile 36 i kontrola stron 16 KiB.

Regresja wykonana w tej sesji: **130 PASS** (backend/Qt i dwie rzeczywiste
integracje GGUF/GUI), 56.54 s. Nowy zestaw Androida i CI pozostają w weryfikacji;
nie oznaczamy ich zaliczenia na podstawie kodu. Nowy APK Alpha.2 nie jest publiczny.
Telefon fizyczny, POCO/Xiaomi i lokalna inferencja telefonu pozostają niezweryfikowane.

## Project Status

- **Wersja:** `0.1.0-alpha.1`, natywny Linux + natywny Android jako klient API.
  Wersja komponentu backendu `0.1.0a0` pozostaje zgodna z dotychczasowym kontraktem.
- **Gotowy zakres:** czat/stream/cancel/historia, modele GGUF/llama.cpp bez Ollamy,
  klient Linux PySide6, klient Android Kotlin/Compose, PL/EN, motywy i diagnostyka.
- **GitHub:** PR #3 **MERGED**, checkpoint zdalnego main
  `ad03290f3c050617b6a74e81c5c49bf6b537e0d9`, potwierdzony API i ls-remote.
  Gałąź `feature/0.1.0-alpha` pozostaje na `21acff00da0c67820bcb2203a27df146fd0e33bc`.
  Commit dokumentujący weryfikację może być późniejszy; bieżący HEAD sprawdzać w Git.
- **Testy:** 130 lokalnych PASS (117 backend + 11 Linux GUI + 2 realne GGUF/GUI),
  18 JVM Android PASS, lint PASS i 1 test natywnego UI na emulatorze API 30 x86_64
  PASS (0 skipped). Backend testu Androida jest fixture protokołu; GGUF zweryfikowano
  osobno rzeczywiście na CPU Linux bez Ollamy. Osobny rzeczywisty HF transfer PASS.
- **CI:** Backend, Linux AppImage i Android APK **SUCCESS** dla źródła `21acff0`
  oraz po scaleniu na `ad03290`. Szczegółowe linki i SHAs poniżej.
- **Pakiety:** oba rzeczywiście przesłane z checksumami do szkicu wydania
  `v0.1.0-alpha.1`, ID 427506837. **draft=true, publicznego release nie opublikowano**.
- **Ograniczenia:** fizyczny ARM64, CachyOS/RTX 4060, CUDA, Wayland i rzeczywista
  Ollama nie były testowane. Android nie wykonuje inferencji na telefonie.
  Image AI/Web pozostają planowane; nie wdrożono nieuzasadnionego komponentu Rust.

Poniższe raporty Etapu 2 są historyczne. Aktualny raport końcowy jest na końcu dokumentu.

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

## Linux GUI — moduł 1 (2026-10-28)

GUI Linux przesunięto przed Image AI na polecenie właściciela. Zachowano checkout,
backend i dotychczasowe kontrakty. Dodano natywnego klienta Qt6/PySide6 6.8.3:
czat, katalog GGUF/HF, ustawienia PL/EN i motywów, diagnostykę oraz asynchroniczny
transport REST/SSE. Własny backend otrzymuje losowy token w środowisku, słucha
loopback i jest zamykany asynchronicznie; parent-death guard chroni także awarię GUI.
Istniejący serwer jest używany przez API bez przejmowania jego procesu.

Weryfikacja: 6 testów GUI PASS (rzeczywisty backend HTTP, auth, import strukturalnego
fixture GGUF, rozmowy/historia, preferencje, restart, zamykanie). Fixture nie stanowi
dowodu inferencji. Osobno wykonano **rzeczywisty test GGUF bez Ollamy: 1 PASS**
(`integration/test_llama_real.py`) i pełny smoke natywnego GUI: import, load, nowa
rozmowa, odpowiedź SSE, historia i zamknięcie. Model:
`bartowski/SmolLM2-135M-Instruct-GGUF/SmolLM2-135M-Instruct-Q4_K_M.gguf`,
105454432 B, Apache-2.0, SHA-256
`2e8040ceae7815abe0dcb3540b9995eaa1fa0d2ca9e797d0a635ae4433c68c2d`.
Silnik CPU: llama.cpp `c3df4b7e22a1ac38da663552d19e649dd97ca936`.
GUI otrzymało 48 tokenów, około 7.29 tok/s; to pojedyncza obserwacja chmury,
nie benchmark sprzętu użytkownika. Bez testu CUDA/Ollamy/CachyOS/Wayland.

AppImage, dodatkowe testy GUI, benchmarki Rust i integracja main pozostają następnymi
modułami. API GitHub oraz uploads.github.com stały się dostępne po zmianie runtime.
Nie utworzono jeszcze release ani nie zmieniono main.

## Linux GUI — moduł 2: stabilizacja (2026-10-28)

Rozszerzono diagnostykę o uwierzytelnione, tylko odczytywane API sprzętu i zadań
bez promptów/tokenów. Dodano obsługę nowego oficjalnego CDN HF `us.aws.cdn.hf.co`
z zachowaniem HTTPS, ograniczeń redirectów i braku przekazywania tokenu do CDN.
Poprawiono porównywanie sekwencji między kolejnymi zadaniami i lifecycle obiektów
QtNetwork po zamknięciu; test SSE ujawnił natywną awarię przy przedwczesnym
niszczeniu transportu, usuniętą przez własność QObject i wygaszanie callbacków.

Wynik po poprawkach: **126 PASS = 116 backend + 10 GUI** przez rzeczywisty X11/Xvfb.
Wszystkie wcześniejsze 115 testów zachowano. Osobno **1 PASS rzeczywistego GUI GGUF**:
streaming, żywy event loop Qt, kopiowanie, druga generacja, anulowanie, historia,
restart i zamknięcie. **1 PASS rzeczywistego HF**: metadane, transfer, cancel/resume,
SHA-256 oraz import. Są to osobne testy integracyjne wymagające środowiska/sieci;
nie wchodzą do domyślnego CI bez wag.

Pierwszy lokalny AppImage (jeszcze przed końcowymi poprawkami) przeszedł uruchomienie
z własnym backendem i realną inferencją przez dołączony CPU llama.cpp. Sprawdzono
też jego start przez X11 bez dodatkowego LD_LIBRARY_PATH. Końcowy plik będzie
zbudowany ponownie z poprawkami; jego suma zostanie podana w późniejszym raporcie.

## Linux GUI — moduł 3: pakowanie i decyzja Rust (2026-10-28)

Dodano powtarzalny build AppImage (PyInstaller, przypięty i zweryfikowany runtime,
SquashFS, względny RPATH silnika CPU, manifest, licencje, .desktop, ikona i SHA-256),
workflow Linux oraz test dwukrotnego uruchomienia rzeczywistego pliku.
Naprawiono trwałość konfiguracji silnika: zmienna ścieżka mount/ekstrakcji AppImage
nie jest zapisywana jako stała ścieżka llama-server. Jest osobny test remount.
Pierwszy AppImage uruchomiono przez X11 i offscreen z realną generacją; końcowy
build po tych poprawkach i jego suma pozostają do raportu walidacyjnego.

Pomiary Python zapisano w benchmarks/linux-cpu-baseline.json; metoda i surowe
próbki są jawne. Dla realnego GGUF 105454432 B mediany: parser 199.6 ms,
import referencji 299.1 ms, SHA-256 114.8 ms, 10000 operacji kolejki 14.5 ms,
proxy startu interpretera 26.8 ms. Syntetyczny plik 4 GiB (to samo metadata,
sparse padding; nie wagi do inferencji): parser 211.1 ms i SHA-256 4649.0 ms.
Bez wykazanej korzyści end-to-end nie wdrażamy Rust. Granica projektu, PyO3/maturin,
izolowany worker, fallback, koszty ABI/Linux/Android/Web i bramki akceptacji
są w native/README.md. Nie utworzono pustych crate'ów.

Test zmian remount/CDN i GUI: 20 PASS. Dokumentacja Linux/AppImage, README,
architektura i roadmapa zaktualizowane. Kolejny krok: pełny zestaw, końcowy obraz,
ruch GitHub/PR, CI, integracja main dopiero po weryfikacji oraz szkic wydania.

## Checkpoint Linux / początek Android

- Checkout przy wznowieniu był czysty; engines.py nie miał niezapisanych zmian.
  Dispatcher frozen/Python i guard zostały zapisane w 27a61e3; późniejsze commity
  Linux: 81e524e, 8ee0fe4, 9b241e3.
- Poprawione CI: Backend foundation oraz Linux desktop and AppImage **SUCCESS**
  dla 9b241e3. Run Linux: 40762926217; artefakt jest rzeczywiście na GitHubie.
- Pobrano paczkę CI Ubuntu 22.04 i wykonano dodatkowy rzeczywisty test GGUF
  przez X11: GUI/backend/dołączony llama.cpp CPU, streaming, historia, PL/EN,
  light/dark/system, restart i zamknięcie własnego backendu **PASS**.
- AppImage do dystrybucji to **paczka CI**, nie wcześniejszy lokalny build Debian:
  SHA-256 `07397174bcbc7cf6e9f14b8193881cb71b4b04ab5c30c3c908ce053cd3dab2c2`.
- Szkic wydania v0.1.0-alpha.1 istnieje (ID 427506837), draft=true. Bezpośredni
  upload z cloud zwrócił 401 mimo działającego API; nie zadeklarowano załączników.
  Przygotowano workflow przesyłania istniejącego artefaktu przez GITHUB_TOKEN Actions,
  z obowiązkowym sprawdzeniem draft=true; bez publikacji wydania.
- Właściciel rozszerzył zakres o natywnego Androida Kotlin/Compose jako klienta
  istniejącego API. Bez WebView i bez inferencji na telefonie. Image AI/Web nadal
  nie są realizowane; Rust nadal wyłącznie po uzasadnionych pomiarach.

## Android — moduł 1: natywny klient i lokalny APK

Zaimplementowano Kotlin/Compose/Material 3: Home, czat/historię, nowe rozmowy,
rename/delete, wybór modelu, streaming SSE/cancel, katalog/import ścieżki backendu,
load/unload, informacje o silnikach, ustawienia połączenia, PL/EN i system/light/dark.
Klient nie zawiera WebView, inferencji, wag ani modułu Rust.

Token jest szyfrowany AES-GCM przez Android Keystore, backup wyłączony; UI nie
zapisuje tokenu w stanie Activity i nie ma loggera requestów. HTTP wymaga zgody
na zaufany LAN i prywatnego IPv4; publiczne hosty wymagają HTTPS. Redirecty są
wyłączone, token nie jest automatycznie ponownie używany dla innego origin.

Lokalnie wykonano **14 testów JVM PASS**, Android lint **PASS**, assembleDebug
oraz assembleDebugAndroidTest **PASS**. Powstał rzeczywisty podpisany testowo APK
ARM64, sprawdzony przez apksigner/aapt (ID, wersja, API 26+, ABI arm64-v8a).
Pierwsza suma lokalnego APK: `7a810fb4115087557c13f65c8bc63f007f32701b81f6ccf4e64cf947e3c24c0d`.
To nie jest jeszcze końcowa paczka CI — debug signing i środowisko zmieniają bajty.

Nie uruchomiono lokalnie testu instalacji/UI: brak /dev/kvm i telefonu. Test Compose
z kontrolowanym backendem HTTP/SSE i rzeczywistym Keystore jest przygotowany oraz
skompilowany; będzie uruchomiony przez emulator x86_64 w GitHub Actions. Nie oznacza
on realnej inferencji ani instalacji na fizycznym ARM64. Backend GGUF jest osobno
rzeczywiście sprawdzony na Linuxie. Instrukcja LAN/TLS/build: docs/ANDROID.md.

AppImage i checksum są już załączone do szkicu wydania (ID 427506837), state=uploaded,
draft=true, digest AppImage `07397174bcbc7cf6e9f14b8193881cb71b4b04ab5c30c3c908ce053cd3dab2c2`.
Przesłanie przez Actions 40825408523 powiodło się po 401 bezpośredniego uploadu z cloud.

## Android — moduł 2: odzyskiwanie połączenia i anulowanie

Poprawiono lifecycle sieci: żądania OkHttp są asynchroniczne i anulowanie coroutine
zamyka rzeczywiste połączenie; health sprawdza kontrakt, a reconnect zwalnia stary
transport i odtwarza obserwację zadania. Zmiana serwera czyści projekcję danych,
aby nie wykonywać operacji z poprzednim klientem/tokenem. Rozłączenie zachowuje
historię w backendzie; opóźnione callbacki poprzedniej sesji są odrzucane.

Lokalnie: **16 testów JVM PASS**, lint, ARM64/x86_64 APK i AndroidTest APK **PASS**.
Dodatkowe testy sprawdzają rzeczywiste zamknięcie HTTP przy cancel coroutine oraz
odrzucenie obcego serwera HTTP 200 bez prawidłowego health.

CI dla wcześniejszego klienta przeszedł build/JVM/lint, ale jego helper pakujący
uruchomiono domyślnym Pythonem Ubuntu 22.04 bez hashlib.file_digest. Dodano jawny
Python 3.12 do workflow i poprawiono cache Gradle. Emulator nie był jeszcze
uruchomiony w tym checkpointcie; nie deklarujemy jego testu jako PASS.

Dodatkowa analiza ELF AppImage CI potwierdziła wymagane symbole do **GLIBC 2.35**.
Wcześniejszy lokalny build Debian wymaga GLIBC 2.39; nie jest tym samym artefaktem.

## Stabilizacja klientów i testów przed integracją

- Rzeczywisty test natywnego Androida na emulatorze API 30 x86_64 wykonał
  **1 test, 0 błędów, 0 pominiętych** (CI 40828606136). Workflow zatrzymał się
  dopiero na pobraniu screenshotu z katalogu aplikacji, usuniętego przez cleanup
  po testach. Przeniesiono zapis testowego screenshotu do Download i poprawiono
  pobieranie artefaktu. Nie uznajemy całego workflow za SUCCESS przed powtórzeniem.
- Poprawiono czyszczenie widoku po usunięciu rozmowy w obu klientach. Linux ma
  jedną linię poprawki i test regresyjny pamięci odpowiedzi; nie przepisano GUI.
  Nowy AppImage z tą poprawką wymaga własnej weryfikacji i nowej checksumy.
- Android zapisuje wybór modelu przez istniejący PATCH rozmowy. Generowanie
  zachowuje parametry rozmowy/backendu zamiast nadpisywać je domyślnymi klienta.
  Ponowienia zachowują request_key. Dodano testy kontraktu wyboru modelu i braku
  niezamierzonego nadpisania parametrów.
- Lokalnie **130 PASS**: 117 backend + 11 Linux GUI + 2 rzeczywiste GGUF/GUI,
  z poprawkami czyszczenia i testu lifecycle. Android: **18 testów JVM PASS**,
  lint i oba APK/debug oraz AndroidTest APK zbudowane. Emulator dla końcowej
  poprawki pozostaje do ponowienia w CI.
- Błąd backend CI był wyścigiem samego testu /proc: proces zdążył zniknąć między
  exists/open/read. Odczyt obsługuje teraz ENOENT/ESRCH jako zakończenie procesu,
  zachowując asercję i limit czasu. Nie wyłączono testu ani nie zmieniono guard.


## Raport końcowy — Linux AppImage i Android APK

### Kod, historia i main

- Zapisano i wysłano wszystkie ukończone zmiany. engines.py nie miał pominiętego
  diffu przy wznowieniu; dispatcher frozen/guard jest w `27a61e3` i na main.
- Główne commity Linux: `27a61e3` GUI/lifecycle, `81e524e` realne testy i stabilizacja,
  `8ee0fe4` AppImage/benchmarki/Rust, `9b241e3` XCB/CI.
- Główne commity kontynuacji: `edfa8b3` draft-assets, `dfe529c` Android,
  `82429c3` zgodność SDK, `987ca10` odzyskiwanie HTTP i bezpieczne sesje,
  `21acff0` końcowa stabilizacja, trwały model rozmowy i czyszczenie widoku.
- [PR #3](https://github.com/vex2137/OmniCore/pull/3) jest zamknięty jako **MERGED**.
  Commit merge: `ad03290f3c050617b6a74e81c5c49bf6b537e0d9`.
  Main potwierdzono przez GitHub API, fetch i ls-remote. Brak force push i resetu;
  dotychczasowa historia oraz checkout są zachowane. Feature branch pozostał.

### Zmienione moduły

- `backend/src/omnicore/desktop`: osobny klient Qt, REST/SSE, własny backend,
  lokalizacje, widoki, prywatna konfiguracja, lifecycle i dispatcher AppImage.
- `backend/src/omnicore/diagnostics.py`, addytywne API diagnostyki i snapshot kontraktu;
  zachowano endpointy, migracje, auth/CORS/limity i dotychczasowe funkcje backendu.
- `apps/android`: niezależny Gradle/Kotlin/Compose/Material 3, bez WebView,
  Keystore, polityka połączeń, stan/transient cache przez API i zasoby PL/EN.
- `desktop/tests`, testy JVM/instrumentacyjne Android, osobne `integration/` dla
  prawdziwego GGUF/GUI/HF, testy remount i race lifecycle.
- `packaging/linux`, skrypty budowania/pakowania/testowania, workflow Linux/Android/
  draft-assets; `native/README.md` i `benchmarks/` z rzeczywistymi pomiarami Python.
- README, ARCHITECTURE, ROADMAP, LINUX_DESKTOP, APPIMAGE, ANDROID, PROGRESS i zrzuty UI.

### Wykonane testy

| Zestaw | Wynik i granica dowodu |
| --- | --- |
| Poprzednie 115 testów | Zachowane; obecnie 117 testów backendu PASS |
| Native Linux GUI | 11 PASS przez X11/Xvfb; rzeczywisty backend HTTP |
| Realny GGUF bez Ollamy | 1 PASS backend + 1 PASS GUI: import/load/stream/cancel/history/restart/unload |
| Łączny lokalny zestaw Python | **130 PASS**, 0 FAIL/skip |
| Android JVM + PL/EN | **18 PASS**, 0 FAIL/skip |
| Android lint i build | PASS, podpisane APK ARM64/x86_64 oraz AndroidTest APK |
| Emulator Android API 30 x86_64 | **1 PASS**, 0 FAIL/skip: natywny Compose, HTTP/SSE, Keystore, modele, historia, cancel, rename/delete, PL/EN i motywy |
| Prawdziwy HF | Osobno PASS: metadata, cancel/resume, checksum i import |
| Końcowy AppImage z CI | Dwukrotny rzeczywisty start przez X11, realny GGUF, trwałość historii/PL/EN/theme, brak osieroconego backendu — PASS |
| Końcowy APK z GitHub Release | Pobrany ponownie, SHA-256 zgodny, apksigner verify i aapt ID/wersja/ABI — PASS |
| Kontrakty/Ruff/format/smoke | PASS |
| Fizyczny ARM64 / CUDA / CachyOS / Wayland / realna Ollama | Niewykonane, nie oznaczono jako PASS |

Model testowy CPU: `bartowski/SmolLM2-135M-Instruct-GGUF/SmolLM2-135M-Instruct-Q4_K_M.gguf`,
105454432 B, Apache-2.0, SHA-256
`2e8040ceae7815abe0dcb3540b9995eaa1fa0d2ca9e797d0a635ae4433c68c2d`.
Silnik `c3df4b7e22a1ac38da663552d19e649dd97ca936`. Nie deklarujemy zgodności wszystkich modeli.

### CI i rzeczywiste artefakty

- [Backend dla źródła 21acff0](https://github.com/vex2137/OmniCore/actions/runs/40831766311): SUCCESS.
- [Linux AppImage 21acff0](https://github.com/vex2137/OmniCore/actions/runs/40831766310): SUCCESS; źródło wybranej paczki.
- [Android APK + emulator 21acff0](https://github.com/vex2137/OmniCore/actions/runs/40831766245): SUCCESS, łącznie z attach-draft.
- [Backend po merge](https://github.com/vex2137/OmniCore/actions/runs/40833603147): SUCCESS.
- [Linux po merge](https://github.com/vex2137/OmniCore/actions/runs/40833603144): SUCCESS.
- [Android po merge](https://github.com/vex2137/OmniCore/actions/runs/40833603057): SUCCESS.
- [Aktualizacja AppImage w szkicu](https://github.com/vex2137/OmniCore/actions/runs/40833916234): SUCCESS.

[Szkic wydania](https://github.com/vex2137/OmniCore/releases)
pozostaje niepubliczny i wymaga dostępu właściciela. Potwierdzono API `state=uploaded`
i rzeczywiste pobranie plików. Oba źródłowe artefakty Actions również istnieją.

| Plik | SHA-256 |
| --- | --- |
| `OmniCore-0.1.0-alpha-x86_64.AppImage` | `a2a9cd06e994f33f2fcbce82a43109a22d1a959d16ec7b83f552c9ec650648a7` |
| `OmniCore-0.1.0-alpha-android-arm64.apk` | `cba87129fe7f4f8136ca3a9a52527b10a2160e016d039ee4674f7f91dc0aa904` |

Do obu plików dołączono `.sha256`. To paczki CI ze źródła `21acff0`; wcześniejsze
lokalne sumy i starsze paczki w historycznych raportach nie są sumami końcowej dystrybucji.
AppImage: x86_64, glibc >=2.35, Python/Qt/backend i CPU llama.cpp, bez wag.
APK: Android Debug/test signature, ID `io.github.vex2137.omnicore`, versionCode 1,
minSdk 26/target 35, arm64-v8a. Instalację/UI sprawdzono na odpowiedniku x86_64,
nie na fizycznym ARM64. Nie ma inferencji na telefonie ani wymogu Rust.

Instrukcje: [Linux](LINUX_DESKTOP.md), [AppImage](APPIMAGE.md), [Android i LAN/TLS](ANDROID.md).
Zrzuty rzeczywistych interfejsów: [Linux](images/linux-desktop.png), [Android](images/android-chat.png).
Zrzut Androida i test UI używają kontrolowanego backendu protokołu.

### Następne zadania

Test fizycznego ARM64 i CachyOS/RTX 4060, macierz CUDA/Wayland/Ollama oraz osobna
procedura produkcyjnego podpisu APK. Image AI i Web pozostają dalszym zakresem,
nie rozpoczęto ich w tym zadaniu. Publiczna publikacja wymaga osobnego potwierdzenia.
Rust pozostaje opcjonalny zgodnie z pomiarami i native/README.md.

### Android część 2 — moduł danych i cyklu życia

Nowy zestaw JVM: **33 PASS**, 0 FAIL/error/skip (17 dotychczasowych transportu,
12 ViewModel, 3 download/parametry/SSE, 1 zgodności zasobów). Regresja Python/Qt:
130 PASS. Testy potwierdzają odłączenie bez cancel, jawny Stop, ponowne odczytanie
zadania, idempotency key, wybór modelu i brak utraty zaawansowanych parametrów.
Toolchain zaktualizowany do API 36 / AGP 8.13.2 / Gradle 8.13 ze zweryfikowanym
wrapperem i sumą dystrybucji. Lint, pakowanie i emulator pozostają w weryfikacji.

### Android część 2 — GUI, narzędzia i APK

Pełny lokalny build API 36: **BUILD SUCCESSFUL**, lint PASS, assembleDebug i
assembleDebugAndroidTest PASS. Skrypt pakowania potwierdził application ID,
versionCode 2/versionName Alpha.2, target 36, podpis debug, ARM64 oraz ZIP/ELF
alignment >=16 KiB. Lokalny plik jest rzeczywistym APK, nie dowodem instalacji
na telefonie. Dystrybucja końcowa będzie wskazywać osobny, zweryfikowany plik CI.

GUI: działające HF search/files/confirmation/download/progress/pause/resume/import,
edycja parametrów rozmowy, filtrowanie silników, diagnostyka API/zadań, systemowy
Wstecz i animowana nawigacja. Dodano test UI powrotu z tła/rekreacji oraz transferu.
Workflow CI obejmuje emulatory API 30 i 36; wyników jeszcze nie potwierdzono.
