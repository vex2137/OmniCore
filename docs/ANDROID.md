# OmniCore Android — natywny klient API

Kotlin + Jetpack Compose + Material 3, bez WebView. Aplikacja korzysta z istniejącego
FastAPI REST/SSE. SQLite, inferencja, kolejka i modele pozostają na komputerze.
**Nie ma lokalnej inferencji GGUF na telefonie ani wymaganego komponentu Rust.**

Identyfikator RC.3: `io.github.vex2137.omnicore.rc3`. Wersja: `0.1.0-rc.3`, versionCode 6.
Minimalny Android 8.0/API 26, target/compile SDK 36. Dystrybucyjny plik:
`OmniCore-0.1.0-rc.3-android-arm64.apk`, ABI arm64-v8a. Jest to build **debug/test**,
podpisany kluczem testowym, nie oficjalnym kluczem produkcyjnym. W APK nie ma
adresu prywatnego serwera, tokenów użytkownika ani wag modeli.

RC.3 instaluje się **obok** RC.2, RC.1 i Alpha jako „OmniCore RC3”. Klucze testowe
runnery CI generują niezależnie, dlatego nie próbujemy zastąpić instalacji RC.1
APK z niezgodnym podpisem. Nie odinstalowuj starej aplikacji i nie czyść jej danych.
W RC3 skonfiguruj ponownie adres/token; historia pozostaje na tym samym backendzie.
To bezpieczna instalacja równoległa, a nie potwierdzona aktualizacja APK.

Wersjonowanie APK, AppImage i aplikacji pochodzi z
`backend/src/omnicore/distribution.json`. Publiczna Alpha.2 zachowuje poprzednie
pliki i versionCode 2; nowe artefakty Alpha.3 są odrębne.

## Funkcje

- Ekran główny, ostatnie rozmowy i tworzenie nowej rozmowy.
- Czat, historia, zmiana nazwy/usunięcie po potwierdzeniu, wybór modelu,
  streaming pełnych snapshotów SSE, anulowanie i kopiowanie odpowiedzi.
- Katalog modeli, metadane/licencja/status kompatybilności, dostępność silników;
  load GGUF w backendzie, unload, usunięcie wpisu oraz import ścieżki GGUF
  **na komputerze backendu**, w już dozwolonym katalogu. Bez wysyłania wag z telefonu.
- Hugging Face przez backend: wyszukiwanie lub owner/repo, lista GGUF, potwierdzenie
  rozmiaru/licencji, pobranie, postęp, wstrzymanie/wznowienie i import gotowego pliku.
  SHA-256 sprawdza backend, jeśli źródło podało sumę. Tło telefonu nie przerywa transferu.
- Parametry rozmowy (temperatura, top-p, kontekst, limit tokenów, system prompt),
  trwały zapis na backendzie i zachowanie pól GPU/top-k/seed/repeat penalty.
- Pierwszy start: wykrycie języka systemowego PL/EN i zapis wyboru; ręczny wybór
  ma pierwszeństwo po restarcie. Onboarding wskazuje adres komputera, nie localhost telefonu.
- Statusy connected/connecting/disconnected/auth, reconnect po utracie sieci,
  ręczne odświeżenie i ponowienie wiadomości bez automatycznego dublowania promptu.
- Nazwa modelu/statystyki zapisane przy wiadomości, oddzielnie zwijane rozumowanie;
  brak finalnej odpowiedzi ma czytelny komunikat, limit kontekstu nie rośnie sam.
- Ustawienia połączenia, token, light/dark/system, PL/EN i diagnostyka połączenia,
  wersji silników, GPU zgłoszonego przez silnik i jego pamięci RAM/VRAM.
- Natywna nawigacja dolna na telefonie, rail na dużym ekranie, przewijane widoki
  i dotykowe kontrolki Material 3. Brak atrap Image AI lub inferencji telefonu.

Modele w katalogu nie są automatycznie uznawane za kompatybilne. Ollama pozostaje
opcjonalna i ładuje model na pierwsze żądanie; Load w katalogu dotyczy llama.cpp.
Usuwanie wpisu pozostawia plik modelu w backendzie. Ustawienia języka/motywu/URL
są trwałe na telefonie, historia jest trwała w backendzie.

## Telefon i komputer w zaufanej sieci lokalnej

1. Sprawdź działanie backendu, silnika i modelu na komputerze. Wybierz adres LAN
   komputera, np. `192.168.1.10`; to przykład, nie adres środowiska Codex Cloud.
2. Świadomie włącz serwer dla innych urządzeń i podaj token co najmniej 32 znaków
   ASCII (litery/cyfry). Przykład powłoki Bash bez wpisywania tokenu do historii:

```sh
export OMNICORE_HOST=0.0.0.0
export OMNICORE_ALLOW_REMOTE=1
export OMNICORE_ALLOWED_HOSTS=192.168.1.10,127.0.0.1,localhost
read -r -s -p 'API token: ' OMNICORE_API_TOKEN
export OMNICORE_API_TOKEN
uv run --frozen omnicore
```

   Zachowaj istniejące OMNICORE_LLAMA_SERVER i OMNICORE_MODEL_ROOTS. Otwórz port
   8000 tylko dla właściwego LAN w zaporze komputera. Nie ustawiaj CORS `*` ani
   nie wyłączaj autoryzacji. Natywny klient nie potrzebuje dodatkowego origin CORS.
3. Na telefonie: **Ustawienia → adres backendu**: `http://192.168.1.10:8000`,
   wpisz token, zaznacz świadomą zgodę na HTTP w zaufanym LAN i wybierz **Zapisz i połącz**.
4. Wybierz model i nową rozmowę. Model musi być już dostępny w backendzie;
   aplikacja nie zakłada, że plik z telefonu jest plikiem komputera.

`localhost`/`127.0.0.1` Androida oznacza telefon, a nie komputer. W emulatorze
Android standardowym adresem hosta jest `10.0.2.2`; wtedy dodaj również ten host
do OMNICORE_ALLOWED_HOSTS. Przykład emulatora nie jest instrukcją dla fizycznego telefonu.

Automatycznie uruchamiany przez GUI Linux backend jest prywatny i nasłuchuje
loopback. Do telefonu użyj świadomie skonfigurowanego serwera headless. Desktop
może dołączyć do tego serwera przez OMNICORE_DESKTOP_URL i OMNICORE_DESKTOP_TOKEN;
nie przejmuje procesu ani nie zmienia jego zabezpieczeń.

## Połączenia zdalne i sekrety

Poza zaufanym LAN wymagane **HTTPS** z prawidłowym certyfikatem i reverse proxy
przed backendem, odpowiednią listą Host oraz auth. Dla SSE również jest to HTTPS;
klient nie wymaga WSS, ponieważ nie używa WS. Nie wyłączaj weryfikacji TLS.
HTTP jest blokowane dla publicznych hostów i wymaga jawnej zgody nawet dla
prywatnego IPv4. Token i rozmowy przez HTTP nie są szyfrowane w transmisji.

Token jest szyfrowany AES-GCM, a nieeksportowalny klucz pozostaje w Android Keystore.
SharedPreferences zawiera tylko ciphertext/IV oraz niesekretny URL/język/motyw.
Backup aplikacji jest wyłączony. Token nie jest w logach, query URL ani zapisanym
stanie pola edycji. Przy zmianie origin wymagany jest nowy token lub jawne usunięcie
poprzedniego; nie przekazujemy starego tokenu automatycznie innemu hostowi.
Przekierowania HTTP są wyłączone, aby nie przekazywać nagłówków auth innemu serwerowi.
Nie ma loggera requestów ani treści rozmów.

Timeouty i błędy auth/sieci/modelu są widoczne w interfejsie. Reconnect odczytuje
historię i stan zadania zamiast ponownie wysyłać prompt. Ponowienie niezakończonego
POST używa tego samego request_key. Przejście aplikacji w tło **nie anuluje generacji**. SSE używa istniejącego
`cancel_on_disconnect=false`; po `onStop` telefon odłącza strumień i polling,
a backend kontynuuje zadanie z własnym limitem czasu. Powrót pobiera historię
oraz trwały snapshot i ponownie podpina SSE. Tylko przycisk Stop wysyła cancel.
Zmiana konfiguracji ekranu/języka zachowuje ViewModel. ID rozmowy i aktywnego
zadania są zapisane lokalnie, więc po odtworzeniu procesu nie wysyłamy promptu
ponownie. Automatyczny reconnect używa opóźnień do 8 sekund, odczytu stanu i
powiadomień sieci Androida; błąd auth wymaga poprawienia tokenu. Częściowa odpowiedź pozostaje
w historii backendu. Aplikacja nie zatrzymuje obcych procesów serwera.

## Budowanie i instalacja

Wymagany pełny JDK 17+ (nie sam JRE), Android SDK platform 36 i build-tools 36.0.0.
Wrapper Gradle 8.13 i jego dystrybucja są zweryfikowane oficjalnymi checksumami;
AGP 8.13.2 / Kotlin 2.1.20 / Compose BOM 2025.04.01. SDK/JDK, cache i klucze podpisu
pozostają poza Git. Ustaw ANDROID_HOME i, gdy potrzebne, JAVA_HOME.

```sh
cd apps/android
./gradlew --no-daemon testDebugUnitTest lintDebug assembleDebug assembleDebugAndroidTest
cd ../..
python3 scripts/package_android.py
sha256sum -c dist/OmniCore-0.1.0-rc.3-android-arm64.apk.sha256
adb install dist/OmniCore-0.1.0-rc.3-android-arm64.apk
```

Budowanie tworzy oddzielne APK arm64-v8a i x86_64 do emulatora. Skrypt pakowania
sprawdza podpis apksigner, application ID, wersję, minSdk i ABI przez aapt;
sprawdza także targetSdk 36, ZIP alignment i ELF LOAD alignment >=16 KiB;
następnie zapisuje rzeczywiste APK, SHA-256 i manifest budowania w dist.
Nie oznacza to samo w sobie testu instalacji lub działania na urządzeniu ARM64.
Kolejne debug buildy z innym kluczem testowym mogą wymagać odinstalowania starej
aplikacji przed instalacją; historia pozostaje na serwerze, token trzeba wprowadzić ponownie.

## Testy i CI

- Testy JVM: polityka URL/LAN/HTTPS, auth i brak redirectu z tokenem, kontrakty
  serializacji, sekwencje różnych zadań, rzeczywisty lokalny HTTP/SSE z kontrolowanym
  serwerem, limit odpowiedzi, zgodność zasobów PL/EN.
- Test instrumentacyjny: natywne ekrany Compose, połączenie HTTP/SSE, Keystore
  (ciphertext nie zawiera tokenu), czat, cancel, zmiana nazwy/usunięcie, modele,
  diagnostyka, język/motyw i zrzut prawdziwego ekranu. Backend jest kontrolowanym
  fixture protokołu; to nie jest test inferencji modelu.
- Workflow **Native Android APK** buduje paczki, uruchamia unit/lint i emulator
  Android API 30 i 36 x86_64 z KVM, po czym wysyła APK ARM64, SHA-256, manifest, screenshot
  i raporty testów. Gdy emulator nie przejdzie, workflow nie oznacza testu jako PASS.
- Lokalna chmura nie ma KVM/telefonu. Instalacji na fizycznym ARM64 nie należy
  deklarować bez osobnego testu. Rzeczywisty GGUF jest sprawdzany na Linuxie,
  Android jest wyłącznie klientem API.

Aktualne, wykonane wyniki oraz linki do paczek: [PROGRESS.md](PROGRESS.md).

## Android 16, POCO i Xiaomi

Build używa compile/target 36 (Android 16), obsługuje edge-to-edge, IME i systemowy
Wstecz, bez blokady orientacji i bez usług Google Play. Minimalny system to API 26.
Jedynymi uprawnieniami są INTERNET i ACCESS_NETWORK_STATE. Natywna biblioteka
AndroidX (nie silnik AI) musi przejść sprawdzenie stron 16 KiB w pakowaniu.
Macierz emulatorów CI obejmuje API 30 i 36. Nie jest to test fizycznego telefonu
ani firmware HyperOS: instalację ARM64, klawiaturę i zachowanie po ubiciu procesu
przez oszczędzanie baterii trzeba dodatkowo sprawdzić na POCO/Xiaomi. Backend
kontynuuje generację niezależnie od życia procesu telefonu.

## Podział kodu

Compose (`OmniCoreApp`, `ModelDownloads`, `GenerationSettings`) obserwuje StateFlow
z `OmniViewModel`. Zastępowalny `OmniRepository` definiuje granicę danych i Flow
snapshotów; `OmniApi` realizuje REST oraz SSE OkHttp. `ClientSettings` oddziela
lokalne preferencje od Keystore (`SecureSettings`). Nie ma logiki inferencji,
SQLite ani uruchamiania silnika w telefonie. Przyszły lokalny silnik wymaga osobnej
implementacji tej granicy i osobnych testów, a nie przełącznika udającego działanie.

## Dystrybucja

Opublikowane wcześniej `v0.1.0-alpha.1` pozostaje bez zmian. Nowy APK wersji
`0.1.0-alpha.2` jest publicznie dostępny w [wydaniu Alpha.2](https://github.com/vex2137/OmniCore/releases/tag/v0.1.0-alpha.2)
po weryfikacji plików i wyraźnym poleceniu właściciela. CI source `e9fd854`
przeszło emulatory API 30/36; podpis jest testowy, telefon fizyczny nie był testowany. Workflow `Attach tested Android APK to draft` wymaga udanego runu,
pełnego zgodnego SHA i draft=true; odrzuca publiczne wydanie. Nie wolno podmieniać
starego publicznego pliku o tej samej nazwie. Podpis debug w różnych CI może być
inny: przed deinstalacją starej aplikacji zapisz adres backendu, a token wprowadź
ponownie. Historia pozostaje na backendzie. Docelowy stały klucz podpisu wymaga
odrębnej konfiguracji sekretów właściciela.

## Rzeczywista inferencja a test UI

Normalne testy JVM i instrumentacja używają kontrolowanych odpowiedzi protokołu.
Oddzielny scenariusz uruchamia **rzeczywisty kod klienta Kotlin** przeciwko
izolowanemu FastAPI i istniejącemu llama.cpp/GGUF na CPU:

```sh
# JDK/SDK/cache tak jak dla builda APK; istniejące wagi, bez automatycznego downloadu:
export OMNICORE_TEST_LLAMA_SERVER=/absolute/llama-server
export OMNICORE_TEST_GGUF=/absolute/model.gguf
uv run --frozen python scripts/test_android_real.py
```

Scenariusz wymaga faktycznych plików i nie ma fallbacku do fixture. Sprawdza import,
load, rozmowę, kilka snapshotów SSE i niepustą odpowiedź, odłączenie streamu bez
cancel, jawne cancel drugiej generacji, historię przez nowy klient oraz unload.
To dowód integracji kodu transportu z AI, **nie instalacji/UI na telefonie**.
`RealBackendTest` jest jawnie wyłączony ze zwykłych testów; uruchamia go wyłącznie
`-PrealBackend=true` z poprawnymi zmiennymi procesu. Brak wag kończy scenariusz błędem.

## Kandydat Stable

RC instaluje się obok Alpha jako „OmniCore RC”; nie usuwaj Alpha, aby wykonać test.
Podpisy testowe poprzednich CI nie są trwałymi kluczami produkcyjnymi. Nie deklarujemy
aktualizacji APK podpisanego innym kluczem. RC wymaga własnego adresu/tokena; po
połączeniu widzi istniejącą historię serwera. Wybór Auto/CPU/CUDA dotyczy komputera.
Wynik fizycznego Androida oraz trwałe podpisywanie są bramkami Stable:
[RELEASE_GATE.md](RELEASE_GATE.md).

Przy współdzieleniu istniejącej historii uruchamiaj jeden backend: zamknij GUI z
prywatnym serwerem przed startem serwera LAN na tej samej bazie. Ustaw świadomie
OMNICORE_MODEL_ROOTS (np. katalog Pulpit z modelami), allowed hosts i token zgodnie
z powyższą instrukcją. Desktop można potem podłączyć do tego serwera przez
OMNICORE_DESKTOP_URL i OMNICORE_DESKTOP_TOKEN (token w środowisku, nie w argumentach
ani logach). Nie uruchamiaj dwóch niezależnych backendów do tej samej bazy.


## Test adresu i szybkie ponowne połączenie

W Ustawieniach wpisz adres komputera oraz token. **Test połączenia** sprawdza
health i uwierzytelnione API modeli, ale nie zapisuje adresu/tokenów i nie przerywa
aktywnego czatu. **Zapisz i połącz** zapisuje konfigurację; token trafia do Keystore.
**Połącz ponownie** używa już zapisanej konfiguracji. Zmiana pól usuwa stary wynik testu.
Localhost/127.0.0.1 telefonu nie wskazuje komputera; użyj jego adresu LAN lub HTTPS.
Nie ma automatycznego skanowania sieci/mDNS: wykrycie hosta nie uwierzytelnia serwera.

GUI Linux uruchamia domyślnie serwer wyłącznie na loopback. Sam test połączenia
w telefonie nie włącza zdalnego dostępu. Zaawansowaną konfigurację zdalnego
serwera AppImage bez Pythona opisuje [instrukcja Linux](LINUX_DESKTOP.md#backend-lokalny-i-serwer-dla-telefonu).
Nie uruchamiaj drugiego backendu na tej samej bazie — połącz klientów z jednym.

Podpis Stable, kopie klucza i sprawdzenie zgodności aktualizacji:
[ANDROID_SIGNING.md](ANDROID_SIGNING.md). Skonfigurowanie workflow nie oznacza
wygenerowania ani sprawdzenia produkcyjnego podpisu.
