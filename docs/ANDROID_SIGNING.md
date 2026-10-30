# Android — trwały podpis właściciela i aktualizacje

Konfiguracja jest przygotowana; **klucz wydawniczy nie został utworzony w Cloud**.
Nie ma tu skonfigurowanego bezpiecznego depozytu/odzyskiwania tego klucza. Debug APK
z CI jest testowy i nie staje się Stable po zmianie nazwy pliku. Weryfikacja podpisu
nie zastępuje testu instalacji, zachowania danych, telefonu ani zgody na wydanie.

## Jednorazowo na zaufanym komputerze właściciela

Najpierw ustal trwały application ID. Alpha, RC.1 i RC.2 mają różne testowe tożsamości;
prywatne klucze poprzednich runnerów CI nie są dostępne. Nowym kluczem nie można
zaktualizować APK podpisanego innym kluczem. Jeżeli stary podpis jest niedostępny,
zalecana jest instalacja Stable obok, pod trwałym ID np.
`io.github.vex2137.omnicore.stable`. Zachowaj stare aplikacje i ich dane; skonfiguruj
połączenie nowego klienta. Historia pozostaje na backendzie. Wybrany ID i klucz
muszą pozostać te same w kolejnych aktualizacjach Stable. Nie zmieniaj ich co build.

Utwórz klucz lokalnie, poza repozytorium. Polecenie pyta o hasło; nie podawaj go
w argumentach procesu, historii powłoki lub czacie. Poniższe polecenia są instrukcją
właściciela, nie zostały wykonane jako generowanie produkcyjnego klucza w Cloud:

```bash
umask 077
mkdir -p "$HOME/.local/share/omnicore-signing"
keytool -genkeypair -storetype PKCS12 \
  -keystore "$HOME/.local/share/omnicore-signing/omnicore-release.p12" \
  -alias omnicore-release -keyalg RSA -keysize 3072 -validity 10000
keytool -list -v -keystore "$HOME/.local/share/omnicore-signing/omnicore-release.p12" \
  -alias omnicore-release
```

Nie uruchamiaj generowania nad istniejącym kluczem. Zapisz publiczny fingerprint
SHA-256 certyfikatu. Hasła, alias i zaszyfrowane kopie klucza przechowuj w prywatnym
menedżerze haseł; przygotuj dwie niezależne zaszyfrowane kopie offline. Sprawdź
odtworzenie kopii na innym zaufanym komputerze: certyfikat musi mieć identyczny
fingerprint. Utrata klucza/hasła uniemożliwia zwykłe aktualizacje. GitHub Secrets
nie są kopią zapasową z możliwością późniejszego odczytu.

Przykład przesłania istniejącego klucza z Linuxa bez wypisywania wartości:

```bash
base64 -w0 "$HOME/.local/share/omnicore-signing/omnicore-release.p12" | \
  gh secret set ANDROID_RELEASE_KEYSTORE_BASE64 --env android-release
```

Hasła wprowadź w chronionym interfejsie GitHuba lub interaktywnym `gh secret set`;
nie używaj `--body` z hasłem w argumentach procesu.

## CI: środowisko `android-release`

Właściciel konfiguruje GitHub Environment `android-release`, wymaganych recenzentów
i ograniczenie gałęzi wyłącznie do main. Nie wystarczy sama nazwa środowiska.
Sekrety mają być environment secrets; nie udostępniać ich pull requestom/forkom:

- `ANDROID_RELEASE_KEYSTORE_BASE64`: base64 istniejącego prywatnego keystore.
- `ANDROID_RELEASE_STORE_PASSWORD`, `ANDROID_RELEASE_KEY_ALIAS`, `ANDROID_RELEASE_KEY_PASSWORD`.

Base64 jest kodowaniem, nie szyfrowaniem. Prześlij je przez zabezpieczony formularz
GitHuba lub stdin CLI; nie drukuj go w logach. Niesekretne environment variables:

- `ANDROID_RELEASE_APPLICATION_ID`: wybrany trwały ID.
- `ANDROID_RELEASE_CERT_SHA256`: publiczny fingerprint, 64 cyfry hex (dwukropki dozwolone).

Po scaleniu konfiguracji uruchom ręcznie workflow **Native Android APK** na main
z `signed_release=true`. Job nie publikuje wydania, uruchamia się tylko ręcznie
na main i używa środowiska `android-release`. Wymaga zgody jego recenzenta.
Keystore jest odtwarzany jako plik 0600 poza checkoutem i usuwany po jobie;
artefakty zawierają tylko APK, manifest z publicznym fingerprintem oraz SHA-256.

Brak sekretów, inny fingerprint, błędny ID, build debug lub certyfikat Android Debug
powodują odmowę przygotowania artefaktu release. Nie ma fallbacku na podpis debug.
Workflow i Gradle używają zmiennych środowiskowych, nie haseł w argv lub plikach Git.
W tej sesji nie zweryfikowano rzeczywistego klucza właściciela ani podpisu Stable.

## Budowanie lokalne z istniejącym kluczem

Ustaw w prywatnym środowisku, bez echa i zapisu do repozytorium:
`OMNICORE_ANDROID_KEYSTORE` (bezwzględna ścieżka poza repozytorium),
`OMNICORE_ANDROID_STORE_PASSWORD`, `OMNICORE_ANDROID_KEY_ALIAS`,
`OMNICORE_ANDROID_KEY_PASSWORD`, `OMNICORE_ANDROID_RELEASE_ID`,
`OMNICORE_ANDROID_CERT_SHA256` i `ANDROID_HOME`. Nie używaj `--info`/`--debug`
dla diagnostyki procesu z sekretami. Nie łącz zadań debug i release w jednym wywołaniu.

```bash
cd apps/android
./gradlew --no-daemon :app:assembleRelease
cd ../..
python3 scripts/package_android.py --release
```

Pakowanie sprawdza `apksigner verify --print-certs`, fingerprint/ID, wersję,
brak flagi debuggable, ABI ARM64, wyrównanie ZIP/ELF 16 KiB oraz SHA-256.
Nie otrzymało prawdziwego klucza właściciela w Cloud, więc pozytywny test tego
podpisu i podpisany Stable APK pozostają niewykonane.

## Aktualizacja bez kasowania danych

Zachowaj poprzedni podpisany APK. Najpierw porównaj tożsamości bez instalowania:

```bash
python3 scripts/android_identity.py poprzedni.apk nowy.apk
```

Narzędzie sprawdza faktyczne podpisy i metadane: ten sam application ID,
identyczny certyfikat i rosnący versionCode. Niezgodność kończy się błędem;
nic nie instaluje ani nie usuwa. Rotacja kluczy/lineage nie jest tu obsługiwana.

Potem na dedykowanym emulatorze lub urządzeniu testowym skonfiguruj starą aplikację,
zapisz język/motyw/adres/token i rozmowę w backendzie. Wykonaj `adb install -r nowy.apk`
bez `-d`, uninstall lub clear-data. Sprawdź ustawienia, odczyt Keystore, historię,
połączenie i streaming. Nie odinstalowuj starej aplikacji, aby ominąć niezgodny
podpis. Sprawdzenie tożsamości samo nie dowodzi zachowania danych na urządzeniu.
Wynik testu, publiczny fingerprint i identyfikator pakietu można przekazać do
zatwierdzenia; nigdy nie wysyłaj prywatnego klucza, haseł ani tokenu backendu.
