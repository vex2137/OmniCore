# Linux desktop — plan implementacji

GUI Linux zostało decyzją właściciela przesunięte przed Etap 3 Image AI.
Punkt wejścia: feature/0.1.0-alpha `59cb2df56b50d2121856b97ddfa5e1c872737177`;
main `0f91a3e9a7ba28cac3324238248e1fda75fdb174`, 14 commitów do przeniesienia.
Bazowa regresja: 115 PASS. Nie przepisujemy backendu.

## Etapy

1. Natywny klient, konfiguracja i lifecycle własnego uwierzytelnionego backendu.
2. Działające widoki rozmów, modeli, pobierania, ustawień i diagnostyki; PL/EN,
   motywy, skróty, asynchroniczne REST i streaming, testy Qt/integracji.
3. Pomiary operacji Python i decyzja Rust bez atrap komponentów.
4. Powtarzalny AppImage x86_64 z Python/Qt/backendem i, jeśli sprawdzony, CPU llama.cpp;
   rzeczywisty start AppImage, checksum, workflow i dokumentacja.
5. Pełna walidacja, PR jeśli dostępny, integracja main bez force push i bez
   omijania ochrony; draft release z załącznikami, bez publikacji publicznej.

## Granice

GUI wywołuje istniejące API; nie implementuje inferencji, parsera GGUF ani
pobierania wag. Sieć i kontrola procesów działają poza głównym wątkiem Qt.
Konfiguracja procesu jest lokalna i prywatna, oddzielona od preferencji backendu.
Zewnętrzny backend nie jest zatrzymywany ani rekonfigurowany przez GUI.

W chmurze API GitHub jest blokowane (403); potrzebne api.github.com i uploads.github.com
zapisano do szkicu. HF pozostaje zablokowane. Nie oznaczać prawdziwej inferencji
ani wysłania artefaktów jako PASS, jeśli nie zostały wykonane.
