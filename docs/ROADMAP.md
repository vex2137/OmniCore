# OmniCore — ROADMAP

Plan rozwoju lokalnej platformy AI. Wersja rozwojowa: **0.1.0 RC → Stable**.
Ostatnia aktualizacja: **2026-10-29**.

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
integracji main i szkicu wydania. Image AI i Web nie są teraz wdrażane. Natywny Android jest bieżącym rozszerzeniem.

## Android — klient API po dostarczeniu AppImage

- [x] Osobny Kotlin/Compose/Material 3, bez WebView i inferencji telefonu.
- [x] Rozmowy/historia, modele, REST/SSE/cancel, ustawienia, PL/EN i motywy.
- [x] Bezpieczna konfiguracja LAN/HTTPS, Keystore, brak tokenów w logach/backupie.
- [x] Rzeczywisty debug-signed APK ARM64, wrapper i CI, testy JVM/zasobów oraz lint.
- [x] Zweryfikować test interfejsu w emulatorze CI i udokumentować wynik (API 30 x86_64).
- [ ] Osobno sprawdzić instalację i działanie na fizycznym ARM64.
- [ ] Lokalna inferencja Android pozostaje przyszłym, odrębnym zakresem.

### Android — część 2: rozwinięcie klienta API

- [x] Oddzielna granica repozytorium, Flow/StateFlow i testowalny ViewModel.
- [x] Zachowanie zadania w tle, jawny Stop, odczyt po restarcie i reconnect bez nowego promptu.
- [x] HF: search/pliki, potwierdzenie rozmiaru/licencji, download/progress/pause/resume/import.
- [x] Parametry rozmowy bez utraty ustawień GPU, filtrowanie silników i diagnostyka wersji API/zadań.
- [x] Target/compile Android 16/API 36; kontrola ZIP/ELF 16 KiB, wersja APK Alpha.2.
- [x] Pełny zestaw JVM/lint/emulatory 30/36 PASS; wyniki, APK i SHA-256 opublikowane.
- [ ] Fizyczny ARM64 POCO/Xiaomi Android 16: instalacja, IME, orientacja i tło/HyperOS.
- [x] Publiczna Alpha.2 opublikowana po zgodzie właściciela i weryfikacji paczek.
- [ ] Stały produkcyjny klucz podpisu wymaga odrębnej konfiguracji sekretów.

Publiczna Alpha.1 zachowuje swoje pliki i sumy. Paczki Alpha.2 są w Actions i publicznym
wydaniu po ręcznej zgodzie właściciela. Automatyczne workflow uploadują tylko do draft.

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

## Alpha.3 — stabilizacja przed dalszymi modułami

- [x] Kolejka/cancel/cleanup i mutacje rozmów serializowane między klientami.
- [x] Oddzielne reasoning i final answer, jawne błędy pustej odpowiedzi/limitu/kontekstu.
- [x] Snapshot modelu i statystyki przy wiadomości, zgodne stare dane/idempotency.
- [x] Linux: natywne dymki/Markdown/kod/kopiowanie, wyszukiwanie historii, onboarding,
  izolacja transportu, raport bez sekretów i wybór QPA.
- [x] Android: język systemowy i trwały wybór, nawigacja, reconnect/statusy/retry/refresh.
- [x] Opcjonalna binarka CUDA + niezależny CPU, jawny fallback w auto, build SM 89.
- [x] Zweryfikować kompilację CUDA w CI.
- [x] Właściciel zgłosił test obu GGUF CPU/Auto/CUDA na RTX4060 w PR #6;
  osobna akceptacja nowej paczki pozostaje bramką Stable.
- [x] Zbudować i uruchomić AppImage/APK Alpha.3 oraz CI/emulatory (szkic zachowany).
- [ ] LFM3/Qwen3.5: zweryfikować dokładne pliki użytkownika i powtórzyć dłuższe prompty.
- [ ] Fizyczne POCO/Xiaomi, CachyOS i NVIDIA: testy na właściwych urządzeniach.

Image AI, Web, lokalna inferencja Android i nowe komponenty Rust pozostają poza
bieżącą implementacją. Publiczne wydanie Alpha.3 wymaga osobnej zgody właściciela.

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

## 0.1.0 RC → Stable

Automatyczne wykrywanie CUDA, izolacja bibliotek, potwierdzony offload, VRAM,
parser myślenia/SSE, prosty wybór wykonania, partie historii i test sprzętowy są
zaimplementowane. Pozostają finalne paczki/CI RC i test właściciela na CachyOS/RTX4060
oraz telefonie. Trwały produkcyjny podpis Androida jest oddzielną bramką; RC ma
osobny identyfikator, aby nie wymagać usuwania wcześniejszej Alpha.
Nie publikować v0.1.0 przed [potwierdzeniem](RELEASE_GATE.md).

RC.1 jest udostępniona jako publiczne prerelease z 11 załącznikami. Main zawiera
implementację po PR #5, CI źródła i main PASS. Następny krok: potwierdzenie raportu
CachyOS/RTX4060 i telefonu oraz docelowego podpisywania, zgodnie z RELEASE_GATE.md.


## Bieżąca sesja Stable — ustalony zakres

- P0: zachować scalone PR #6/#7, ograniczyć log silnika, poprawić odzyskiwanie
  współdzielonego streamingu Androida i transport SSE Qt; testy i paczki RC.2.
- P1: brak specyfikacji „wydzielenia paska” i „algorytmu” w dokumentacji,
  pasującej historii commitów oraz zgłoszeniach repozytorium (brak issues).
  Nie ustalono, który pasek, ani wejść/wyjść i reguł algorytmu. Pominięte;
  wymagany jest konkretny widok/komponent oraz przykłady oczekiwanego zachowania.
- P2: zachować decyzję z pomiarów `benchmarks/linux-cpu-baseline.json` i plan
  `native/README.md`. Python/FastAPI/SQLite/orkiestracja, C++/CUDA w llama.cpp,
  Kotlin/Compose/API w Androidzie; Rust dopiero po wykazaniu potrzeby i korzyści.
  Błąd rosnącego logu usuwa ograniczony bufor i lifecycle asyncio bez nowego ABI.
- P4: istniejący znak, bez zmiany marki; Android adaptive icon i marginesy.
- P5: artefakty na GitHubie, PR do zatwierdzenia; brak automatycznego merge
  ani finalnego tagu/release. Telefon, docelowy podpis i zgoda właściciela są bramkami.


RC.2: poprawki P0/P4, CI i kanoniczne paczki kodu 064005b są zweryfikowane.
Obie paczki i sumy dostarczono do Actions oraz niepublicznego szkicu; PR #8
pozostaje do przeglądu. Wyniki i aktualne bramki: RELEASE_GATE.md.
P1 pozostaje bez specyfikacji, P2 bez uzasadnienia Rust. Pozostają test telefonu,
akceptacja nowej paczki na RTX4060/CachyOS, podpis produkcyjny i zgoda na Stable.


## Dodatkowy priorytet — backend i podpis APK

RC.3 zachowuje automatyczny start GUI, dodaje wyłączność bazy/cyklu życia serwera,
wykrywanie lokalnego portu, stany i retry oraz headless AppImage --serve. Android
ma odrębny test konfiguracji bez jej nadpisania i reconnect. Nie skanuje LAN.
Konfiguracja podpisu właściciela, pin certyfikatu, chroniony ręczny job i kontrola
tożsamości aktualizacji są przygotowane. Produkcyjny klucz nie powstał w Cloud;
przygotowano instrukcję bezpiecznego utworzenia, dwóch kopii i odzyskiwania.
Pozostają: rzeczywista konfiguracja/backup klucza, podpis APK, zgodna aktualizacja
na urządzeniu, akceptacja sprzętowa oraz osobna zgoda na Stable.
