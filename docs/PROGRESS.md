# OmniCore — PROGRESS

## Alpha.3 — stabilizacja w toku

Audyt: czysty lokalny i zdalny main `b1c9a520441c2a785daad32e8b8a4591c3f28bce`,
brak otwartych PR; Alpha.2 publiczna z pięcioma faktycznymi assetami. Nowa gałąź
`feature/alpha-3-stability`, bez resetu lub dodatkowego checkoutu.

Zakres: Android (pierwszy język, nawigacja, konfiguracja, status/reconnect/retry),
Linux (pierwszy start, QPA X11/Wayland, diagnostyka i lifecycle), synchronizacja
klientów i wyścigi backendu. Osobne commity, regresja/realny GGUF, paczki Alpha.3
i CI oraz **szkic** wydania. Zgoda na publiczną Alpha.2 nie obejmuje Alpha.3.
Nie wdrażamy Image AI ani nowego silnika/Rust.

Ryzyka: wyścig kolejki ze sprzątaniem engine, blokady mutacji rozmowy względem
submit, niedostępny fizyczny ARM64/HyperOS i natywna sesja CachyOS. Wayland/Arch
będą raportowane tylko po faktycznym uruchomieniu w opisanym środowisku.


## Alpha.2 — dostarczone i opublikowane (2026-10-29)

[Publiczne wydanie v0.1.0-alpha.2](https://github.com/vex2137/OmniCore/releases/tag/v0.1.0-alpha.2)
opublikowano na wyraźne polecenie właściciela o 12:02:58 UTC. GitHub potwierdził
`draft=false`, `prerelease=true`, `published_at` oraz 5 faktycznie przesłanych assetów.
Pobrano oba binaria ze szkicu przed publikacją i zweryfikowano sha256sum -c;
po publikacji strona i oba pliki odpowiedziały HTTP 200 bez tokenu klienta.

[PR #4](https://github.com/vex2137/OmniCore/pull/4) **MERGED**, commit wydania/tag/main
w chwili scalenia: `a0593d06be295f3c7e3e2d8b17e8ea2afc51fc7b`. API i ls-remote
potwierdziły main; tag v0.1.0-alpha.2 wskazuje ten sam commit. Commit raportu może
być późniejszy. Gałąź feature/android-part-2 zachowana na
`e9fd8547088ca8136fe6a4ae78277e3d183679ee` (źródło dostarczonego APK).
Nie nadpisano historii ani publicznych assetów Alpha.1.

Android: natywny Kotlin/Compose/Material 3, repozytorium/Flow/StateFlow, REST/SSE,
Keystore, czat/history/CRUD/model/stream/stop/copy, HF GGUF download manager,
parametry generowania, PL/EN/motywy, diagnostyka i poprawiona klawiatura/scroll.
Tło/rozłączenie nie anuluje generacji serwera; jawny Stop wysyła cancel. Linux,
backend produkcyjny i kontrakty zachowane. Brak WebView i inferencji telefonu.
Rust pozostaje opcjonalny; Image AI/Web poza tym etapem.

| Wykonana walidacja | Wynik |
| --- | --- |
| Android JVM + PL/EN | **34 PASS**, 0 fail/error/skip |
| Lint/build/podpis/ZIP i ELF 16 KiB | **PASS** |
| Natywny UI/HTTP-SSE/Keystore/tło/rekreacja/HF na emulatorach 30 i 36 | **1 PASS na każdy API**, 0 skipped |
| Końcowe CI backend + Qt bez GPU | **128 PASS** (117 backend + 11 Qt) |
| Rzeczywisty AppImage dwukrotnie, trwałość i zamykanie własnych procesów | **PASS** |
| Wcześniejsza lokalna regresja Python/Qt + 2 realne GGUF | **130 PASS** |
| Oddzielny realny klient Kotlin/FastAPI/llama.cpp/SmolLM2 CPU | **1 PASS**, bez fixture inferencji |
| Fizyczny ARM64/POCO/Xiaomi/HyperOS | **NIEWYKONANE** |

Końcowe CI źródła e9fd854: [APK push](https://github.com/vex2137/OmniCore/actions/runs/40868744901),
[APK PR](https://github.com/vex2137/OmniCore/actions/runs/40868751105),
[Linux](https://github.com/vex2137/OmniCore/actions/runs/40868751121),
[backend push](https://github.com/vex2137/OmniCore/actions/runs/40868745078),
[backend PR](https://github.com/vex2137/OmniCore/actions/runs/40868751232): wszystkie **SUCCESS**.
[Upload APK](https://github.com/vex2137/OmniCore/actions/runs/40869838047): **SUCCESS**,
weryfikacja źródła/runu/draft i SHA-256 przed wysłaniem przez GITHUB_TOKEN.

| Asset publicznego wydania | Rozmiar B | SHA-256 |
| --- | ---: | --- |
| [APK ARM64](https://github.com/vex2137/OmniCore/releases/download/v0.1.0-alpha.2/OmniCore-0.1.0-alpha-android-arm64.apk) | 18160061 | `3700cfc24670d28a4ad42ad73a5d3f0268ed81c4b3cea35677dc23a9c2ad4b4a` |
| [AppImage x86_64](https://github.com/vex2137/OmniCore/releases/download/v0.1.0-alpha.2/OmniCore-0.1.0-alpha-x86_64.AppImage) | 98650616 | `a2a9cd06e994f33f2fcbce82a43109a22d1a959d16ec7b83f552c9ec650648a7` |

Dołączono oba pliki .sha256 i android-build.json. APK: minSdk 26, target/compile 36,
versionCode 2, io.github.vex2137.omnicore, Android Debug/test key. AppImage identyczny
z Alpha.1, zawiera CPU llama.cpp/Python/Qt, bez wag. Dane są poza paczką.
Fizyczny telefon, CUDA, CachyOS/RTX 4060 i Wayland pozostają niezweryfikowane.
Różne klucze debug mogą wymagać deinstalacji starego APK; historia zostaje w backendzie.

Moduły zapisano w logicznych commitach: `2eafa86`, `da3a557`, `9f560d8`, `909bcf0`,
`f9d33f3`, `73a1a0c`, `272256c`, `a2a1bed`, `523133f`, `e9fd854`; wszystkie zachowane
na GitHubie i w merge commit. Następne zadanie: fizyczny ARM64/Android 16 i stały
klucz podpisu. Kolejna publiczna publikacja wymaga nowej zgody właściciela.


## Historia realizacji Androida, część 2 (2026-10-29)

Audyt: czysty main `2e78daa0035ff0858c33fc387468b078100e3fd8`, PR #3 scalony,
brak otwartych PR na starcie. GUI Linux i AppImage zachowane. Publiczna Alpha.1
została opublikowana po późniejszej, wyraźnej zgodzie właściciela; historyczne
opisy szkicu poniżej odnoszą się do wcześniejszego punktu kontrolnego.

Gałąź: `feature/android-part-2`. Rozwijamy istniejącego klienta, nie tworzymy go
od nowa. Implementacja: granica OmniRepository + Flow/StateFlow, odłączenie SSE
bez cancel w tle, ponowne obserwowanie zadania/historii, HF download manager,
parametry rozmowy zachowujące GPU, target/compile 36 i kontrola stron 16 KiB.

Regresja wykonana w tej sesji: **130 PASS** (backend/Qt i dwie rzeczywiste
integracje GGUF/GUI), 56.54 s. Android: **34 JVM PASS**, lint/build PASS; rzeczywisty Kotlin/FastAPI/GGUF: **1 PASS**.
CI emulatorów pozostaje w weryfikacji. Właściciel zezwolił na publiczną Alpha.2.
Telefon fizyczny, POCO/Xiaomi i lokalna inferencja telefonu pozostają niezweryfikowane.

## Historyczny status Alpha.1

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

### Android część 2 — rzeczywisty klient i odzyskanie połączenia

Checkout i commity zachowane po przerwie środowiska. Rerun JVM: **34 PASS**,
0 fail/error/skip (w tym SSE reconnect i nowy ViewModel odtworzony ze stanu).
`RealBackendTest` przez `scripts/test_android_real.py`: **1 PASS**, 22 s Gradle,
bez fixture inferencji. Kotlin połączył się z prawdziwym FastAPI/llama.cpp CPU
oraz SmolLM2 Q4_K_M: import/load, wiele snapshotów, niepusta odpowiedź,
odłączenie bez cancel, jawny cancel, trwała historia przez nowy klient i unload.
To test transportu z rzeczywistym AI, nie test instalacji na telefonie.
Ruff/format/contracts/diff check PASS. Moduły `2eafa86` i `da3a557` zachowane;
push `da3a55783658121c5f464aec34fa404a4a7c3abf` potwierdzony, PR #4 jako draft.
Emulatory 30/36 są w weryfikacji, fizyczny POCO/Xiaomi pozostaje nietestowany.

Właściciel polecił publikację Alpha.2. Najpierw zostanie przygotowany draft
z faktycznie przesłanym APK/checksum, następnie publikacja po sprawdzeniu paczki.
Publiczna Alpha.1 pozostaje bez zmian. Linux AppImage nie wymaga przebudowy:
Alpha.2 może załączyć identyczny, wcześniej sprawdzony plik z jawną informacją.

### Poprawka pierwszego połączenia wykryta przez emulator

Run `40856903928` dla `9f560d8`: build/lint/JVM i pakowanie PASS, oba natywne UI
FAIL na pierwszym połączeniu. Przyczyną był warunek enabled przycisku konfiguracji
wymagający już connected=true. Naprawiono go: pierwszy connect/reconnect jest
aktywny, gdy klient nie jest busy i nie zmienia aktywnej połączonej generacji.
Test UI sprawdza teraz assertIsEnabled przed kliknięciem. Nie osłabiono auth,
Keystore ani polityki LAN/HTTPS. Publikację zatrzymano; wymagany nowy poprawny CI.

### Synchronizacja testu automatycznego przewijania

Push run `40865054040` dla `909bcf0`: oba emulatory 30/36 PASS. PR run
`40865061582`: API 36 PASS, API 30 FAIL na natychmiastowym assertIsDisplayed
po statusie Completed. Treść była już w drzewie; animacja przewijania nie zakończyła
się w tej samej klatce. Test oczekuje teraz (maks. 10 s) rzeczywistej widoczności
odpowiedzi, zachowując końcową asercję i sprawdzanie automatycznego przewijania.
Nie dodano sleep, nie usunięto asercji i nie zmieniono aplikacji. Wymagany nowy CI.

### Stabilizacja istniejącego testu backendu

PR backend run `40866059597` ujawnił wyścig w istniejącym teście idempotencji:
po await drugiego submit zadanie mogło już zakończyć się i zniknąć z manager.tasks.
Test zachowuje teraz Task natychmiast po pierwszym submit i oczekuje tej samej
referencji. Wszystkie asercje trwałości, treści, metryk i idempotencji zachowano.
Kod backendu i kontrakty nie zostały zmienione. Push backend run `40866050449`
dla tego samego kodu wcześniej PASS; wymagamy ponownej walidacji poprawki testu.

### Poprawka widoku czatu przy zmianie rozmiaru klawiatury

Run `40866050470`: API 36 PASS, API 30 FAIL na widoczności odpowiedzi mimo
oczekiwania. Samo oczekiwanie na animację nie rozwiązało problemu. Kontener
Scaffold konsumuje teraz własne insets, aby imePadding nie naliczał ponownie
wysokości dolnego paska, a automatyczne przewijanie reaguje również na zmianę
wysokości viewportu (IME/orientacja), nie tylko liczbę wiadomości/sekwencję.
Ustawienia mają imePadding, więc pola i przycisk połączenia pozostają osiągalne
przy otwartej klawiaturze. Test wciąż wymaga rzeczywistej widoczności odpowiedzi;
CI zachowuje zrzut i geometrię fixture także przy błędzie, bez tokenów/headers.

### Budżet testu częściowej odpowiedzi przy timeout

Linux CI `40866965677`: 127 PASS, 1 FAIL w starym teście partial-history/timeout.
Budżet 100 ms obejmował także rzeczywiste SQLite i thread-pool; na runnerze wygasł
przed pierwszym chunkiem, dlatego nie było częściowej treści. Ustawiono 3 s,
zgodnie z domyślnym budżetem fixture. Test nadal rzeczywiście doprowadza do
engine_timeout i wymaga dokładnej częściowej odpowiedzi, właściwego stanu historii
oraz wszystkich dotychczasowych asercji. Bez sleep, pomijania ani zmiany backendu.

### Obserwacja viewportu bez pętli rekompozycji

Run `40866959073`, API 30: Compose zgłosił stale oczekujące rekompozycje po
wprowadzeniu odczytu layoutInfo w kompozycji. Wysokość viewportu jest teraz
obserwowana przez derivedStateOf, więc nowe obiekty layoutInfo przy każdym kroku
scroll nie unieważniają całego widoku. Klucz efektu zależy wyłącznie od faktycznej
zmiany wysokości. Diagnostyka testu najpierw robi zrzut i nie maskuje pierwotnego
wyjątku, jeśli zapytanie o semantykę nie może czekać na idle.

### Zachowanie statusu testu w skrypcie emulatora

Raport XML source `523133f`, API 30: **1 PASS, 0 fail/error/skip**. Poprawki
widoku przeszły pełny natywny przepływ. Krok workflow zgłosił błąd po teście:
android-emulator-runner uruchamia linie script w osobnych powłokach, więc zmienna
test_status nie przechodziła do końcowego exit. Przeniesiono ten krok do jednego
scripts/test_android_emulator.sh. Skrypt zachowuje kod Gradle, zbiera dostępne
zrzuty również przy błędzie i zwraca pierwotny status. bash -n PASS; nowy CI wymagany.

### Alpha.3 — moduł synchronizacji backendu

Implementacja: semafor obejmuje także cleanup/unload po błędzie/anulowaniu;
serialized cancel i shield zakończenia chronią cleanup przed kolejnym klientem
lub odłączeniem żądania. Mutacje rozmów/modelu są blokowane względem submit.
Publiczne trasy, schematy i SQLite pozostają kompatybilne.

Wykonane: **123 backend PASS**, 0 FAIL (117 dotychczasowych + 5 deterministycznych
przypadków konkurencji + 1 przypadek dwóch rzeczywistych transportów HTTP).
Test dwóch klientów obejmuje wspólną historię, detach SSE bez cancel, odrzucenie
mutacji aktywnej rozmowy/modelu, cancel obserwowany przez drugi strumień i zapis
częściowej historii. Kontrolowany silnik nie dowodzi inferencji.
OpenAPI/JSON Schema snapshots: export_contracts.py --check PASS, bez zmian.

### Alpha.3 — moduł Android UX/połączenie

Pierwszy odczyt języka wybiera PL/EN z listy języków systemu i zapisuje wynik;
ręczny wybór ma pierwszeństwo po restarcie. Nawigacja telefonu używa krótkich
lokalizowanych nazw i dwóch linii bez ellipsis, zachowując pełne opisy dostępności.
Dodano pierwszy ekran z rzeczywistą konfiguracją komputera, statusy connecting/
connected/disconnected/auth, sticky auth po zamknięciu banera, obsługę onLost,
reconnect po błędzie pollingu i ręczne odświeżanie rozmów/modeli. Wyślij ponownie
używa ostatniej wiadomości; retry niepotwierdzonego POST zachowuje request_key,
a jawny retry zakończonego żądania tworzy nowy. Terminalny snapshot nie wraca do running.

Wykonano **42 JVM PASS**, 0 fail/skip (34 istniejące + 4 polityki języka/statusu
+ 4 ViewModel sieć/retry/synchronizacja). Lokalny lint i assembleDebugAndroidTest PASS.
Dodano test instrumentacyjny pierwszego języka i trwałości ręcznego wyboru;
nie był jeszcze uruchomiony na emulatorze w tym etapie. Fizyczny telefon nieobecny.

### Alpha.3 — zapisany moduł Linux UX/transport

16 testów desktop PASS, 0 FAIL. Działają onboarding/import, reconnect własnego
backendu bez zmiany PID, synchronizacja usunięcia rozmowy, obserwowanie zadań
z historii, izolacja starych odpowiedzi HTTP oraz eksport raportu o zamkniętym
schemacie (bez tokenów, ścieżek i treści), plik 0600. Logi odrzucają nieznane kody.
Wybór QPA respektuje jawny override i wybiera Wayland/X11 według sesji; test
wyboru nie jest testem natywnego CachyOS/Wayland. AppRun izoluje hostowe pluginy Qt.
Backend 123 PASS zapisany wcześniej w 5e25533, Android 42 JVM PASS w 99a5b27.

### Alpha.3 — odpowiedzi, tożsamość modelu i statystyki

129 backend PASS (123 poprzednie + 6 przypadków regresji). Rzeczywisty test
SmolLM2-135M-Instruct-Q4_K_M przez llama.cpp na CPU: 1 PASS, bez Ollamy;
potwierdzono treść, liczniki wejścia/wyjścia, TTFT, czas, kontekst, finish_reason
oraz zapis metadanych w historii. Nie testowano wag LFM3/Qwen użytkownika.
Parser zachowuje reasoning oddzielnie, rozpoznaje odpowiedź JSON i SSE, usage oraz
finish_reason. Domyślnie żąda wyłączenia thinking przez opcje szablonu (zależne od
modelu). Brak finalnej odpowiedzi jest błędem, reasoning-only z length ma własny
komunikat; nie zwiększamy automatycznie kontekstu ani limitu. Błąd przekroczenia
kontekstu jest odróżniony od OOM. Nowe pola kontraktów są opcjonalne/defaultowane;
stare dane i odciski idempotency pozostają zgodne. Nazwa modelu jest snapshotem
wiadomości, zachowanym przy zmianie nazwy/modelu, restarcie i eksporcie/importcie.
TTFT mierzony od rozpoczęcia wykonania (bez kolejki, z ładowaniem), osobno czas
ładowania i pierwszego tekstu odpowiedzi. Liczby tokenów i tok./s pochodzą z silnika;
brak danych pozostaje null, wykorzystanie kontekstu = raportowane wejście+wyjście.

### Alpha.3 — widok rozmowy Linux i metadane klientów

18 desktop PASS: natywne dymki z nazwą modelu zapisaną w wiadomości, bezpieczny
Markdown (bez HTML i dostępu do zasobów lokalnych/zdalnych), osobne bloki kodu
z kopiowaniem, kopiowanie wiadomości, lokalizowane statystyki i zwijane rozumowanie.
Wyszukiwanie historii przeszukuje wiadomości przez istniejące API; nie gubi
bieżącej rozmowy przy filtrowaniu. Starsze wiadomości mają neutralną etykietę
Asystent/Assistant, bez przypisywania aktualnego modelu. Ctrl+F, Ctrl+Enter i Escape
obsługują wyszukiwanie, wysyłanie i stop. Zachowano obsługę schowka i skalowanie.
Android: 44 JVM PASS, lintDebug i assembleDebugAndroidTest PASS; dodano odczyt
snapshotu modelu/statystyk, ich wyświetlanie oraz jawne sterowanie thinking.
Nowe pola mają bezpieczne wartości domyślne dla starszego API/historii.
Testy protokołu i UI nie zastępują testu fizycznego telefonu.

### Alpha.3 — wybór CUDA/CPU

131 backend + 18 desktop = 149 PASS. Dwa przypadki subprocess sprawdzają oddzielną
binarkę CUDA, prawidłowe --device/--gpu-layers, brak fałszywych urządzeń z logów,
zmianę na CPU, cleanup i fallback przy niedostępnej binarce CUDA. To test sterowania,
nie GPU. Rzeczywisty SmolLM2 GGUF/llama.cpp: 2 PASS (CPU i auto→CPU z raportowanym
fallbackiem), bez Ollamy. Dodano osobną konfigurację CUDA w backendzie/Qt i pola
execution_device/fallback_reason w metadanych klientów. CPU pozostaje niezależny.
Skrypt przypina llama.cpp, wariant CUDA buduje SM 89 i ma osobny workflow; wynik
kompilacji CI wymaga jeszcze sprawdzenia. Test sprzętowy wymaga offloadu i VRAM
z nvidia-smi; niewykonany — Cloud nie ma GPU. Brak deklaracji zgodności RTX 4060.

### Alpha.3 — powtarzalne paczki i zamykanie podczas inferencji

Rozszerzony rzeczywisty test Qt + HTTP/SSE + SmolLM2 GGUF CPU: 1 PASS, w tym
streaming/cancel/restart, trzecia generacja przerwana zamknięciem aplikacji,
brak procesów silnika i zapis częściowej historii cancelled w SQLite.
Android po dodaniu metadanych urządzenia: 44 JVM PASS i lintDebug PASS.

Wspólne distribution.json określa versionName, versionCode i nazwy AppImage/APK
Alpha.3. Smoke pakietu porównuje digest pełnej historii po restarcie oraz wersję.
Workflowy budowania obejmują gałąź Alpha.3, osobny upload do draft wymaga sukcesu
obu runów i identycznego SHA w manifestach. Gotowe paczki i ich uruchomienie
wymagają dalszego potwierdzenia; zmiana skryptu nie oznacza udanego builda.

### Alpha.3 — potwierdzony checkpoint paczek i klientów

Checkpoint gałęzi `f5f2b3779f19e5ded945a837f862ede91ccf2569`:
CI backend `40915267745` PASS; Linux `40915268031` PASS, w tym 149 testów i faktyczny
AppImage dwukrotnie; Android `40915267851` PASS (44 JVM, lint/build, po 2 testy UI
na API 30 i 36, 0 fail/error/skip według XML). Dwa nadmiarowe runy push anulowano
po uruchomieniu identycznej walidacji PR; nie były błędami produktu.

Lokalny rzeczywisty AppImage: GUI/backend/llama.cpp CPU, streaming GGUF, zamknięcie,
restart, język/motyw i identyczny digest pełnej historii PASS. W kontenerze Arch
20261025 (glibc 2.44, Weston 15.0.1, Xvfb 21.1.25, font DejaVu) wykonano osobno
rzeczywistą generację GGUF i restart na natywnym Wayland/pixman oraz X11/xcb;
oba raporty ok=true, digest historii/katalog zachowane. Nie jest to test fizycznego
CachyOS. Minimalny obraz Arch wymagał instalacji fontów; fontconfig wypisuje
ostrzeżenia o nowszej konfiguracji hosta, ale tekst po instalacji fontu jest czytelny.
Zrzut Linux pochodzi z tego Wayland/GGUF, Android z natywnego emulatora API 36
z kontrolowanym backendem HTTP/SSE. Fizycznego telefonu ani GPU nie ma.

Rzeczywisty Kotlin HTTP/SSE + FastAPI + SmolLM2 GGUF CPU: 1 PASS (load, streaming,
detach bez cancel, jawne cancel, reconnect/historia, unload). To nie test urządzenia.
Kod aplikacji Android nie został ponownie napisany. Pakiety nie zawierają wag.

Uwaga techniczna checkpointu: checkout PR domyślnie budował tymczasowy merge
`f288d7b8754dc0c2dab52c156bb8fe29b14e13df`, mimo run.head_sha wskazującego f5f2b37.
Checkout pakujących workflowów przypięto teraz jawnie do PR head.sha, aby nowa para
manifestów miała dokładnie SHA wymagane przez upload do draft. Nowe runy są konieczne
przed dołączeniem paczek. Wydanie Alpha.3 nie zostało publicznie opublikowane.

### 0.1.0 RC — automatyczne CUDA (przed bramką sprzętową)

Dokończona walidacja Alpha.3: CI 40916851255 Linux, 40916851419 Android/API30+36,
40916851208 backend PASS; kompilacja opcjonalnego CUDA SM89 40914492143 PASS.
Poprawka wykrywania: zamknięta lista skonfigurowanych, zarządzanych i typowych ścieżek
(w tym ~/llama.cpp/build/bin), bez skanowania modeli/dysku. Guard przywraca oryginalny
LD_LIBRARY_PATH przed exec z AppImage. CUDA wymaga dodatniego potwierdzonego offloadu
warstw z silnika; samo wykrycie urządzenia nie ustawia aktywnego CUDA. Auto ma CPU
fallback także przy błędzie GPU; wymuszone CUDA zwraca konkretny błąd. Dodano NVSMI
VRAM urządzenia i własnego procesu oraz szczegóły kandydatów w diagnostyce API.
30 testów modułu generacji/silników/wykrywania PASS; 5 testów nowego modułu ponownie
PASS po walidacji wymuszonego CUDA z zerem warstw. Są to kontrolowane testy procesu,
nie inferencja GPU. Rzeczywisty RTX4060 wymaga testu właściciela przed Stable.

### 0.1.0 RC — reasoning i SSE

44 testy reasoning/transportu/generacji PASS. Nowy parser przyrostowy obsługuje
podział <think>/</think> między tokenami, oddziela rozumowanie od odpowiedzi i ukrywa
niekompletne znaczniki przy zakończeniu. Ustrukturyzowane reasoning ma osobny tor.
Wieloliniowe data: SSE jest składane przed JSON, heartbeat/metadane są ignorowane,
[DONE]/finish_reason/usage pozostają zachowane. Request thinking=false wysyła
zarówno enable_thinking=false, jak i reasoning_effort=none do zgodnego llama.cpp;
żaden preserve flag nie jest traktowany jako wyłączenie rozumowania. Reasoning-only
z length nadal kończy się błędem, nie pustą zakończoną odpowiedzią. Regresje oznaczone
LFM3/Qwen są testami protokołu, nie testami rzeczywistych wag użytkownika.

### 0.1.0 RC — ustawienia klientów i zgodność danych

20 Qt + 1 upgrade Alpha.3 PASS. Podstawowy widok Linux ma Auto/CPU/CUDA; ścieżki,
warstwy i parametry silników są w rozwijanych opcjach zaawansowanych. Nowy profil
preferuje Auto/99, istniejący ręczny CPU pozostaje zachowany; CPU zapisuje zero
warstw. Diagnostyka rozróżnia dostępne GPU i aktualnie potwierdzony offload/VRAM.
Długie historie tworzą początkowo 60 dymków; starsze można rzeczywiście doładować.
Test aktualizacji zachowuje oryginalny JSON wiadomości bajt w bajt, ustawienia,
katalog i eksport/import. Nie zmieniono schematu SQLite.
Android: 44 JVM i lint PASS; opcje wykonania dotyczą komputera backendu, nie telefonu.
Dodano wyświetlanie potwierdzonej liczby warstw na GPU i czytelne błędy GPU.

### 0.1.0 RC — test sprzętowy bez hostowego Pythona

Dodano --hardware-test do dispatchera AppImage i krótki test_omnicore_cachyos.sh.
Test używa wyłącznie świeżej bazy tymczasowej i referencji do podanych GGUF;
nie dotyka katalogu/historii użytkownika, nie drukuje tokenu, nie nadpisuje raportu.
Sprawdza CPU/Auto/CUDA, niepustą odpowiedź, zapis nazwy modelu/historii, offload
oraz pamięć własnego procesu według nvidia-smi; raport zawiera osiągi i gate
hardware_ready. Cloud: rzeczywisty SmolLM2 CPU/Auto PASS, hardware_ready=false.
Dodatkowy rzeczywisty test izolacji danych/modelu/raportu: 1 PASS (dwie generacje).
Installer opcjonalnego silnika buduje przypięty commit z lokalnym CUDA Toolkit,
nie instaluje sterownika, nie zastępuje istniejącego silnika i zachowuje runtime
RPATH. bash -n i odmowa instalacji bez wymaganych narzędzi PASS; lokalnego CUDA13
nie ma, więc jego budowanie wymaga potwierdzenia na sprzęcie. Silnik SM89/CUDA12
z poprzedniego workflow został faktycznie zbudowany (40914492143 PASS).

### 0.1.0-rc.1 — finalna walidacja źródeł przed paczkami

156 backend + 20 Qt = 176 PASS; 44 JVM, lintDebug, assembleDebug oraz
assembleDebugAndroidTest PASS dla RC/applicationId .rc. Rzeczywiste testy GGUF CPU:
4 PASS (backend CPU/Auto, Qt z cancel/close/restart oraz izolowany hardware tool).
Zmiana backendowej wersji na PEP440 0.1.0rc1 nie zmienia tras/schematu API v1.
Wersja dystrybucji 0.1.0-rc.1, Android versionCode4; bramka Stable jest jawna.
RC ma oddzielny ID, aby testowy podpis nie wymagał usunięcia istniejącej Alpha.
Dokumentacja rozróżnia tę instalację od prawdziwej aktualizacji podpisanego APK.
Opcjonalny prebuilt CUDA SM89 ma sprawdzoną sumę
`ef431c73583986be861f47068f119172b0434393d7ff8b2ff2764c8e972058e5` i pochodzi
z udanego workflow 40914492143. To dowód kompilacji, nie działania RTX4060.
Końcowe artefakty/CI/merge/upload RC wymagają jeszcze potwierdzenia.

### RC — znaleziony i odtworzony błąd zagnieżdżonych bibliotek

Faktyczny zamrożony guard zwrócił przed poprawką LD_LIBRARY_PATH zawierające
AppImage/_internal mimo przywrócenia LD_LIBRARY_PATH_ORIG. Zagnieżdżone bootloadery
przenosiły wewnętrzne biblioteki także do ORIG. Native boundary filtruje teraz
rzeczywisty sys._MEIPASS i podkatalogi również z ORIG, zachowując ścieżki CUDA hosta.
Dodano regresję jednostkową i obowiązkowy test faktycznego wyekstrahowanego AppImage:
natywna powłoka sprawdza brak _internal bez drukowania środowiska/sekretów.
Nowe paczki muszą przejść tę kontrolę przed wydaniem RC.

### RC.1 — potwierdzona dostawa GitHub i checkpoint do kontynuacji

Źródło paczek: **09cd1d8f8f62b96512587a764b6f83ed452d0ef6**.
PR #5 scalony (bez force push) do main jako
**92a2ca02ccd06acfd81f63935d978703c73cf618**; oba drzewa źródeł są identyczne.
CI PR: backend 40930829737 PASS (157 testów), Linux 40930829718 PASS
(157 backend + 20 Qt = 177), Android 40930829695 PASS (44 JVM/lint/build,
2 UI na API30 i 2 UI na API36, 0 fail/error według XML). CI main na checkpoint92:
40932360138 backend, 40932360205 Linux i 40932360129 Android — wszystkie PASS.
Wcześniejsze runy anulowane przy aktualizacji PR nie były błędami produktu.

Rzeczywista inferencja: 4 testy pytest CPU (backend CPU/Auto, Qt cancel/close/restart,
izolacja hardware tool), 1 dodatkowy test Auto z rzeczywistą binarką CUDA przy braku
runtime oraz 1 rzeczywisty klient Kotlin + FastAPI/GGUF PASS. To nie inferencja GPU.
Faktyczny CI AppImage testowano dodatkowo z prawdziwym GGUF CPU, restartem i digestem
historii oraz kontrolą zagnieżdżonych bibliotek. Kanoniczny plik CI przeszedł również
Wayland/Weston i X11/Xvfb z GGUF/restartem w kontenerze Arch. Nie testowano fizycznego
CachyOS/RTX4060 ani telefonu. Zrzuty pochodzą z tego AppImage i emulatora API36
(kontrolowany backend w teście interfejsu Android).

Publiczne **prerelease RC.1** (nie Stable):
https://github.com/vex2137/OmniCore/releases/tag/v0.1.0-rc.1
ID 428235659, draft=false, prerelease=true, make_latest=false. Tag wskazuje merge92.
Upload 40932563350 PASS: 11 załączników mają state=uploaded, niezerowe rozmiary i
zweryfikowane server digest. Pobrano obie paczki ponownie z publicznych URL i
obliczono zgodne SHA-256:

| Plik | Bajty | SHA-256 |
| --- | ---: | --- |
| OmniCore-0.1.0-rc.1-x86_64.AppImage | 98707960 | 15bd847bda98abad9b6666f5897fe96012c0364ea964f475a5a219e203766a2d |
| OmniCore-0.1.0-rc.1-android-arm64.apk | 18207561 | 7760e6d46ba4418331ef85b54f99f0c0432d24da08508edffa59822b8bfb69d2 |
| OmniCore-llama-cuda-sm89.tar.gz | 250652194 | ef431c73583986be861f47068f119172b0434393d7ff8b2ff2764c8e972058e5 |

Załączniki zawierają sumy, manifesty, test_omnicore_cachyos.sh, install_cuda_engine.sh
i tools.sha256; bez wag. SM89 z CUDA12.6 ma potwierdzoną kompilację, nie inferencję.
RC APK ma ID io.github.vex2137.omnicore.rc i podpis testowy; instaluje się obok Alpha.
Nie deklarować aktualizacji APK podpisanego niedostępnym kluczem poprzedniego CI.

Commity RC: 5f2f559 (wykrywanie/VRAM/offload), 1887845 (reasoning/SSE), 42d26fe
(klienci/upgrade), 2e48568 (test sprzętowy/installer), d343707 (paczki/bramka),
09cd1d8 (odtworzony i naprawiony błąd zagnieżdżonego LD_LIBRARY_PATH_ORIG).
Starsze commity Alpha.3 zachowano w historii PR. Alpha.1/2 i szkic Alpha.3 pozostają.

**Następny krok bez ponownego audytu:** właściciel uruchamia załączony test na obu
GGUF, przekazuje nowy omnicore-hardware-*.json oraz wynik GUI Wayland i APK ARM64.
Nie zastępować raportu wynikiem samego zewnętrznego llama-server. Nie publikować
v0.1.0 Stable przed potwierdzeniem sprzętu i docelowego podpisywania. Szczegóły
w RELEASE_GATE.md. Trwałe dane użytkownika nie były resetowane ani usuwane.

### Stable hardening — P0, bounded native stderr

Branch starts at main f429a40. PR #6 (0f0dd16, source 745166d) and #7
(f429a40) are merged; `-lv 4` is retained and regression-checked. PR #6 records
owner tests of LFM3/Qwen3.5 CPU/Auto/CUDA on RTX4060 with hardware_ready=True.
This is owner-reported hardware evidence for that build, not a Cloud GPU test.

Verbose stderr previously accumulated without a size limit in a temporary file.
The engine now continuously drains its pipe into a private 128 KiB memory tail,
retains offload evidence independently and joins the reader during shutdown.
No raw prompt/log output is exported. A controlled engine emits ~2 MB before
health becomes ready: bounded output, preserved offload and process/reader cleanup PASS.
Targeted native/adapter/parent-death suite: 23 PASS. Real SmolLM2 GGUF CPU and Auto:
2 PASS (the first invocation lacked the test-specific executable variable; corrected
configuration passed). No GPU hardware is present in Cloud; no CUDA claim from mocks.

### Stable hardening — P0, Android shared streams and cold loading

Opening or refreshing a shared conversation now attaches to its recovered active
SSE task exactly once, without resubmitting the prompt or cancelling the backend.
Previously these paths only retrieved a snapshot and could leave a static answer.
Model loading has a separate bounded 180s HTTP timeout instead of the ordinary
45s read timeout. Ordinary REST exchanges also have a 60s total deadline; SSE
retains heartbeat/read semantics. Loading shares the dispatcher/pool and cancellation.
Targeted Android JVM: ClientTest 18 + ViewModelTest 19 = 37 PASS, 0 skipped/errors.
Tests include another client's task, repeated refresh without duplicate stream,
and a delayed HTTP load that exceeds the ordinary read timeout. No phone test.

### Stable hardening — P4, launcher icon

Android now uses an adaptive launcher icon (API26+) with the original purple
OmniCore diamond kept inside the 66dp safe zone. Its central cutout is circular,
matching Linux/AppImage's existing SVG; no new logo or branding was invented.
Legacy vector geometry remains available. Full local JVM suite: 47 PASS, lintDebug,
assembleDebug and assembleDebugAndroidTest PASS. Resource compilation validates
both launcher layers; launcher appearance on POCO/HyperOS still needs a phone.

### Stable hardening — P0, Linux SSE transport

Qt joins bytes before normalizing CRLF and assembles multiline data fields per
SSE event. It rejects non-object snapshots instead of passing them into a dict
signal, and maps HTTP401/403 on streaming connections to unauthorized without
exposing server bodies. Four actual Qt HTTP transport tests PASS (LF/CRLF,
multiline snapshots, malformed object and authentication). The earlier complete
backend/Qt run passed 178 tests before these three new parametrized cases.

### Stable hardening — P1/P2 and RC.2 build checkpoint

No actionable specification for the requested bar/algorithm was found in relevant
docs, matching commit history or repository issues (none). These items are explicitly
deferred in ROADMAP, without inventing behavior. Existing measured Python/Rust
admission plan remains applicable; no new workload/profile proves an FFI/worker
benefit. No Rust crate, JNI requirement or inference rewrite was added.

RC.2 metadata: Python 0.1.0rc2, distribution 0.1.0-rc.2, Android versionCode5,
existing .rc applicationId. Contract snapshot regenerated; 3 contract tests PASS.
Full local tests before final transport cases: 158 backend + 20 Qt PASS, followed
by 4 targeted Qt transport PASS (three new parametrized cases). Android full JVM
47 PASS, lint/build PASS; ruff check/format and git diff --check PASS.
CI, final packaged tests and artifact delivery are the next checkpoint.
Production signing remains unresolved: the current integration cannot list Actions
secrets (403); no secret values were read, no random production key was created.
No device or GPU test was performed in Cloud. PR #6 owner results are recorded
separately in RELEASE_GATE; Stable still requires explicit approval and phone/signing gates.

### RC.2 — CI correction and preservation of installed RC.1

First RC.2 CI found one stale health-test assertion expecting literal 0.1.0rc1
(157 backend and 180 backend/Qt cases otherwise passed). It now compares runtime
version to installed distribution metadata; targeted health/contracts: 4 PASS.
A second packaging issue was prevented: a new ephemeral CI debug signature cannot
update installed RC.1 under the same ID. RC.2 now uses `.rc2`, label OmniCore RC2,
so neither Alpha nor RC.1 must be uninstalled. Both retain private settings; the
new client needs its own connection configuration and shares backend history.
The earlier same-ID RC.2 checkpoint is superseded; no such APK was published.

Final-source real integrations: Qt stream/cancel/close/restart plus isolated hardware
acceptance CPU/Auto: 2 PASS; actual Kotlin HTTP/SSE + FastAPI + GGUF CPU: PASS.
These use SmolLM2, not mocks or user LFM/Qwen weights. No physical phone/GPU claim.

### RC.2 — finalny checkpoint P5 do kontynuacji bez audytu

**Kod i kanoniczne paczki: 064005b980dbc1629d74291d475e4023f63e3de0**.
Późniejszy commit tego raportu zmienia wyłącznie dokumentację; nie należy
przypisywać istniejącym paczkom nowego SHA ani nadpisywać ich innymi bajtami.
PR #8 https://github.com/vex2137/OmniCore/pull/8 pozostaje do przeglądu, bez merge.
Main w ostatniej weryfikacji: f429a40bf45c84879f13204e5a4d7bb397db9509, zawiera #6/#7.

CI źródeł: backend 40960267667 PASS (158), Linux 40960267646 PASS (181=158+23 Qt,
kompilacja CPU/AppImage, dwa uruchomienia i trwałość), Android 40960267733 PASS
(47 JVM/lint/build, po 2 natywne UI na API30/36; XML 0 skip/fail/error).
Real GGUF CPU: backend CPU/Auto, Qt cancel/close/restart, izolowany acceptance,
klient Kotlin z FastAPI PASS. Kanoniczny pobrany AppImage: real GGUF, restart,
digest historii i guard bibliotek PASS. Zamrożony --hardware-test CPU/Auto PASS,
hardware_ready=False (Cloud nie ma GPU). Arch/Weston Wayland i X11/Xvfb: faktyczna
paczka, GGUF, restart i ustawienia PASS. Kopia bazy RC.1 zachowała wszystkie dwie
stare wiadomości i dodała dwie nowe, bez modyfikowania oryginalnej testowej bazy.
Fontconfig w Arch ostrzega o nowych regułach hosta; testy GUI zakończone sukcesem.
To nie test natywnego CachyOS lub fizycznego urządzenia.

Upload 40961298009 PASS. Szkic ID428427155 (draft=true, prerelease=true):
https://github.com/vex2137/OmniCore/releases
11 załączników istnieje na GitHubie, state=uploaded, niezerowe rozmiary i zgodne
server digests. Obie paczki ponownie pobrano ze szkicu i zweryfikowano SHA-256:

- AppImage 98707960 B: caac9059da913eb5aaba96aa4e6765af7169971c75f569f52a1634185e078a3b
- APK 18209073 B: 3506d5f5627f12a16f7825b2f4638095bc765d734cc9530a252055157a3a8bbc

Artefakty Actions: Linux12936111082, Android12936046127. Szkic zachowuje też sumy,
manifesty, oba skrypty i istniejący opcjonalny silnik CUDA12/SM89. Nie dodano wag.
Faktycznie wyekstrahowane SVG i desktop entry AppImage są zgodne z repozytorium.

Commity implementacji: 0a32f3d (log/lifecycle), 3b9230f (Android stream/timeout),
0b5f4e1 (adaptive icon), e1cae00 (Qt SSE), 917230e (RC.2), 7ca2368/064005b
(ochrona instalacji RC.1 i test wersji). Brak Rust — pozostaje zmierzony plan.
Pasek/algorytm: brak specyfikacji, odroczone jawnie w ROADMAP.

Następnie: właściciel testuje te paczki i skrypt na swoim CachyOS/RTX4060 oraz APK
na fizycznym ARM64. Wynik PR #6 jest zachowany, ale nie zastępuje potwierdzenia
nowych bajtów. Wymagane docelowe podpisywanie/ścieżka aktualizacji i osobna zgoda
na finalne wydanie; patrz RELEASE_GATE. Nie ma finalnego tagu ani Stable v0.1.0.
Nie restartować projektu, nie usuwać checkoutu ani danych Alpha/RC.
