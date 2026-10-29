# OmniCore AppImage x86_64

Nazwa pliku: `OmniCore-0.1.0-rc.1-x86_64.AppImage`.
Paczka zawiera Python 3.12, PySide6/Qt6, backend i opcjonalnie sprawdzony CPU
llama.cpp. Nie zawiera wag, Ollamy ani CUDA. Nie wymaga instalowania Pythona.

## Uruchomienie

Pobierz AppImage i sąsiadujący plik `.sha256` ze szkicu wydania (dostęp dla właściciela)
lub z artefaktu workflow **Linux desktop and AppImage**, gdy jest dostępny:

```sh
sha256sum -c OmniCore-0.1.0-rc.1-x86_64.AppImage.sha256
chmod +x OmniCore-0.1.0-rc.1-x86_64.AppImage
./OmniCore-0.1.0-rc.1-x86_64.AppImage
```

Wymagane Linux x86_64, glibc, serwer graficzny X11/Wayland, biblioteki systemowego
stosowania okien/OpenGL oraz czcionki. Build CI na Ubuntu 22.04 jest docelowym
artefaktem; wymagania glibc zależą od rzeczywistego hosta budowania i zapisuje je
manifest. Nie należy utożsamiać różnych buildów i ich SHA-256. Silnik CPU używa
AVX2/FMA/F16C/BMI2; starszy procesor może wymagać własnego zgodnego silnika.
Alpha.3 wybiera Wayland/X11 według sesji i respektuje jawne `QT_QPA_PLATFORM`.
Można wymusić `QT_QPA_PLATFORM=xcb` albo `wayland`; potrzebna jest odpowiednia sesja.
AppRun izoluje pluginy Qt/KDE hosta od dołączonego ABI. Wyniki rzeczywistych testów
pakietu są w PROGRESS.md; nie deklarujemy fizycznego CachyOS ani CUDA.
Opcjonalny niezależny silnik CUDA można wskazać w ustawieniach: [CUDA.md](CUDA.md).

Bez obsługi FUSE użyj wspieranego trybu ekstrakcji:

```sh
APPIMAGE_EXTRACT_AND_RUN=1 ./OmniCore-0.1.0-rc.1-x86_64.AppImage
# Alternatywnie:
./OmniCore-0.1.0-rc.1-x86_64.AppImage --appimage-extract
./squashfs-root/AppRun
```

Poprzedni AppImage przetestowano w trybie extract-and-run na X11/Xvfb oraz
Qt offscreen, z backendem i prawdziwym GGUF. Mount przez FUSE nie jest dostępny
w środowisku testowym. Dane i konfiguracja są trwałe poza obrazem, zgodnie z
[LINUX_DESKTOP.md](LINUX_DESKTOP.md). Ścieżka wbudowanego silnika jest wykrywana
ponownie po każdym mount/ekstrakcji; tymczasowa ścieżka nie trafia do preferencji.

W środku znajduje się plik `.desktop`, ikona SVG, `build-manifest.json`, licencje
oraz informacje o źródłach. Integracja menu pulpitu jest opcjonalna: można skopiować
wpis `.desktop` do `~/.local/share/applications`, zmieniając Exec/Icon na własne
stałe ścieżki. AppImage nie modyfikuje automatycznie systemowego menu.

## Powtarzalny proces budowania

Wymagane: Linux x86_64, Python 3.12/uv, `squashfs-tools`, `patchelf` oraz zależności
systemowe Qt. Zależności Pythona są przypięte w uv.lock. Budowanie silnika CPU
według [ENGINES.md](ENGINES.md), commit `c3df4b7e22a1ac38da663552d19e649dd97ca936`.

```sh
uv sync --frozen --extra desktop --group gui-test --group packaging
uv run --frozen python scripts/build_appimage.py \
  --llama-server /absolute/llama.cpp/build/bin/llama-server
xvfb-run -a uv run --frozen python scripts/test_appimage.py
# Osobno: realna inferencja w faktycznym AppImage, bez pobierania wag:
xvfb-run -a uv run --frozen python scripts/test_appimage.py --gguf /absolute/model.gguf
```

Bez `--llama-server` paczka korzysta z ręcznej konfiguracji silnika. Build nie
pobiera modeli ani nie wykonuje kodu repozytoriów modeli. PyInstaller tworzy onedir
z własnym Pythonem, Qt, pluginami i kontraktami zasobów backendu; AppDir jest
kompresowany przez mksquashfs i łączony ze zweryfikowanym runtime AppImage typu 2.
`packaging/linux/runtime.json` przypina SHA-256 oficjalnego runtime. Zmiana zasobu
`continuous` powoduje błąd checksumy; aktualizację trzeba zweryfikować u źródła,
nie zmieniać oczekiwanej sumy tylko po to, aby build przeszedł.

`--runtime`, `--mksquashfs`, `--patchelf`, `--output` pozwalają wskazać lokalne
narzędzia. Silnik i zależności ELF otrzymują względny RPATH. Manifest zapisuje commit
źródła, Python, host/glibc, runtime i checksumy silnika. Proces jest odtwarzalny
operacyjnie; różne hosty/timestamps/toolchainy nie gwarantują identycznych bajtów.
Zbudowany plik zawsze otrzymuje własne `.sha256`. Artefakty/binarne wagi nie trafiają do Git.

Workflow `.github/workflows/linux-appimage.yml` uruchamia testy backendu/GUI bez GPU,
buduje CPU llama.cpp, buduje AppImage, uruchamia go dwukrotnie, sprawdza restart,
trwałą historię/katalog/preferencje i brak osieroconego backendu, a następnie wysyła artefakt
na 30 dni. Nie publikuje release. Testy modeli są osobne i jawnie wymagają wag.

## Alpha.3 — integralność i szkic

Nazwa i manifest pochodzą z `backend/src/omnicore/distribution.json`.
Workflow `Attach verified Alpha 3 packages to draft` wymaga dwóch zakończonych
sukcesem buildów z dokładnie tego samego SHA, sprawdza manifesty i SHA-256, po czym
uploaduje AppImage/APK wyłącznie do istniejącego szkicu `v0.1.0-alpha.3`.
Nie publikuje wydania i odrzuca publiczny cel. Artefakty Actions wymagają konta
GitHub; szkic jest dostępny osobom uprawnionym w repozytorium.

## RC: automatyczne GPU i test właściciela

Nowe ustawienia pokazują Auto/CPU/CUDA; ręczne ścieżki pozostają zaawansowaną opcją.
Auto używa CUDA tylko po potwierdzeniu offloadu; rzeczywiste urządzenie i fallback
są zapisane przy wiadomości. Test `--hardware-test` działa z dołączonym Pythonem
bez GUI, z własną tymczasową bazą. Nie wskazuj istniejącej bazy do testów.
[Instrukcja i blokada Stable](RELEASE_GATE.md).
