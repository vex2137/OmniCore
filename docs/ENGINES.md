# Silniki tekstowe — instalacja i konfiguracja

OmniCore działa bez zainstalowanego silnika. GGUF wymaga `llama-server` z
llama.cpp; **Ollama nie jest wymagana**. Nie instalujemy silników ani modeli
automatycznie podczas uruchamiania backendu. Nie umieszczaj wag ani binarek w Git.

## llama.cpp na Linux

Użyj własnej zaufanej instalacji lub zbuduj oficjalne źródło
`https://github.com/ggml-org/llama.cpp`. Wymagane są kompilator C/C++, CMake,
Ninja i Git (na CachyOS odpowiednie pakiety zarządza pacman). Poniższe polecenia
dotyczą nowego katalogu, nie istniejącego checkoutu z cudzymi zmianami:

```sh
git clone https://github.com/ggml-org/llama.cpp.git llama.cpp
git -C llama.cpp checkout --detach c3df4b7e22a1ac38da663552d19e649dd97ca936
cmake -S llama.cpp -B llama.cpp/build -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=OFF -DGGML_NATIVE=OFF \
  -DGGML_OPENMP=OFF -DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=OFF \
  -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_SERVER=ON
cmake --build llama.cpp/build --target llama-server -j 2
llama.cpp/build/bin/llama-server --version
llama.cpp/build/bin/llama-server --list-devices
```

Ten build CPU i commit wykonano w chmurze: GNU 14.2.0, wersja `0.8.0-dev`,
uruchomienie `--version` i `--list-devices` zakończyło się powodzeniem. Lista GPU
jest pusta. Nie jest to test modelu ani dowód zgodności z CachyOS/RTX 4060.
Build CUDA/ROCm/Vulkan wymaga osobnej konfiguracji, właściwego toolchainu i testu
na posiadanym sprzęcie. Nie obiecujemy wsparcia każdej kwantyzacji/architektury.

```sh
export OMNICORE_LLAMA_SERVER=/pełna/ścieżka/llama.cpp/build/bin/llama-server
export OMNICORE_MODEL_ROOTS=/pełna/ścieżka/do/modeli
uv run --frozen omnicore --data-dir .local-data
```

`OMNICORE_MODEL_ROOTS` jest listą katalogów rozdzielonych `:` na Linux.
Domyślnie dopuszczony jest tylko prywatny katalog pobierania `<data-dir>/models`.
Import z zewnętrznego katalogu wymaga jawnego wskazania go w konfiguracji procesu.
Nie używaj symlinków ani `..`. Nie przenoś/zmieniaj wag podczas używania modelu.

Jeśli `OMNICORE_LLAMA_SERVER` nie jest ustawione, szukamy `llama-server` w PATH.
API nie przyjmuje ścieżki do programu ani dowolnych flag/poleceń. Proces dostaje
listę argumentów, loopback i jeden slot; żaden shell nie jest uruchamiany.
Linux bootstrap ustawia `PR_SET_PDEATHSIG`, aby własny silnik zakończył się także
po śmierci backendu. Przy normalnym zamknięciu używamy SIGTERM, następnie SIGKILL
po 5 s. Nie zatrzymujemy obcych serwerów. Obsługa tego procesu jest obecnie linuksowa.

Domyślnie generacja działa CPU-only (`device=cpu`, `gpu_layers=0`). Przy dostępnej
wersji GPU wybierz `device=auto` lub identyfikator z diagnostyki i liczbę warstw.
Żądanie GPU przy pustej liście urządzeń jest odrzucane, bez udawanej akceleracji.
Kontekst, architektura modelu i kwantyzacja nadal muszą mieścić się w możliwościach silnika.

Jeśli model nie ma właściwego szablonu rozmowy, serwer może odrzucić żądanie.
Administrator może jawnie wskazać zgodny `OMNICORE_LLAMA_CHAT_TEMPLATE`, np.
`chatml` wyłącznie dla modelu, z którym został sprawdzony. Nie narzucamy jednego
szablonu wszystkim GGUF i nie wykonujemy skryptów dostarczonych z modelem.

Instalator/updater silników pozostaje przyszłym, opcjonalnym komponentem.
Jego wejściem będzie zaufany artefakt z weryfikacją pochodzenia i integralności;
obecnie dostępna jest detekcja i ręczne wskazanie programu.

## Opcjonalna Ollama

Zainstaluj Ollamę według oficjalnych instrukcji właściciela projektu i uruchom
własny lokalny serwer. OmniCore nie uruchamia skryptów instalacyjnych ani `ollama pull`.

- Domyślny adres: `http://127.0.0.1:11434`.
- `OMNICORE_OLLAMA_URL` zmienia adres (konfiguracja administratora, nie parametr API).
- `OMNICORE_OLLAMA_ENABLED=0` całkowicie wyłącza integrację.
- Synchronizacja katalogu: `POST /api/v1/text/models/sync-ollama`.
- Detekcja: `/api/version`; katalog: `/api/tags`, możliwości i licencja: `/api/show`.
- Generowanie: `/api/chat`, streaming NDJSON; zwalnianie wybranego modelu:
  `/api/generate` z `keep_alive=0`. Nie zatrzymujemy procesu serwera Ollamy.

Wspólne parametry samplowania mapujemy na udokumentowane opcje Ollamy. Pola
`device`/`gpu_layers` służą llama.cpp; domyślne `cpu/0` nie są przekazywane Ollamie
i nie obiecują CPU-only tego serwera. Niestandardowe wartości są odrzucane;
urządzenia Ollamy ustawia administrator samego silnika.
Przerwanie połączenia zamyka strumień; dodatkowe unload może się nie udać,
jeśli obcy serwer jest niedostępny. Nie obiecujemy zdalnego wymuszonego kill.

## Hugging Face i sekrety

API pobiera wyłącznie wybrany GGUF z przypiętego commita. Nie pobiera ani nie
uruchamia repozytoryjnych `.py`, bibliotek lub modeli bez potwierdzenia.
Publiczne repozytoria nie wymagają tokenu. Prywatne/gated mogą wymagać `HF_TOKEN`
podanego bezpiecznie w środowisku, nigdy w JSON, SQLite, poleceniu URL czy logu.
Authorization jest wysyłane tylko do hosta HF, nie do docelowego CDN.

Potrzebne domeny: `huggingface.co` oraz odpowiednie hosty dostarczania plików:
`cdn-lfs.huggingface.co`, `cdn-lfs-us-1.huggingface.co`, `cas-bridge.xethub.hf.co`.
Inne redirecty są odrzucane; ich dopuszczenie wymaga osobnego przeglądu.
TLS i checksumy pozostają włączone. Bez dostępnej wiarygodnej checksumy
`integrity_verified=false`; poprawny rozmiar i nagłówek nie zastępują checksumy.

W chmurze aktualna polityka zwraca CONNECT 403 dla HF. Domeny zapisano w szkicu
konfiguracji; użytkownik musi zastosować zmianę w ustawieniach. Nie traktujemy
tego jako braku tokenu ani nie omijamy polityki przez inne proxy.

## Osobne testy rzeczywistych modeli

Najpierw przygotuj istniejący zgodny model, zgodnie z jego licencją, poza Git.
Testy nie pobierają automatycznie wag. Wymagany scenariusz bez Ollamy:

```sh
export OMNICORE_TEST_LLAMA_SERVER=/pełna/ścieżka/do/llama-server
export OMNICORE_TEST_GGUF=/pełna/ścieżka/do/modelu.gguf
uv run --frozen pytest -q integration/test_llama_real.py
```

Test sprawdza brak binarki Ollamy i brak jej serwera na localhost, import, load,
rzeczywistą generację, zapis historii i unload własnego procesu. Nie ma fallbacku
do mocka; brak modelu lub silnika jest błędem warunku wstępnego, nie PASS/skip.
Ewentualny szablon testu: `OMNICORE_TEST_CHAT_TEMPLATE`.

Osobny, opcjonalny scenariusz Ollamy:

```sh
export OMNICORE_TEST_OLLAMA_MODEL=nazwa-już-zainstalowanego-modelu
uv run --frozen pytest -q integration/test_ollama_real.py
```

Zwykłe `pytest` uruchamia testy bez GPU z `backend/tests`; protokoły są testowane
kontrolowanymi odpowiedziami. W bieżącej sesji nie uruchomiono inferencji z wagami
ani testu rzeczywistej Ollamy. Wymagany scenariusz akceptacyjny pozostaje otwarty.
