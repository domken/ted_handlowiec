# Instrukcje projektu

Przed zmianą zapoznaj się z `PROJECT_MEMORY.md` i `README.md`. Po każdej istotnej zmianie aktualizuj pamięć projektu i README, jeśli zmienił się sposób działania lub uruchamiania.

## Zakres

TED Handlowiec to lokalna aplikacja dla handlowca do wyszukiwania ogłoszeń TED, selekcji postępowań i eksportu metryczek do Excela. Główne środowisko pracy to macOS; wersja Windows jest budowana jako jednoplikowe EXE skryptem `Zbuduj_na_Windows.bat`.

## Zasady pracy

- Zachowuj prosty interfejs dla użytkownika bez wiedzy technicznej.
- Przed zmianą istniejącego zachowania sprawdź aktualny kod i zachowaj dotychczasowe wymagania produktu.
- Aplikacja używa biblioteki standardowej Pythona; nie dodawaj zależności bez uzasadnienia.
- Przy zmianach API TED pilnuj składni expert query. Sortowanie API jest osobnym elementem payloadu (`sortColumn`, `sortOrder`), a nie częścią filtra.
- Wyszukiwanie CPV obsługuje listę kodów i prefiksy z `*`; bieżące wartości domyślne to `72*` i `48*`.
- Nie dodawaj do repozytorium lokalnej bazy użytkownika, eksportowanych metryczek ani danych poufnych.
- Wprowadzaj commity dla logicznie zakończonych zmian z krótkim polskim lub angielskim opisem.
- Nie uruchamiaj testów automatycznych bez prośby użytkownika. Dla zmian kodu można sprawdzić składnię i wykonać wąską kontrolę statyczną.
