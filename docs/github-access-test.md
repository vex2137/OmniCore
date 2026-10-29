# GitHub access test

Ten plik służy do sprawdzenia odczytu i zapisu repozytorium
`vex2137/OmniCore` z połączonego środowiska Codex.

- Data testu: 2026-10-28.
- Gałąź testowa: `test/omnicore-github-access`.
- Bazowy commit `main`: `0f91a3e9a7ba28cac3324238248e1fda75fdb174`.
- Odczyt: `git ls-remote --exit-code origin refs/heads/main` zakończył się powodzeniem.
- Zapis: wymaga commita tego pliku, pushu gałęzi i porównania SHA lokalnego ze zdalnym.

Samo istnienie tego pliku nie potwierdza uprawnień do zapisu. Wynik testu
i zweryfikowany SHA są zapisane w [PROGRESS.md](PROGRESS.md) po udanym pushu.
Test nie wymaga zapisywania tokenów ani innych sekretów w repozytorium.
