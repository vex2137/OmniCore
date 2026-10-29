# OmniCore Android — natywny klient API

Kotlin + Jetpack Compose + Material 3, bez WebView. Aplikacja korzysta z istniejącego
FastAPI REST/SSE. SQLite, inferencja, kolejka i modele pozostają na komputerze.
**Nie ma lokalnej inferencji GGUF na telefonie ani wymaganego komponentu Rust.**

Identyfikator: `io.github.vex2137.omnicore`. Wersja: `0.1.0-alpha.1`, versionCode 1.
Minimalny Android 8.0/API 26, target/compile SDK 35. Dystrybucyjny plik:
`OmniCore-0.1.0-alpha-android-arm64.apk`, ABI arm64-v8a. Jest to build **debug/test**,
podpisany kluczem testowym, nie oficjalnym kluczem produkcyjnym. W APK nie ma
adresu prywatnego serwera, tokenów użytkownika ani wag modeli.

## Funkcje

- Ekran główny, ostatnie rozmowy i tworzenie nowej rozmowy.
- Czat, historia, zmiana nazwy/usunięcie po potwierdzeniu, wybór modelu,
  streaming pełnych snapshotów SSE, anulowanie i kopiowanie odpowiedzi.
- Katalog modeli, metadane/licencja/status kompatybilności, dostępność silników;
  load GGUF w backendzie, unload, usunięcie wpisu oraz import ścieżki GGUF
  **na komputerze backendu**, w już dozwolonym katalogu. Bez wysyłania wag z telefonu.
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
POST używa tego samego request_key. Przejście aplikacji w tło anuluje własną generację;
zmiana konfiguracji ekranu/języka zachowuje ViewModel. Częściowa odpowiedź pozostaje
w historii backendu. Aplikacja nie zatrzymuje obcych procesów serwera.

## Budowanie i instalacja

Wymagany pełny JDK 17+ (nie sam JRE), Android SDK platform 35 i build-tools 35.0.0.
Wrapper Gradle 8.11.1 i jego dystrybucja są zweryfikowane oficjalnymi checksumami;
AGP 8.9.2 / Kotlin 2.1.20 / Compose BOM 2025.04.01. SDK/JDK, cache i klucze podpisu
pozostają poza Git. Ustaw ANDROID_HOME i, gdy potrzebne, JAVA_HOME.

```sh
cd apps/android
./gradlew --no-daemon testDebugUnitTest lintDebug assembleDebug assembleDebugAndroidTest
cd ../..
python3 scripts/package_android.py
sha256sum -c dist/OmniCore-0.1.0-alpha-android-arm64.apk.sha256
adb install dist/OmniCore-0.1.0-alpha-android-arm64.apk
```

Budowanie tworzy oddzielne APK arm64-v8a i x86_64 do emulatora. Skrypt pakowania
sprawdza podpis apksigner, application ID, wersję, minSdk i ABI przez aapt;
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
  Android API 30 x86_64 z KVM, po czym wysyła APK ARM64, SHA-256, manifest, screenshot
  i raporty testów. Gdy emulator nie przejdzie, workflow nie oznacza testu jako PASS.
- Lokalna chmura nie ma KVM/telefonu. Instalacji na fizycznym ARM64 nie należy
  deklarować bez osobnego testu. Rzeczywisty GGUF jest sprawdzany na Linuxie,
  Android jest wyłącznie klientem API.

Aktualne, wykonane wyniki oraz linki do paczek: [PROGRESS.md](PROGRESS.md).
