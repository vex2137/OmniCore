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

## Alpha.3 — rozmowy i diagnostyka

Dymki używają zapisanej nazwy modelu. Starsze wiadomości bez snapshotu pokazują
Asystent/Assistant. Markdown nie ładuje obrazów/plików z modelu; bloki kodu mają
osobne kopiowanie. Ctrl+F przeszukuje historię przez backend, Ctrl+Enter wysyła,
Escape zatrzymuje. Statystyki pokazują tylko dane raportowane przez silnik;
TTFT obejmuje ładowanie, ale nie kolejkę. Rozumowanie można rozwinąć oddzielnie.

Pierwszy ekran prowadzi do rzeczywistego importu GGUF i ustawień. Reconnect nie
uruchamia drugiego własnego backendu. Zamknięcie klienta współdzielonego backendu
odłącza podgląd, a jawny Stop anuluje zadanie. Prywatny backend aplikacji jest
zatrzymywany razem z jej procesami. Eksport raportu diagnostycznego zawiera tylko
zamknięty zestaw pól: bez tokenów, adresów, ścieżek, treści i surowych logów.
[CUDA i fallback CPU](CUDA.md) są konfigurowane bez zmian logiki inferencji w GUI.


## Backend lokalny i serwer dla telefonu

Zwykłe uruchomienie GUI nie wymaga terminala. Aplikacja sprawdza istniejący serwer,
a jeśli go nie ma, uruchamia własny backend z tokenem w pamięci na losowym porcie
loopback. Pasek pokazuje uruchamianie/połączono/rozłączono/błąd. Po awarii przycisk
**Uruchom backend** ponawia start. Zakończenie GUI zatrzymuje wyłącznie własny proces;
zewnętrzny serwer pozostaje uruchomiony.

Backend trzyma blokadę `backend.lock` w katalogu danych przez cały cykl życia
ASGI, przed inicjalizacją bazy i kolejki. Drugi proces z tą samą bazą odmawia startu.
GUI odczytuje wyłącznie lokalny port aktywnej blokady, nigdy token. Przy istniejącym
serwerze wymagającym uwierzytelniania podaj `OMNICORE_DESKTOP_TOKEN` w prywatnym
środowisku GUI. Dowolny inny serwer można wskazać przez `OMNICORE_DESKTOP_URL`;
zewnętrzny adres desktopu wymaga HTTPS. Błędny token nie powoduje startu duplikatu.
Nie usuwaj blokady działającego procesu. Nieaktywny plik jest ignorowany i ponownie
używany; nie zawiera sekretów. Bezpośredni Uvicorn wymaga zgodnego RuntimeConfig;
preferuj poniższy launcher CLI, który zna rzeczywisty host/port.

AppImage ma jawny tryb headless dla zaawansowanych użytkowników:

```bash
./OmniCore-0.1.0-rc.3-x86_64.AppImage --serve --host 127.0.0.1 --port 8000
```

Dane pozostają w dotychczasowym katalogu XDG. Jeśli GUI już używa tej bazy,
najpierw je zamknij. Dla telefonu właściciel świadomie konfiguruje środowisko
serwera (np. prywatny plik poza Git z prawami 0600):

- `OMNICORE_ALLOW_REMOTE=1`, `OMNICORE_HOST=0.0.0.0`, `OMNICORE_PORT=8000`;
- `OMNICORE_API_TOKEN`: własny losowy token ASCII alfanumeryczny, co najmniej 32 znaki;
- `OMNICORE_ALLOWED_HOSTS`: jawnie adres LAN komputera i loopback dla lokalnego GUI;
- `OMNICORE_MODEL_ROOTS`: dotychczasowe dozwolone katalogi GGUF;
- istniejący katalog danych i konfiguracja silnika; nie kopiuj ani nie resetuj bazy.

Nie umieszczaj tokenu w argv, logu, `.desktop`, repozytorium ani czacie. Nie dodawaj
wildcard Host/Origin/CORS. Natywny Android nie wymaga otwarcia CORS dla wszystkich
stron. Backend sam odmówi bindu zdalnego bez jawnej zgody i poprawnego tokenu.
Poza zaufaną siecią wymagany jest poprawnie skonfigurowany HTTPS/WSS z zaufanym
certyfikatem (np. lokalny reverse proxy). Nie wyłączaj walidacji TLS.

Aby zaawansowany serwer działał po zamknięciu terminala, właściciel może utworzyć
własny unit systemd --user z następującymi ustawieniami (ścieżki dostosuj lokalnie):

```ini
[Unit]
Description=OmniCore authenticated backend

[Service]
EnvironmentFile=%h/.config/omnicore/server.env
Environment=APPIMAGE_EXTRACT_AND_RUN=1
ExecStart=%h/Applications/OmniCore-0.1.0-rc.3-x86_64.AppImage --serve
Restart=on-failure
RestartSec=3
TimeoutStopSec=20
KillMode=control-group

[Install]
WantedBy=default.target
```

`server.env` zawiera wyłącznie świadomie wybraną konfigurację i musi być prywatny
(0600), poza repozytorium. Właściciel włącza/wyłącza usługę przez systemd --user;
OmniCore nie instaluje jej automatycznie i nie otwiera portów bez zgody. Nie podawaj
sekretów w zgłoszeniach błędów. Zewnętrzny backend nie jest zatrzymywany przez GUI.


Pod ograniczoną affinity lub widocznym limitem CPU cgroup v2 adapter ogranicza
pule wątków llama.cpp i wyłącza aktywne oczekiwanie (polling). Zapobiega to
zużywaniu budżetu CPU przez oczekujące pule podczas równoległych obciążeń.
Niższe ustawienia LLAMA_ARG_THREADS/BATCH są zachowane. Bez ograniczeń pozostaje
domyślny dobór silnika; dotyczy to również zwykłej instalacji CachyOS/CUDA.
Pomiary i ograniczenia obserwacji: benchmarks/rc3-cgroup-cpu.json.


## RC.4: Serwer i urządzenia

Otwórz **Serwer i urządzenia**. Własny backend uruchamia się domyślnie wraz z GUI;
można wyłączyć autostart i użyć przycisku uruchomienia. Zatrzymanie wymaga
potwierdzenia, anuluje aktywną generację i rozłącza klientów. Zamknięcie GUI nadal
zatrzymuje jego własny backend. Backend uruchomiony przez inną aplikację pozostaje
zewnętrzny: GUI może go używać, ale nie zatrzymuje i nie rekonfiguruje tego procesu.
Blokada katalogu danych nie jest usuwana, a drugi backend tej samej bazy jest odrzucany.

Aby połączyć telefon:

1. Połącz oba urządzenia z tą samą zaufaną siecią prywatną.
2. Włącz dostęp LAN i zapisz ustawienia. Aplikacja wykrywa prywatne adresy IPv4,
   ustawia hosty i port, zachowuje katalogi modeli oraz uruchamia ponownie swój backend.
3. Wybierz adres używany przez telefon i naciśnij **Sparuj telefon z Androidem**.
4. Zeskanuj QR w ustawieniach Androida i sprawdź adres komputera przed potwierdzeniem.

Kod QR wygasa po 120 sekundach, jest jednorazowy i można go anulować zamykając
okno. Utworzenie nowego kodu unieważnia poprzedni; restart unieważnia wszystkie
niewykorzystane kody. Kod nie zawiera głównego tokenu API. Telefon otrzymuje osobny
token; w sekcji urządzeń można cofnąć jego dostęp. Nowe żądania z odwołanym tokenem
są odrzucane; wcześniej otwarty strumień kończy się zgodnie z jego cyklem życia.
Każde sparowane urządzenie uzyskuje dostęp do wspólnego backendu i jego historii,
nie do osobnej przestrzeni kont użytkowników.

Główny token procesu jest zapisany w `server.token` w katalogu danych z prawami
0600; pliki symlink i tokeny czytelne dla innych użytkowników są odrzucane.
Konfiguracja GUI nie zawiera tokenu. W SQLite zapisane są wyłącznie hashe kodów
parowania i tokenów urządzeń. Brak tokenu, obcy Host/Origin i publiczny adres
źródłowy są odrzucane. LAN używa HTTP w świadomie zaufanej sieci — bez szyfrowania.
Nie przekierowuj portu przez router. Dla niezaufanej sieci zachowaj HTTPS/reverse
proxy i ręczną konfigurację połączenia. GUI nie zmienia zapory ani sterowników;
przy braku połączenia sprawdź wspólną sieć i regułę zapory dla wybranego portu.

W ustawieniach generowania wybierz zakres: **Bieżąca rozmowa** lub **Domyślne dla
nowych rozmów**. Zapis bieżącej rozmowy trafia do backendu; inne urządzenie odczytuje
go po odświeżeniu. Wysyłanie nie zastępuje zapisanych parametrów rozmowy domyślnymi.
Auto/CUDA korzystają z dotychczasowego wykrywania silników, wyboru pliku CUDA,
warstw GPU i potwierdzonego offloadu. Nie instaluje się CUDA ani sterowników.

**Automatycznie generuj nazwy rozmów** jest wspólnym ustawieniem backendu,
domyślnie włączonym. Po pierwszej odpowiedzi istniejący model tworzy krótki tytuł
w tle (maksymalnie 32 tokeny). Nowa odpowiedź ma pierwszeństwo i anuluje trwające
tworzenie tytułu. Błąd, anulowanie, brak modelu i restart nie powodują ponawiania
na każdej wiadomości; tytuł można nadać ręcznie. Istniejące i ręcznie nazwane
rozmowy nie są automatycznie nadpisywane.

**Usuń wszystkie rozmowy** pobiera aktualną liczbę rozmów i wymaga potwierdzenia
nieodwracalnej operacji. Backend anuluje aktywne generowanie oraz usuwa rozmowy,
wiadomości, zadania generacji i klucze ich żądań. Modele, pobrane pliki, ustawienia
oraz parowania pozostają. Zmiana liczby rozmów przez inny klient wymaga ponownego
potwierdzenia. Klienci odświeżają wspólną historię również podczas zwykłej pracy.


## RC.5: tokeny, parowanie i panel historii

W **Serwer i urządzenia → Tokeny i dostęp API** utwórz nazwany token (domyślnie
30 dni, 0 oznacza bezterminowy). Pełna wartość jest widoczna tylko teraz; skopiuj
ją do ustawień Androida wraz z adresem wyświetlanym przez serwer. Schowek jest
czyszczony po 45 sekundach, jeżeli jego zawartość się nie zmieniła. Lista pokazuje
zakresy, daty utworzenia/ostatniego użycia/wygaśnięcia. Odwołanie wszystkich wymaga
potwierdzenia i obejmuje również sparowane telefony; główny token jest zachowany.
Administracja tokenami wymaga głównego tokenu i połączenia lokalnego.

QR jest ważny 120 sekund według serwera. Okno blokuje równoległe otwieranie,
pokazuje status, pozwala utworzyć nowy QR i sprawdza zgodność adresu z aktualnym
nasłuchem/allowlist. Po zmianie adresu sieci wykonaj restart backendu z GUI.
Nowy kod nie upoważnia do ponownego wydawania wielu tokenów z jednego kodu.

Przeciągnij prawą krawędź historii (200–520 px) albo użyj przycisku zwijania w
czacie. Szerokość i zwinięcie są trwałe. Długie nazwy mają wielokropek i tooltip.
Limit automatycznych nazw (20–80 znaków, domyślnie 42, do 5 słów) zmienisz w
ustawieniach historii; nie przepisuje starych nazw ani ręcznych tytułów.
[Dostawcy AI](EXTERNAL_AI.md).
