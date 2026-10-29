# OmniCore AppImage x86_64

Nazwa pliku: `OmniCore-0.1.0-alpha-x86_64.AppImage`.
Paczka zawiera Python 3.12, PySide6/Qt6, backend i opcjonalnie sprawdzony CPU
llama.cpp. Nie zawiera wag, Ollamy ani CUDA. Nie wymaga instalowania Pythona.

## Uruchomienie

Pobierz AppImage i sąsiadujący plik `.sha256` ze szkicu wydania (dostęp dla właściciela)
lub z artefaktu workflow **Linux desktop and AppImage**, gdy jest dostępny:

```sh
sha256sum -c OmniCore-0.1.0-alpha-x86_64.AppImage.sha256
chmod +x OmniCore-0.1.0-alpha-x86_64.AppImage
./OmniCore-0.1.0-alpha-x86_64.AppImage
```

Wymagane Linux x86_64, glibc, serwer graficzny X11/Wayland, biblioteki systemowego
stosowania okien/OpenGL oraz czcionki. Do szkicu wydania dołączono zweryfikowany artefakt CI Ubuntu 22.04; analiza jego
ELF potwierdza wymagane symbole do **GLIBC 2.35**. Jego SHA-256 wynosi
`07397174bcbc7cf6e9f14b8193881cb71b4b04ab5c30c3c908ce053cd3dab2c2`.
Wcześniejszy lokalny build Debian 13 wymagał GLIBC 2.39 i ma inną checksumę;
nie jest to plik dołączony do szkicu. Nie należy utożsamiać różnych buildów.
Nie przetestowano fizycznego CachyOS, Wayland ani CUDA.

Bez obsługi FUSE użyj wspieranego trybu ekstrakcji:

```sh
APPIMAGE_EXTRACT_AND_RUN=1 ./OmniCore-0.1.0-alpha-x86_64.AppImage
# Alternatywnie:
./OmniCore-0.1.0-alpha-x86_64.AppImage --appimage-extract
./squashfs-root/AppRun
```

Rzeczywisty AppImage przetestowano w trybie extract-and-run na X11/Xvfb oraz
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
trwały katalog/preferencje i brak osieroconego backendu, a następnie wysyła artefakt
na 30 dni. Nie publikuje release. Testy modeli są osobne i jawnie wymagają wag.
