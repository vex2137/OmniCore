# Etap 2 — Text AI: plan, integracje i weryfikacja

Gałąź: `feature/0.1.0-alpha`. Punkt wejścia: `1a2826b55efa419629f462233e1e56f29d10fa79`.
Etap 1 i projekt opcjonalnego Rust pozostają zachowane. Bez GUI i Image AI.

## Audyt przed implementacją (2026-10-28)

Odczytano AGENTS.md, ARCHITECTURE.md, ROADMAP.md, PROGRESS.md, historię i kod
backendu, schematy, migrację 001, zabezpieczenia oraz kontrakty.
GitHub read działa; lokalny HEAD odpowiada zdalnej gałęzi. `main` pozostaje
`0f91a3e9a7ba28cac3324238248e1fda75fdb174`.

Bazowe testy: 64 PASS i 1 błąd `CancelledError` podczas zamykania WebSocket
(`test_invalid_websocket_payload_is_error_and_connection_remains_usable`).
Naprawa cyklu życia połączenia należy do części A/F; nie usuwać asercji ani testu.

Brak zainstalowanych llama-server i Ollamy, brak potwierdzonego GPU.
Przygotowywany build CPU z oficjalnego repozytorium ggml-org/llama.cpp.
Sieć blokuje Hugging Face (CONNECT 403); wymagania domen zapisano w szkicu
konfiguracji. Sam zapis szkicu nie otwiera dostępu ani nie potwierdza inferencji.

## Kolejność A–F i warunki przejścia

| Część | Zakres | Walidacja przed commitem |
| --- | --- | --- |
| A | Asynchroniczne adaptery HTTP, llama-server jako własny proces loopback, diagnostyka wersji i CPU/GPU, opcjonalna Ollama | Testy protokołów i błędów, brak silników nie blokuje fundamentu, regresja 65 testów |
| B | Bezpieczny import przez referencję, ograniczony parser GGUF, katalog modeli w SQLite | Dobre/złe GGUF, metadane, symlinki/traversal, migracja i katalog bez kopiowania wag |
| C | Wyszukiwanie HF i plików GGUF, potwierdzone pobrania, resume/checksum/progress/cancel | Kontrolowany serwer HTTP i błędy sieci; realny HF tylko gdy polityka pozwala |
| D | Rozmowy i wiadomości, parametry, wyszukiwanie, JSON import/eksport | Trwałość po restarcie, zachowanie danych, walidacja i transakcje |
| E | Kolejka generowania, zdarzenia, streaming, stany, anulowanie i zapis historii | Testy obu protokołów, brak duplikatów, rozłączenie, timeout, OOM, restart |
| F | Wersjonowane API i kontrakty, lokalizacja, dokumentacja i testy rzeczywistych silników | Pełna regresja, smoke, build; osobno scenariusz GGUF bez Ollamy |

Testy protokołów z kontrolowanym serwerem i sztucznymi plikami są testami
jednostkowymi/integracji komponentów, nie dowodem rzeczywistej inferencji.
Rzeczywiste testy modeli muszą wskazać binarkę, wersję/commit, model, checksum,
sprzęt i wynik. Brak sieci/modelu/GPU oznacza niewykonany test, nie PASS.

## Decyzje

- Python 3.12/FastAPI pozostaje hostem. HTTP do silników jest asynchroniczne;
  lokalne połączenia omijają proxy egress, HTTPS do HF zachowuje proxy i CA.
- Proces jest uruchamiany wyłącznie z wcześniej skonfigurowanej zaufanej binarki,
  listą argumentów, bez powłoki. OmniCore zamyka tylko własny proces.
- Ścieżki modeli ogranicza konfigurowana przez administratora lista katalogów;
  API nie może rozszerzać tej listy. Import nie kopiuje wag.
- Istniejący kontrakt `/api/v1` pozostaje działający; nowe trasy i schematy są
  dodatkiem. Health nadal raportuje wersję schematu fundamentu, a nowe migracje
  modułu Text AI mają własny jawny marker w tej samej SQLite, aby zachować testy
  i znaczenie istniejącego pola `database_version`.
- Katalog, rozmowy i zadania są trwałe. Stan zadania po przerwaniu procesu
  backendu zostaje oznaczony jako przerwany, a częściowa odpowiedź zachowana.
- Maksymalnie jedna generacja jednocześnie domyślnie. Pełne fragmenty tekstu
  są odtwarzalne z historii zadania; WS nie jest jedynym źródłem prawdy.
- Nie uznajemy GGUF za obsługiwany tylko na podstawie rozszerzenia/metadanych.
  Udane załadowanie i rzeczywista generacja są osobnymi dowodami kompatybilności.

## Stan bieżący

Audyt zakończony. Część A w realizacji; pozostałe części oczekują.
