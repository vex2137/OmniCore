# OmniCore — instrukcje dla agentów

## Tożsamość projektu

- Nazwa: **OmniCore**.
- Typ: **open-source local AI platform** — platforma lokalnej sztucznej inteligencji.
- Aktualna wersja rozwojowa: **0.1.0 Alpha** (publiczne Alpha.1 i Alpha.2; kolejne publikacje wymagają zgody właściciela).
- Platformy: Linux, Web, Android. Przyszła platforma: Windows.
- Języki interfejsu: polski i angielski (PL/EN).
- Interfejs: jasny i ciemny motyw oraz automatyczne wykrywanie motywu systemowego.
- Pierwsza wersja obejmuje modele tekstowe i obrazowe. Dalszy zakres opisuje roadmapa.

## Początek każdej sesji i nowego zadania

1. Przeczytaj ten plik, [docs/ROADMAP.md](docs/ROADMAP.md)
   i [docs/PROGRESS.md](docs/PROGRESS.md).
2. Sprawdź gałąź, remote, status Git i istniejący kod. Zachowaj cudze zmiany.
3. Porównaj dokumentację z rzeczywistym stanem kodu i dostępnymi wynikami testów.
4. Kontynuuj od ostatniego potwierdzonego etapu. Zapis w dokumentacji sam w sobie
   nie dowodzi wykonania funkcji ani testu.
5. Korzystaj z istniejącego checkoutu w izolowanym środowisku chmurowym;
   nie twórz dodatkowego Git worktree, chyba że właściciel o to poprosi.

## Zasady pracy

- Nie przebudowuj działających modułów bez uzasadnienia.
- Nie usuwaj funkcji bez zgody właściciela.
- Nie przedstawiaj atrap funkcjonalności jako ukończonych funkcji.
- Dziel duże zadania na mniejsze etapy z weryfikowalnymi wynikami.
- Uruchamiaj odpowiednie testy po zmianach. Brak testów zgłaszaj jawnie;
  sprawdzenie dokumentacji nie zastępuje testów aplikacji.
- Dokumentuj ograniczenia i znane błędy.
- Aktualizuj PROGRESS.md po ukończeniu istotnego etapu.
- Aktualizuj ROADMAP.md, kiedy zmienia się plan.
- Nie publikuj publicznych wydań bez zgody właściciela.
- Nie umieszczaj sekretów, tokenów ani wag modeli w repozytorium.
  Nie używaj tokenów znalezionych w plikach projektu; korzystaj z autoryzacji
  dostarczonej przez środowisko i bezpiecznych ustawień sekretów.

## Zasady Git

- Pracuj na gałęziach funkcjonalnych i twórz czytelne commity.
- Nie wykonuj force push bez wyraźnej zgody.
- Nie nadpisuj cudzych zmian.
- Przed raportowaniem sprawdź status Git.
- Po push zweryfikuj zdalny commit, np. przez `git ls-remote`, i porównaj SHA.
- Jeśli push nie działa, zgłoś problem zamiast twierdzić, że zmiany opublikowano.
  W bieżącym zadaniu właściciel zezwala kontynuować lokalne GUI i commity
  mimo niedostępności GitHuba; przed integracją ponowić test dostępu.

## Zakończenie większego zadania

1. Uruchom właściwe testy i sprawdź błędy oraz diff.
2. Zaktualizuj PROGRESS.md i, jeśli plan się zmienił, ROADMAP.md.
3. Zapisz zmiany w commicie.
4. Wykonaj push, jeśli środowisko na to pozwala i mieści się to w zakresie zadania.
5. Zweryfikuj zdalny stan Git i przedstaw raport: zakres, testy, ograniczenia,
   lokalny/zdalny SHA oraz stan publikacji i PR, jeśli dotyczy.

## Definicja ukończenia zadania

Zadanie można oznaczyć jako ukończone dopiero po implementacji wymaganego zakresu,
uruchomieniu właściwych testów, sprawdzeniu błędów, aktualizacji dokumentacji,
zapisaniu commita i potwierdzeniu publikacji zmian, jeśli była wymagana.
W zadaniu dokumentacyjnym implementacją jest kompletna dokumentacja, a walidacja
obejmuje strukturę, treść i odnośniki; nie potwierdza działania produktu.

W PROGRESS.md podawaj wyłącznie zaobserwowane wyniki i prawdziwe SHA.
Pola SHA zapisane w dokumencie oznaczają konkretny zweryfikowany punkt kontrolny:
commit dokumentujący tę weryfikację może być późniejszy. Bieżący HEAD i stan
zdalny sprawdzaj poleceniami Git; nie próbuj wpisać hasha commita do niego samego.

## Bieżąca granica prac

Bieżące zadanie przesuwa natywne GUI Linux przed Image AI: klient PySide6/Qt6,
istniejący backend, AppImage, testy, integracja main po weryfikacji i szkic wydania.
Nie publikuj publicznego release bez osobnego potwierdzenia. Nie omijaj ochrony gałęzi.
Bieżące rozszerzenie zadania obejmuje natywnego Androida Kotlin/Compose jako klienta API.
Nie implementuj teraz Image AI, Web GUI ani lokalnej inferencji Android. Rust wymaga pomiarów
i mierzalnej potrzeby; bez pustych crate'ów lub przepisywania backendu.
Nie deklaruj działania inferencji, klientów ani zgodności modeli na podstawie
samych interfejsów adapterów lub testów bez rzeczywistego silnika.
