# NVIDIA / CPU — 0.1.0 RC

Inferencja pozostaje w llama.cpp. Rust nie uczestniczy w uruchamianiu modeli.
AppImage ma niezależny silnik CPU; opcjonalna binarka CUDA jest wybierana dopiero
na żądanie GPU. Brak bibliotek CUDA lub sterownika nie blokuje uruchomienia CPU.

## Konfiguracja

W ustawieniach Linux zachowaj ścieżkę CPU i wskaż osobno zaufany `llama-server`
zbudowany z CUDA. Dla backendu bez GUI: `OMNICORE_LLAMA_SERVER` i opcjonalnie
`OMNICORE_LLAMA_CUDA_SERVER`. Nie ustawiaj globalnego LD_LIBRARY_PATH.

- `device=cpu`, `gpu_layers=0`: zawsze CPU.
- `device=auto`, `gpu_layers>0`: wykryty silnik/urządzenie z `--list-devices`;
  przy braku GPU/runtime — CPU, z `fallback_reason=gpu_unavailable`.
- `device=CUDA0`, `gpu_layers>0`: jawne urządzenie, błąd przy niedostępności.
- `gpu_layers=0`: brak offloadu, raportowane CPU. OOM/startup failure pozostaje
  jawnym błędem; nie zmieniamy bez ostrzeżenia kontekstu, modelu lub limitu.

Metadane generacji i wiadomości zawierają `execution_device` i `fallback_reason`.
Wybór urządzenia jest informacją o konfiguracji wykonania, nie dowodem wydajności GPU.
Dobierz warstwy i kontekst do VRAM; RTX 4060 nie pomieści dowolnego modelu/kontekstu.

## Powtarzalny build

Na maszynie z CMake, Ninja, kompilatorem C++ i CUDA toolkit:

```bash
python scripts/build_llama.py --backend cuda --source /twoja/sciezka/llama-cuda --cuda-architectures 89
```

SM 89 odpowiada RTX 4060/Ada. Skrypt przypina commit llama.cpp i odrzuca inny
istniejący checkout; nie resetuje źródeł. CPU ma osobny katalog build.
Workflow `Optional llama.cpp CUDA build` kompiluje tę samą konfigurację w CUDA
12.6.3 i udostępnia opcjonalny silnik z SHA-256. Kompilacja nie dowodzi inferencji.
Pakiet wymaga zgodnego sterownika NVIDIA i runtime CUDA 12; nie zawiera sterownika.

## Bramka sprzętowa

```bash
OMNICORE_TEST_LLAMA_CUDA_SERVER=/sciezka/llama-server \
OMNICORE_TEST_GGUF=/sciezka/model.gguf \
uv run pytest integration/test_cuda_real.py -q
```

Test wymaga faktycznego offloadu warstw, pamięci procesu według nvidia-smi,
niepustej odpowiedzi i sprzątnięcia procesu. Nie uruchomiono go w środowisku Cloud,
które nie ma GPU NVIDIA. Nie deklarujemy przetestowanej inferencji RTX 4060/CUDA.
Zwykłe testy procesu/selektora używają kontrolowanego serwera i tego nie dowodzą.

## Zmiana RC względem Alpha.3

Nie trzeba wpisywać ścieżki, jeśli silnik znajduje się w skonfigurowanej lokalizacji,
zarządzanym katalogu XDG, `~/llama.cpp/build{,-cuda}/bin/llama-server`, `~/.local/bin`
lub standardowych lokalizacjach PATH/systemu. Lista jest zamknięta; nie skanujemy
dysku ani katalogów modeli. Native guard przywraca oryginalny LD_LIBRARY_PATH po
bootstrapie PyInstaller, aby CUDA13 użytkownika nie ładowała bibliotek Qt/AppImage.

Wymuszona CUDA z zerem warstw jest błędem ustawień. Auto może przejść na niezależne
CPU również przy błędzie ładowania/offloadu; powód jest jawny. NVIDIA VRAM pochodzi
z nvidia-smi, a aktywny CUDA wymaga dodatniego offloadu w logu zaufanego silnika.
Wynik `--list-devices` sam nie oznacza inferencji GPU. Starsza Alpha.3 nie wyszukiwała
samodzielnie lokalnej binarki użytkownika — to była przyczyna zgłoszonego problemu.
[Sprawdzenie rzeczywistej inferencji i bramka Stable](RELEASE_GATE.md).
