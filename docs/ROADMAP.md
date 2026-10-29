# OmniCore — ROADMAP

Plan rozwoju lokalnej platformy AI. Wersja rozwojowa: **0.1.0 Alpha**.
Ostatnia aktualizacja: **2026-10-28**.

## Status i sposób realizacji

Repozytorium zawiera fundament Etapu 1 oraz implementację backendu Text AI Etapu 2
z testami bez GPU. Rzeczywista inferencja GGUF na CPU i transfer HF zostały zweryfikowane.
Klient Linux jest wdrożony przed Image AI. Android ma natywnego klienta API
Kotlin/Compose; Web pozostaje planowany. Test fizycznego ARM64 jest osobnym zadaniem.
Puste pola `[ ]` są zadaniami do wykonania, a nie potwierdzeniem funkcji.
Zakończenie funkcji wymaga kodu, właściwych testów i udokumentowanej weryfikacji
w [PROGRESS.md](PROGRESS.md). Zasady sesji: [AGENTS.md](../AGENTS.md).

Wybrany stos, granice modułów, plan etapów i ryzyka opisuje
[ARCHITECTURE.md](ARCHITECTURE.md). Nie ustalono terminów ani potwierdzonej
macierzy sprzętowej. Testy fundamentu nie potwierdzają zgodności modeli.

## Zmiana priorytetu — Linux desktop przed Image AI

Na polecenie właściciela realizujemy teraz natywny klient PySide6/Qt6 i AppImage.
Pierwszy przepływ GGUF/llama.cpp bez Ollamy przeszedł rzeczywisty test backendu
i GUI na CPU. Pozostają testy rozszerzone, pakowanie, stabilizacja oraz weryfikacja
integracji main i szkicu wydania. Image AI, Web i Android nie są teraz wdrażane.

## Android — klient API po dostarczeniu AppImage

- [x] Osobny Kotlin/Compose/Material 3, bez WebView i inferencji telefonu.
- [x] Rozmowy/historia, modele, REST/SSE/cancel, ustawienia, PL/EN i motywy.
- [x] Bezpieczna konfiguracja LAN/HTTPS, Keystore, brak tokenów w logach/backupie.
- [x] Rzeczywisty debug-signed APK ARM64, wrapper i CI, testy JVM/zasobów oraz lint.
- [x] Zweryfikować test interfejsu w emulatorze CI i udokumentować wynik (API 30 x86_64).
- [ ] Osobno sprawdzić instalację i działanie na fizycznym ARM64.
- [ ] Lokalna inferencja Android pozostaje przyszłym, odrębnym zakresem.

## Przekrojowo — Python i opcjonalny Rust

**Status:** projekt architektury opisany; własne komponenty Rust nie są wdrożone.
Ukończony Etap 1 pozostaje zachowany. Python/FastAPI, SQLite, REST/WebSocket,
klienci Qt/React/Kotlin i integracje istniejących silników pozostają podstawą.
Rust nie jest warunkiem ukończenia Alpha ani nową zależnością standardowego setupu.

Szczegóły wariantów PyO3/maturin i osobnego procesu API, koszty platformowe,
zgodność oraz bramki opisuje
[architektura warstwy Rust](ARCHITECTURE.md#opcjonalna-warstwa-rust--decyzja-architektoniczna).

- [x] Opisać podział Python/Rust, warianty integracji, priorytety i warunki decyzji.
- [ ] P0: rozwijać integracje tekstowe i obrazowe według istniejących etapów,
  zachowując testy oraz publiczne kontrakty; nie przepisywać fundamentu.
- [x] P1: po wdrożeniu importu dużych plików wykonać profilowanie rzeczywistego
  przepływu i porównać go z najlepszą rozsądną ścieżką Python/bibliotek natywnych.
- [ ] Ustalić mierzalny cel przed prototypem: np. minimum 20% poprawy p95 operacji
  lub peak RSS, bez regresji poprawności i budżetu API; to cel, nie zmierzony wynik.
  Dla izolacji wymagać testu przeżycia awarii workera i pomiaru narzutu.
- [ ] Tylko po wykazaniu potrzeby wybrać jedną operację i przygotować prototyp
  PyO3/maturin albo izolowanego workera; uwzględnić FFI/IPC i koszt budowania.
- [ ] Tylko po spełnieniu celu udostępnić opcjonalny artefakt oraz przetestować
  tryby z Rust i bez Rust, anulowanie, błędy, restart, instalację i zgodność kontraktów.
- [ ] P2: ponownie ocenić scheduler/wykonawcę kolejki, pomiary zasobów i współbieżność
  wyłącznie na podstawie nowych pomiarów. Polityki, trwałość i SQLite pozostają w Pythonie.

**Zależności:** działające funkcje i workload do pomiaru, zapisany baseline,
decyzja techniczna oraz dostęp do właściwej platformy testowej. PyO3 nie jest
granicą izolacji; osobny proces wymaga nadzoru i ograniczeń OS. Linux wymaga
testowanych wheel/binarek; Android w Alpha łączy się z backendem komputera;
Web pozostaje klientem API. JNI/UniFFI i WebAssembly wymagają osobnych decyzji.

**Kryteria wdrożenia:** udokumentowana potrzeba i osiągnięty cel, zgodność wyników
i API, sprawdzona instalacja na deklarowanych platformach, limity zasobów,
bezpieczny rollback i oszacowany koszt utrzymania. Bez spełnienia tych warunków
pozostaje implementacja Python. Nie przenosić obliczeń GPU do Rust ani nie
deklarować zgodności modeli na podstawie zmiany języka.

## OmniCore 0.1.0 — Text & Image

**Status:** w realizacji — fundament Etapu 1 zaimplementowany i przetestowany;
backend Etapu 2 A–F zaimplementowany, ale jego akceptacja z rzeczywistym modelem
pozostaje otwarta. Cała wersja 0.1.0 Alpha pozostaje nieukończona.

### Fundament — Etap 1

- [x] Audyt istniejącego repozytorium, architektura i ryzyka.
- [x] Backend FastAPI uruchamiany bez GUI i GPU.
- [x] Wersjonowane schematy Pydantic, OpenAPI i JSON Schema.
- [x] SQLite, migracje transakcyjne i trwałe preferencje.
- [x] REST i zdarzenia ustawień przez WebSocket.
- [x] Katalogi PL/EN i preferencje motywu oraz trybu interfejsu.
- [x] Podstawowa kontrola dostępu, Origin/Host i rozmiaru żądań.
- [x] Testy bez GPU oraz rzeczywisty start i restart z zachowaniem danych.

Gotowość tego fundamentu nie oznacza działania czatu, obrazów, menedżera modeli
ani klientów. Przed Etapem 2 wymagany jest raport Etapu 1 zgodnie z zakresem zadania.

### Text AI — Etap 2

- [x] A: transporty llama.cpp/Ollama, detekcja, własny proces i lifecycle.
- [x] B: katalog, referencje GGUF, metadane, ograniczenia ścieżek i struktury pliku.
- [x] C: HF search/pliki i mechanizm potwierdzonego download/resume/checksum/cancel.
- [x] D: SQLite, trwałe rozmowy, model/parametry, historia i import/eksport JSON.
- [x] E: mechanizm kolejki, streamingu, idempotencji, timeoutów i anulowania.
- [x] F: nowe API/WS, kontrakty, lokalizacja, zabezpieczenia i regresja komponentów.
- [x] Wykonać rzeczywisty HF transfer: cancel/resume, checksum i import.
- [x] Wykonać wymagany scenariusz: brak Ollamy, realny GGUF i llama.cpp, odpowiedź,
  historia oraz unload. Build silnika i fixture nie spełniają tego warunku.
- [ ] Zweryfikować opcjonalną integrację rzeczywistej Ollamy z istniejącym modelem.
- [ ] Zweryfikować CachyOS/RTX 4060, dostępny backend GPU, VRAM/OOM i anulowanie na sprzęcie.

Checkboxy A–F potwierdzają implementację i testy usług/protokołów, nie deklarują
działania realnego modelu. Zewnętrzny warunek akceptacji pozostaje niespełniony.
Szczegóły i procedura wznowienia: [TEXT_AI.md](TEXT_AI.md), [ENGINES.md](ENGINES.md).
Nie rozpoczynać Etapu 3 w ramach tego zadania.

### Cele

Uruchamianie lokalnych modeli tekstowych i obrazowych, zarządzanie modelami
oraz wspólny dostęp z Linux, Web i Android z naciskiem na prywatność i wydajność.
Zakres platform oznacza natywne klienty Linux i Android oraz klienta Web;
miejsce wykonywania inferencji dla każdego klienta należy opisać przed implementacją.

### Zakres, zadania i podzadania

- [ ] Architektura, backend i API.
  - [ ] Wybrać stos, granice komponentów, protokół API i sposób obsługi zadań.
  - [ ] Opisać lokalne dane, konfigurację, błędy, anulowanie i dostęp do backendu.
- [ ] Natywny Linux, Web i natywny Android.
  - [ ] Ustalić narzędzia klientów, macierz wersji systemów i sposób połączenia.
  - [ ] Zaimplementować i przetestować podstawowy przepływ tekstu i obrazu na każdej platformie.
- [ ] Lokalne modele tekstowe i import GGUF.
  - [ ] Walidować pliki, metadane i zgodność modelu; obsługiwać błędy importu.
  - [ ] Zapewnić generowanie tekstu, strumieniowanie i anulowanie.
- [ ] Integracje Ollama i llama.cpp.
  - [ ] Zdefiniować adaptery i obsługiwane wersje oraz wykrywać dostępność silników.
  - [ ] Przetestować lokalną inferencję i błędy obu integracji.
- [ ] Generowanie obrazów, image-to-image i inpainting.
  - [ ] Wybrać silnik, obsługiwane modele i formaty wejść, wyjść oraz masek.
  - [ ] Obsługiwać kolejkę, parametry, postęp i anulowanie każdego trybu.
- [ ] Upscaling i obsługa LoRA.
  - [ ] Określić zgodność LoRA z modelami bazowymi oraz parametry skalowania.
  - [ ] Przetestować ładowanie, zmianę i odrzucanie niezgodnych zasobów.
- [ ] Menedżer modeli.
  - [ ] Dodać lokalny katalog, import, metadane, lokalizację i kontrolę integralności.
  - [ ] Zaprojektować bezpieczne usuwanie i informacje o rozmiarze oraz licencji.
- [ ] Diagnostyka sprzętu.
  - [ ] Wykrywać CPU, RAM, GPU i VRAM oraz dostępność backendów obliczeniowych.
  - [ ] Raportować ograniczenia i dobrać testy dla wspieranych konfiguracji.
- [ ] PL/EN oraz jasny, ciemny i automatyczny motyw systemowy.
  - [ ] Przygotować tłumaczenia, przełączanie języka i zapamiętywanie preferencji.
  - [ ] Przetestować oba języki i wszystkie tryby motywu na trzech platformach.
- [ ] Przygotowanie Alpha.
  - [ ] Udokumentować instalację, uruchamianie, wymagania i ograniczenia.
  - [ ] Przygotować testy jednostkowe, integracyjne i reprezentatywne testy użytkowe.

### Zależności

Wybór architektury i stosu poprzedza implementację. Integracje wymagają ustalenia
wersji Ollama i llama.cpp. Obrazy wymagają silnika i modeli o zgodnych licencjach.
Testy sprzętowe i natywnego Androida wymagają odpowiednich urządzeń lub emulatora.
Wagi modeli pozostają poza Git. Nie zakładać dostępu do GPU w środowisku chmurowym.

### Kryteria ukończenia

Wszystkie powyższe funkcje mają implementację i wyniki odpowiednich testów.
Użytkownik może zaimportować GGUF, wykonać lokalną generację tekstu z obiema
integracjami oraz użyć każdego trybu obrazowego, LoRA i menedżera modeli.
Przepływy są zweryfikowane na Linux, Web i Android; diagnostyka i interfejs
PL/EN z trzema trybami motywu działają zgodnie z udokumentowaną macierzą.
Instrukcje i znane ograniczenia są aktualne. Publiczne wydanie wymaga zgody właściciela.

## OmniCore 0.2.0 — AI Training Studio

**Status:** planowane, nierozpoczęte.

### Cele

Umożliwić proste dostrajanie LoRA oraz porównywanie jakości i wydajności modeli.

### Zakres, zadania i podzadania

- [ ] Proste dostrajanie LoRA.
  - [ ] Wybrać silnik, wspierane modele, eksport i ponowne użycie adapterów.
- [ ] Menedżer zbiorów danych.
  - [ ] Obsłużyć import, walidację, podział danych i informacje o ich pochodzeniu.
- [ ] Konfigurator treningu.
  - [ ] Walidować parametry, zgodność modelu oraz wymagania pamięciowe.
- [ ] Monitorowanie treningu.
  - [ ] Pokazywać metryki, postęp, błędy, zatrzymanie i stan zapisanych wyników.
- [ ] Benchmarki modeli.
  - [ ] Zapewnić powtarzalne scenariusze, pomiary i porównania przed/po dostrajaniu.

### Zależności

API, menedżer modeli i diagnostyka z 0.1.0; silnik treningowy, odpowiedni sprzęt,
legalnie używane dane i uzgodnione metryki. Wsparcie treningu na poszczególnych
platformach należy określić oddzielnie od dostępu do interfejsu.

### Kryteria ukończenia

Mały udokumentowany zbiór przechodzi walidację i pełny trening, powstała LoRA
jest ładowana do zgodnego modelu, a benchmark porównuje wyniki. Testy obejmują
niepoprawne dane, parametry i błędy zasobów; monitorowanie przedstawia rzeczywisty stan.

## OmniCore 0.3.0 — Media AI

**Status:** planowane, nierozpoczęte.

### Cele

Rozszerzyć platformę o lokalne przetwarzanie wideo, muzyki i mowy.

### Zakres, zadania i podzadania

- [ ] Generowanie wideo.
  - [ ] Wybrać integrację, formaty i parametry; wdrożyć generowanie i eksport.
- [ ] Generowanie muzyki.
  - [ ] Określić modele, sterowanie generacją i zapis plików.
- [ ] Text-to-speech.
  - [ ] Dodać syntezę, wybór głosu oraz sprawdzić PL/EN.
- [ ] Speech-to-text.
  - [ ] Dodać import lub nagranie, transkrypcję i sprawdzić PL/EN.
- [ ] Narzędzia audio.
  - [ ] Ustalić podstawowe operacje, formaty, odtwarzanie i eksport.

### Zależności

API zadań i menedżer modeli; dobór silników, kodeków i licencji oraz sprzętu
do testowania mediów. Dostęp do mikrofonu i plików wymaga uprawnień platformowych.

### Kryteria ukończenia

Każda funkcja ma przetestowany przepływ od wejścia do odtwarzalnego lub czytelnego
wyniku, obsługę błędów i anulowania. Testy mowy obejmują PL/EN; wymagania sprzętowe,
formaty i ograniczenia są udokumentowane.

## OmniCore 0.4.0 — AI Agents

**Status:** planowane, nierozpoczęte.

### Cele

Zapewnić kontrolowane wykonywanie zadań przez agentów oraz budowanie automatyzacji.

### Zakres, zadania i podzadania

- [ ] Agenci programistyczni.
  - [ ] Opisać cykl zadania, kontekst, zmiany kodu i sprawdzanie wyników.
- [ ] Operacje na plikach.
  - [ ] Ograniczać zakres dostępu, prezentować zmiany i obsługiwać konflikty.
- [ ] Terminal z kontrolą uprawnień.
  - [ ] Zdefiniować zgodę na operacje, izolację, limity i rejestr wykonania.
- [ ] Automatyzacje.
  - [ ] Dodać uruchamianie, zatrzymywanie, stan i historię zadań.
- [ ] Wizualny edytor workflowów.
  - [ ] Walidować grafy, zapisywać je i pokazywać postęp wykonania.
- [ ] Współpraca wielu modeli.
  - [ ] Określić role, przekazywanie kontekstu i agregację wyników.

### Zależności

Stabilizujące się API, integracje modeli i system zadań; projekt uprawnień,
izolacji i audytu przed umożliwieniem zapisu plików i wykonywania poleceń.

### Kryteria ukończenia

Agent realizuje reprezentatywne zadanie programistyczne, a workflow wykonuje
automatyzację z wieloma modelami. Testy potwierdzają egzekwowanie uprawnień,
obsługę odmowy, przerwania i konfliktów. Operacje mają widoczny rejestr i stan.

## OmniCore 1.0.0 — Stable Platform

**Status:** planowane, nierozpoczęte.

### Cele

Dostarczyć spójną, stabilną platformę z utrzymywanym API i dokumentacją.

### Zakres, zadania i podzadania

- [ ] Stabilne API.
  - [ ] Ustalić wersjonowanie, kompatybilność i testy kontraktów.
- [ ] Rozszerzenia.
  - [ ] Zaprojektować API rozszerzeń, uprawnienia i zarządzanie cyklem życia.
- [ ] Synchronizacja i obsługa wielu urządzeń.
  - [ ] Określić zakres synchronizowanych danych, uwierzytelnianie i konflikty.
  - [ ] Zapewnić kontrolę użytkownika nad przesyłaniem lokalnych danych.
- [ ] Dopracowany interfejs.
  - [ ] Zweryfikować dostępność, spójność platform, PL/EN i motywy.
- [ ] Dokumentacja.
  - [ ] Przygotować instrukcje użytkownika, administratora i twórcy rozszerzeń.
- [ ] Wydajność i bezpieczeństwo.
  - [ ] Ustalić mierzalne cele, wykonać benchmarki, przegląd zagrożeń i testy regresji.
- [ ] Rozważenie portu Windows.
  - [ ] Ocenić wykonalność, koszt i kompatybilność; zapisać decyzję.
  - [ ] Jeśli port zostanie zatwierdzony, ustalić osobny zakres i testy.

### Zależności

Zweryfikowane wcześniejsze moduły, polityka kompatybilności i utrzymania,
przeglądy bezpieczeństwa i wydajności oraz decyzje dotyczące synchronizacji.
Windows pozostaje oceną możliwości, a nie obietnicą ukończonego portu w 1.0.0.

### Kryteria ukończenia

Stabilne API i rozszerzenia przechodzą testy kontraktów; synchronizacja przechodzi
testy wielu urządzeń i konfliktów. Kryteria wydajności, bezpieczeństwa oraz
dostępności mają udokumentowane wyniki, dokumentacja jest kompletna,
a decyzja o Windows zapisana. Właściciel zatwierdza publiczne wydanie.
