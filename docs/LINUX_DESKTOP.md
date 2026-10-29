# OmniCore — natywny Linux desktop

GUI Linux przesunięto przed Image AI na polecenie właściciela. PySide6/Qt6 jest
osobnym klientem HTTP/SSE istniejącego backendu, bez duplikowania inferencji.
Web i Image AI pozostają planowane. Android jest osobnym natywnym klientem tego samego API; zobacz [ANDROID.md](ANDROID.md).

## Uruchomienie ze źródeł

Linux x86_64, Python 3.12+, uv oraz działająca sesja X11/Wayland:

```sh
uv sync --frozen --extra desktop --group gui-test --group packaging
uv run --frozen omnicore-desktop
```

Qt6/PySide6-Essentials 6.8.3 jest opcjonalną zależnością. Sam backend nadal działa
przez `uv sync --frozen` i `uv run --frozen omnicore`, bez Qt i środowiska graficznego.
Dla gotowej paczki bez Pythona zobacz [APPIMAGE.md](APPIMAGE.md).

1. Otwórz **Ustawienia** i wskaż zaufany plik wykonywalny `llama-server`, jeśli
   korzystasz ze źródeł i nie masz go w PATH/OMNICORE_LLAMA_SERVER. AppImage może
   zawierać sprawdzony silnik CPU. Ollama pozostaje opcjonalna.
2. **Modele → Importuj GGUF** otwiera systemowy dialog plików. Dla nowego katalogu
   potwierdź rozszerzenie dozwolonych katalogów; restart dotyczy własnego backendu.
   Wagi pozostają na miejscu, symlinki są nadal odrzucane.
3. Zaznacz model, wybierz **Załaduj**. Sam import nie potwierdza kompatybilności;
   `load_verified` i `tested` oznaczają osobne etapy weryfikacji, nie rezydowanie w RAM.
4. **Czat AI → Nowa rozmowa**, wybierz model i wyślij wiadomość. Odpowiedź jest
   strumieniowana; można ją zatrzymać, skopiować i wrócić do historii po restarcie.
   Ollama ładuje swój model przy pierwszym żądaniu, dlatego ręczny Load dotyczy GGUF.
5. W zakładce **Hugging Face** wyszukaj repozytorium lub wpisz pełne `owner/repo`,
   pobierz listę GGUF, wybierz plik i potwierdź rozmiar/licencję. Pasek postępu,
   anulowanie i wznawianie używają trwałych zadań backendu. Po ukończeniu wybierz
   **Importuj pobrany GGUF**. Nie pobieramy wag przy starcie aplikacji.

## Ustawienia i dane

- Rozmowy, wiadomości, katalog modeli i zadania: `$XDG_DATA_HOME/omnicore`
  (domyślnie `~/.local/share/omnicore`), ewentualnie `OMNICORE_DATA_DIR`.
- Lokalna konfiguracja procesu i GUI: `$XDG_CONFIG_HOME/omnicore/desktop.json`
  (domyślnie `~/.config/omnicore/desktop.json`), zapisywana z trybem 0600.
- Preferencje języka/motywu są synchronizowane przez istniejące API ustawień.
  PL/EN i light/dark/system przełączają się w oknie; **Zapisz ustawienia** utrwala wybór.
- Parametry obejmują temperaturę, top-p/k, karę powtórzeń, kontekst, limit tokenów,
  seed, system prompt i pola urządzenia llama.cpp. GPU wymaga odpowiedniego silnika;
  paczka CPU nie deklaruje CUDA. Parametry obowiązują następne wiadomości.
- Zamknięcie okna zatrzymuje własny backend i jego silnik. Nie kasuje danych.
  `desktop.lock` zapobiega równoczesnemu otwarciu tego samego katalogu przez dwa GUI.

Skróty: **Ctrl+N** nowa rozmowa, **Ctrl+Enter** wyślij, **Esc** zatrzymaj,
**Ctrl+,** ustawienia. Nawigacja klawiaturą korzysta z natywnych widgetów Qt.
Komunikaty są prezentowane w oknie/pasku stanu, bez dodatkowego demona powiadomień.

## Bezpieczeństwo i istniejący backend

Na starcie klient sprawdza domyślny localhost:8000. Jeśli istnieje zgodny backend,
używa API i nie przejmuje procesu. Przy wymaganym tokenie ustaw bezpiecznie
`OMNICORE_DESKTOP_TOKEN` w środowisku procesu; GUI nie przechowuje go w JSON/logach.
Jawny `OMNICORE_DESKTOP_URL` wybiera istniejący serwer (lokalny HTTP lub zdalny HTTPS);
brak połączenia nie powoduje wtedy uruchamiania zastępczego lokalnego serwera.
Zdalny serwer wymaga własnej konfiguracji TLS/auth/Host po stronie administratora.

Gdy serwera nie ma, aplikacja tworzy prywatny backend na losowym porcie loopback,
z losowym tokenem przekazanym wyłącznie w środowisku dziecka. Nie wyłącza auth,
CORS ani walidacji ścieżek. QProcess i QtNetwork działają asynchronicznie; inferencję
wykonuje istniejący backend/silnik. Parent-death guard działa na Linux.
GUI zamyka tylko własne procesy. Zmiany silników/rootów zewnętrznego serwera są
odrzucane z instrukcją konfiguracji na hoście.

Diagnostyka pokazuje dostępność/wersje silników, GPU zgłoszone przez silnik, CPU,
RAM hosta i silnika, wolny dysk oraz stany/błędy ostatnich zadań. Brak danych GPU
pozostaje nieznany, nie jest szacunkiem. Log zawiera tylko dozwolone kody zdarzeń;
nie zapisuje promptów, tokenów i surowych odpowiedzi ani stderr silnika.

## Testy i ograniczenia

```sh
QT_QPA_PLATFORM=offscreen uv run --frozen pytest backend/tests desktop/tests -q
# Z rzeczywistym X11:
xvfb-run -a uv run --frozen pytest backend/tests desktop/tests -q
# Osobno, z istniejącymi wagami i silnikiem (bez automatycznych pobrań):
OMNICORE_TEST_LLAMA_SERVER=/absolute/llama-server OMNICORE_TEST_GGUF=/absolute/model.gguf \
  QT_QPA_PLATFORM=offscreen uv run --frozen pytest integration/test_desktop_real.py -q
```

Sprawdzono Linux CPU i X11/Xvfb. Fizyczne CachyOS/RTX 4060, CUDA i natywna sesja
Wayland nie są jeszcze potwierdzone. Rzeczywista Ollama nie była dostępna do testu.
Nie wszystkie GGUF i architektury są zgodne z wybranym silnikiem. Alpha nie ma
jeszcze edycji/generowania obrazów, załączników multimodalnych ani klienta Web. Android działa jako osobny klient API.
