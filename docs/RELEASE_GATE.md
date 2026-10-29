# 0.1.0 — bramka wydania

Bieżąca paczka: **0.1.0-rc.1**, nie Stable. Zgoda na publiczne Stable obowiązuje
po testach i osobnym potwierdzeniu sprzętowym właściciela. Nie twórz tagu v0.1.0
ani finalnego wydania przed potwierdzeniem poniższych punktów.

- [x] Końcowe CI CPU/Qt/JVM/lint/emulatory, oba artefakty i manifesty tego samego SHA.
- [x] Faktyczny AppImage: start/stop, GGUF CPU, historia i ustawienia po restarcie.
- [ ] CachyOS/RTX4060: wykrywanie lokalnego llama-server CUDA, Auto/CPU/CUDA,
  faktyczny offload i VRAM, niepusta końcowa odpowiedź LFM3 oraz Qwen3.5.
- [ ] Raport właściciela i potwierdzenie testu sprzętowego; wyniki muszą dotyczyć
  nowego OmniCore, nie samej zewnętrznej binarki.
- [ ] Android ARM64/POCO: instalacja, połączenie LAN/HTTPS, streaming, tło/obrót,
  reconnect, PL/EN, motyw i historia. Emulator nie zastępuje telefonu.
- [ ] Docelowy trwały klucz podpisu APK oraz potwierdzona ścieżka aktualizacji.
  RC ma podpis testowy i oddzielny ID `io.github.vex2137.omnicore.rc`, aby instalacja
  testowa nie wymagała usunięcia Alpha i jej danych. RC łączy się z tą samą historią
  backendu, ale wymaga własnej konfiguracji połączenia. Nie udajemy aktualizacji
  APK podpisanego innym, niedostępnym kluczem testowym poprzedniego CI.

## Test na CachyOS

Pobierz AppImage, oba skrypty i sumy z wydania RC. Sprawdź pliki `.sha256` i:

```bash
chmod +x OmniCore-0.1.0-rc.1-x86_64.AppImage
bash test_omnicore_cachyos.sh \
  ./OmniCore-0.1.0-rc.1-x86_64.AppImage \
  "$HOME/Pulpit/LFM3-1.7B-Q8_0.gguf" \
  "$HOME/Pulpit/Qwen_Qwen3.5-4B-Q8_0.gguf"
```

Nie potrzeba Pythona ani Ollamy. Test nie wymaga działającej sesji graficznej,
nie korzysta z istniejącej bazy i nie modyfikuje wag. Raport powstaje jako nowy
plik `omnicore-hardware-*.json` z prawami 0600, bez tokenów, ścieżek i logów.
Zawiera odpowiedź testową, tok./s, TTFT, tokeny, finish_reason, offload i VRAM.
Przekaż ten raport oraz wynik ręcznego uruchomienia GUI pod Wayland.

Auto wykrywa `~/llama.cpp/build/bin/llama-server`; przy działającej instalacji
użytkownika nie jest potrzebna konfiguracja ścieżki ani nowa instalacja CUDA.
Opcjonalny prebuilt CUDA SM89 jest zbudowany z CUDA 12.6 i wymaga zgodnego runtime
CUDA12/sterownika; CUDA Toolkit13 sam nie dostarcza ABI libcudart.so.12.
Jeśli potrzeba nowego silnika, `bash install_cuda_engine.sh` buduje przypięte
llama.cpp z lokalnym toolkit (SM89), bez sudo i zastępowania istniejącego silnika.
Wymaga git/cmake/ninja/nvcc/patchelf. Zgodność kompilacji z CUDA13.4 wymaga lokalnego
testu; działająca już binarka użytkownika jest preferowaną ścieżką testową.

Po potwierdzeniu: zachować raport, zamknąć blokery, przygotować podpis produkcyjny,
zaktualizować wersjonowanie/CI, ponownie zbudować i sprawdzić paczki Stable, scalić,
potwierdzić zdalne SHA, utworzyć v0.1.0 i publiczne finalne wydanie. RC nie może być
przemianowana na Stable bez tej weryfikacji.

## Zweryfikowany kandydat

Publiczne [RC.1](https://github.com/vex2137/OmniCore/releases/tag/v0.1.0-rc.1)
zawiera obie paczki, SHA-256, manifesty, skrypty z sumą i opcjonalny silnik SM89.
Źródło paczek: `09cd1d8f8f62b96512587a764b6f83ed452d0ef6`; tag RC wskazuje merge
`92a2ca02ccd06acfd81f63935d978703c73cf618`, o identycznym drzewie źródeł.
Nie istnieje tag ani Stable v0.1.0. Kolejny etap wymaga raportu sprzętowego właściciela.
Przy ręcznym teście GUI użyj Auto oraz kontekstu 4096 jak w udanym zewnętrznym teście;
RC nie zmienia automatycznie zachowanego wcześniej kontekstu 100000.
