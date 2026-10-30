# Changelog

## 0.1.0-rc.5 — przygotowanie, bez publicznej publikacji

- QR: deduplikacja skanowania, trwałe szyfrowane wznowienie, weryfikacja połączenia,
  bezpieczne ponowienie tej samej wymiany i nowy kod po wygaśnięciu; zegar serwera.
- Nazwane tokeny API: jednorazowe ujawnienie, zakresy, wygaśnięcie, ostatnie użycie,
  unieważnianie jednego/wszystkich dodatkowych tokenów; zgodność starego QR.
- Wspólny czat modeli OpenAI/Anthropic/Gemini/OpenRouter/własnego API OpenAI,
  natywne ustawienia obu klientów, Secret Service, streaming/Stop/usage/tytuły.
- Krótkie tytuły z deterministycznym limitem i bez nadpisywania ręcznych nazw.
- Przeciągany, zwijany panel historii Linux z trwałą szerokością i pełnym tooltipem;
  Android wyświetla długie nazwy z wielokropkiem i zachowuje ich edycję.
- Osobny APK `.rc5`, versionCode 8, testowy podpis; zachowane dane i paczki RC.4.

## 0.1.0-rc.4 — przygotowanie, bez publikacji

- Android: trwały wybór CPU/Auto/CUDA, warstwy GPU, rozdzielenie ustawień rozmowy
  i domyślnych, jawne parametry generowania i rzeczywiste statystyki wykonania.
- Linux: serwer i urządzenia, start/stop/restart, autostart, prywatny LAN i własność procesu.
- Jednorazowe parowanie QR, skaner Androida i odwoływalne tokeny urządzeń.
- Wspólne automatyczne nazwy oraz potwierdzane, zbiorcze usuwanie historii.
- Zachowane dotychczasowe wydania, dane i bramki sprzętu/podpisu/Stable.

## 0.1.0-rc.3 — start backendu i przygotowanie podpisu

- Jeden backend na katalog danych, lokalne wykrywanie portu bez zapisu tokenów.
- Czytelne stany GUI i ponowny start po awarii; AppImage `--serve` dla zaawansowanych.
- Android: test adresu/tokena bez nadpisania konfiguracji i przycisk reconnect.
- Podpis właściciela: chroniony manualny job, pin certyfikatu, brak debug fallbacku,
  sprawdzenie tożsamości aktualizacji oraz instrukcja trwałych kopii klucza.
- Testowy APK RC3 instaluje się obok wcześniejszych wersji. Produkcyjnego klucza
  nie utworzono; podpis Stable, aktualizacja na urządzeniu i testy sprzętowe nadal
  wymagają właściciela. RC.2 zachowuje swoje bajty i sumy.

## 0.1.0-rc.2 — kandydat do weryfikacji, nie Stable

- Zachowana poprawka PR #6: verbose llama.cpp i rzeczywista weryfikacja offloadu.
- Ograniczony stderr silnika: 128 KiB w pamięci, bez rosnącego pliku na dysku.
- Android wznawia streaming po otwarciu/odświeżeniu rozmowy innego klienta.
- Oddzielny timeout zimnego ładowania modelu i limit całkowitego czasu REST.
- Ikona Androida: adaptive icon z bezpiecznymi marginesami i spójnym znakiem Linux.
- Identyfikator RC2 jest oddzielny od Alpha i RC.1; versionCode 5, podpis testowy.

PR #6 zawiera zgłoszone przez właściciela wyniki obu GGUF CPU/Auto/CUDA na RTX4060.
To nie test Cloud ani końcowe zatwierdzenie tej paczki. Telefon i trwały podpis APK
pozostają bramkami wydania; nie utworzono finalnego tagu v0.1.0.

## 0.1.0-rc.1

- Automatyczne wykrywanie lokalnych silników CUDA, niezależnie od silnika CPU w AppImage.
- Izolacja bibliotek AppImage, potwierdzenie offloadu, Auto fallback, VRAM i diagnostyka.
- Przyrostowa obsługa znaczników myślenia i wieloliniowego SSE; brak pustego sukcesu.
- Nazwa modelu i statystyki przy odpowiedzi, prosty wybór wykonania i zaawansowane opcje.
- Partie starszych dymków w długich rozmowach, bez utraty historii.
- Android: poprawki Alpha.3, wybór wykonania na backendzie i raportowane warstwy GPU.
- Izolowany test sprzętowy wewnątrz AppImage i instrukcja bramki Stable.

Rzeczywiste testy RTX4060, LFM3/Qwen użytkownika i telefonu pozostają do potwierdzenia.
RC APK ma testowy podpis oraz osobny identyfikator; nie zastępuje zainstalowanej Alpha.

## 0.1.0 Alpha.3

Synchronizacja kolejki i rozmów, anulowanie, snapshot modelu/statystyki, natywne
Markdown/dymki/wyszukiwanie Linux oraz systemowy język/reconnect/UX Android.
Szczegóły testów i checkpointów: docs/PROGRESS.md. Alpha.3 pozostała szkicem.

## 0.1.0 Alpha.2 / Alpha.1

Pierwsze publiczne testowe paczki Linux/Android i lokalna inferencja GGUF CPU.
