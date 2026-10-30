# 0.1.0 — bramka wydania

Bieżący kandydat źródeł: **0.1.0-rc.3**, nie Stable. Zgoda na publiczne Stable obowiązuje
po testach i osobnym potwierdzeniu sprzętowym właściciela. Nie twórz tagu v0.1.0
ani finalnego wydania przed potwierdzeniem poniższych punktów.

- [x] RC.2: CI CPU/Qt/JVM/lint/emulatory, oba artefakty i manifesty źródła
  `064005b980dbc1629d74291d475e4023f63e3de0` (wyniki poniżej).
- [x] RC.2 AppImage: start/stop, GGUF CPU, historia i ustawienia po restarcie;
  dodatkowo Arch Wayland/X11 i kopia danych RC.1 bez utraty starych wiadomości.
- [x] Właściciel zgłosił w [PR #6](https://github.com/vex2137/OmniCore/pull/6)
  test źródeł 745166d: LFM3-1.7B-Q8_0 i Qwen3.5-4B-Q8_0 CPU/Auto/CUDA,
  RTX4060 8 GB, hardware_ready=True, przebudowany AppImage z zewnętrznym CUDA.
  Scalona poprawka `-lv 4` pozostaje obecna. To nie test GPU wykonany w Cloud.
- [ ] Potwierdzenie nowej paczki RC.3 na CachyOS/RTX4060: wykrywanie lokalnego llama-server CUDA, Auto/CPU/CUDA,
  faktyczny offload i VRAM, niepusta końcowa odpowiedź LFM3 oraz Qwen3.5.
- [ ] Raport właściciela i potwierdzenie testu sprzętowego; wyniki muszą dotyczyć
  kandydata RC.3, nie samej zewnętrznej binarki.
- [ ] Osobne zatwierdzenie finalnej publikacji Stable przez właściciela.
- [ ] Android ARM64/POCO: instalacja, połączenie LAN/HTTPS, streaming, tło/obrót,
  reconnect, PL/EN, motyw i historia. Emulator nie zastępuje telefonu.
- [ ] Docelowy trwały klucz podpisu APK oraz potwierdzona ścieżka aktualizacji.
  RC.2 ma podpis testowy i oddzielny ID `io.github.vex2137.omnicore.rc2`, aby instalacja
  testowa nie wymagała usunięcia RC.1 (`.rc`), Alpha ani ich danych. RC łączy się z tą samą historią
  backendu, ale wymaga własnej konfiguracji połączenia. Nie udajemy aktualizacji
  APK podpisanego innym, niedostępnym kluczem testowym poprzedniego CI.

## Test na CachyOS

Pobierz AppImage, oba skrypty i sumy z wydania RC. Sprawdź pliki `.sha256` i:

```bash
chmod +x OmniCore-0.1.0-rc.3-x86_64.AppImage
bash test_omnicore_cachyos.sh \
  ./OmniCore-0.1.0-rc.3-x86_64.AppImage \
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
RC.1 pozostaje niezmieniona; jej tag, sumy i wyniki nie potwierdzają nowych bajtów RC.2.
Nie istnieje tag ani Stable v0.1.0. Kolejny etap wymaga akceptacji kandydata i telefonu.
Przy ręcznym teście GUI użyj Auto oraz kontekstu 4096 jak w udanym zewnętrznym teście;
RC nie zmienia automatycznie zachowanego wcześniej kontekstu 100000.


## RC.2 — dostarczony kandydat do akceptacji

PR #8: https://github.com/vex2137/OmniCore/pull/8 (do przeglądu, bez automatycznego merge).
Szkic RC.2 na liście wydań właściciela (wymaga logowania):
https://github.com/vex2137/OmniCore/releases
ID 428427155, tag_name v0.1.0-rc.2, draft=true, prerelease=true.
GitHub zmienia adres `untagged-*` przy edycji szkicu, dlatego odnośnik prowadzi
do listy wydań. Bezpośrednie, wersjonowane linki pobrania istnieją dopiero po publikacji;
obecnie działają linki artefaktów Actions z README.
Artefakty kodu 064005b pozostają kanoniczne; późniejszy commit dokumentacji nie zmienia
ich źródła ani bajtów. RC.1 nie została zastąpiona. Main pozostaje po PR #6/#7.

- Backend 40960267667: 158 PASS, build/smoke/kontrakty/lint PASS.
- Linux 40960267646: 158 backend + 23 Qt = 181 PASS, build i faktyczny start/restart PASS.
- Android 40960267733: 47 JVM, lint/build PASS; po 2 UI na API30 i API36, 0 skip/fail/error.
- Upload 40961298009 PASS: 11 załączników, server digest zgodny z lokalnymi sumami.
  Obie paczki pobrano ponownie ze szkicu i ponownie obliczono zgodne SHA-256.
- GGUF Cloud: SmolLM2 CPU/Auto, Qt cancel/close/restart, Kotlin z FastAPI,
  zamrożony --hardware-test CPU/Auto oraz Arch Wayland/X11 PASS.
  `hardware_ready=False` w Cloud; brak GPU i fizycznego telefonu.

SHA-256:

```text
caac9059da913eb5aaba96aa4e6765af7169971c75f569f52a1634185e078a3b  OmniCore-0.1.0-rc.2-x86_64.AppImage
3506d5f5627f12a16f7825b2f4638095bc765d734cc9530a252055157a3a8bbc  OmniCore-0.1.0-rc.2-android-arm64.apk
```

AppImage: 98707960 B. APK: 18209073 B, testowy podpis, ID .rc2.
Test właściciela ma użyć tych plików i załączonego skryptu. W kontenerze Arch
występują ostrzeżenia starszego Fontconfig o nowych regułach hosta; GUI i testy
zakończyły się powodzeniem. Kontener nie zastępuje natywnego CachyOS/RTX4060.


## RC.3 — dodatkowy priorytet startu i podpisu

RC.2 powyżej pozostaje niezmienionym punktem kontrolnym; jego sumy nie dotyczą RC.3.
Bieżące manifesty i końcowe wyniki paczek są zapisywane w [PR #8](https://github.com/vex2137/OmniCore/pull/8)
i raporcie walidacji załączonym do szkicu RC.3. Nie przenosić poprzednich PASS
sprzętowych na nowe bajty bez ich sprawdzenia.

- [x] Start bez terminala, wykrywanie istniejącego lokalnego serwera, blokada
  danych, retry i obsługa awarii: lokalne 164 backend/28 Qt PASS.
- [x] Android: test połączenia bez zapisu tokena/adresu, zachowanie aktywnego
  czatu i reconnect; lokalne 50 JVM/lint/debug build PASS.
- [x] Przygotowana konfiguracja podpisu, pin certyfikatu i instrukcja odzyskiwania.
- [ ] Chroniony depozyt właściciela, kopie i odzyskanie tego samego klucza.
- [ ] Faktyczny owner-signed APK i poprawne `apksigner` z oczekiwanym certyfikatem.
- [ ] Zgodny ID/podpis i wzrost versionCode oraz instalacja aktualizacji bez utraty
  ustawień/Keystore/historii. Negatywne testy narzędzia nie zamykają tej bramki.
- [ ] Akceptacja bieżącego AppImage i testu GGUF/CUDA na sprzęcie właściciela
  oraz fizyczny telefon. Emulatory/Cloud CPU nie zastępują urządzeń.
- [ ] Osobne zatwierdzenie publikacji v0.1.0.

Szczegóły: [podpis i aktualizacje](ANDROID_SIGNING.md), [serwer bez terminala](LINUX_DESKTOP.md#backend-lokalny-i-serwer-dla-telefonu).
Żaden produkcyjny klucz nie został utworzony w Cloud. Podpis Stable pozostaje
niewykonany, a przygotowany job nie publikuje wydania i wymaga konfiguracji właściciela.
