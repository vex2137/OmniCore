# RC.5 — Dostawcy AI / Zewnętrzne API

Linux: **Ustawienia → Dostawcy AI / Zewnętrzne API**. Android ma tę samą sekcję
ustawień. Dodaj konfigurację OpenAI, Anthropic, Gemini, OpenRouter lub własnego
endpointu OpenAI, zapisz klucz, sprawdź połączenie, pobierz modele albo wpisz ID.
Test połączenia pobiera katalog, nie generuje płatnej odpowiedzi. Niektóre klucze
ograniczone do generowania nie mają uprawnień do katalogu; wtedy użyj ręcznego ID.
Nie ma listy identyfikatorów modeli wpisanej na stałe.

Dodanie modelu wymaga potwierdzenia kosztów i wysyłania treści. Model pojawia się
w zwykłym wyborze modeli z oznaczeniem płatnego API. Dopiero jego **świadomy wybór**
uruchamia zewnętrzny czat; awaria lokalnego silnika nigdy nie przełącza na API.
Przełączanie modeli nie wymaga restartu. Historia, streaming, Stop i automatyczny
tytuł używają istniejącej kolejki generowania. Automatyczny tytuł to dodatkowa,
krótka generacja tym samym modelem; można ją wyłączyć w ustawieniach historii.
W statystykach widnieje dostawca/model i zużycie zgłoszone przez API, bez fikcyjnego
GPU lub limitu kontekstu. Parametry GPU lokalnej rozmowy pozostają zachowane.

## Sekrety i miejsce wykonywania

Żądania do firm wykonuje **backend Linux**, także przy korzystaniu z Androida.
Klucze są przechowywane wyłącznie w systemowym Secret Service (np. GNOME Keyring
lub KWallet udostępniający Secret Service); SQLite zawiera tylko odwołanie.
Nie ma awaryjnego zapisu klucza w JSON. Jeśli magazyn nie działa lub jest zamknięty,
aplikacja pokaże błąd; odblokuj go w sesji desktopowej i ponów operację.
Serwer uruchomiony poza sesją desktopową musi mieć dostęp do jej D-Bus/magazynu.
AppImage zawiera bibliotekę klienta magazynu, nie instaluje systemowego demona.

Zdalne wpisanie klucza wymaga HTTPS. Przy zwykłym HTTP LAN skonfiguruj klucz
na komputerze; telefon korzysta z zapisanej konfiguracji bez pobierania klucza.
Token OmniCore w telefonie pozostaje szyfrowany przez Android Keystore. Uprawnienie
`providers` pozwala zarządzać konfiguracją; token `chat` pozwala korzystać z już
udostępnionych modeli. Administrator powinien udostępniać dostęp do płatnych modeli
wyłącznie zaufanym klientom. Wymagana jest autoryzacja backendu.

Każdy dostawca ma właściwy format autoryzacji, żądań, SSE i usage. OpenAI używa
Chat Completions, Anthropic Messages, Gemini GenerateContent, OpenRouter i własny
endpoint formatu OpenAI. Parametry próbkowania są opcjonalne, ponieważ nie każdy
model je obsługuje. Ograniczenia modelu i odpowiedzi 401/403/429/5xx są jawne;
nie ma cichego fallbacku ani automatycznego ponawiania płatnej generacji.

Własny endpoint wymaga publicznego HTTPS bez danych logowania, query i fragmentu;
przekierowania są wyłączone, TLS weryfikowany. Walidacja odrzuca literalne prywatne
adresy i nazwy lokalne; nie jest izolacją sieciową DNS. Konfiguruj wyłącznie
zaufany endpoint. Usunięcie konfiguracji usuwa jej modele z katalogu i klucz
z magazynu (przy chwilowym błędzie magazynu usunięcie sekretu jest ponawiane).
Historia rozmów pozostaje dostępna.

Kontrolowane testy nie zastępują próby z własnym kluczem i aktualnie dostępnym
modelem. W Cloud nie wykonywano płatnych wywołań ani nie używano kluczy właściciela.
