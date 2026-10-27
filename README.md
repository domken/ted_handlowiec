# TED — narzędzie dla handlowca (prototyp macOS)

Prototyp lokalnej aplikacji do przeglądania ogłoszeń z TED, zapisywania wyborów i eksportu metryczek Excel.

## Uruchomienie

1. Otwórz folder ted_handlowiec.
2. Kliknij dwukrotnie Uruchom_na_Mac.command.
3. Aplikacja otworzy się w domyślnej przeglądarce.
4. Aby zamknąć aplikację, wróć do Terminala i naciśnij Ctrl+C.

Aplikacja nie wymaga dodatkowych bibliotek Pythona. Wymaga Pythona 3.10 lub nowszego i połączenia z internetem dla wyszukiwania TED. Dane i zaznaczenia zapisują się lokalnie w ~/Library/Application Support/TED Handlowiec.

Jeśli macOS zablokuje uruchomienie pliku .command, kliknij go prawym przyciskiem i wybierz Otwórz.

## Wersja Windows

Preferowany build działa przez GitHub Actions: workflow `.github/workflows/windows-build.yml` buduje EXE na runnerze Windows po każdym pushu do `main` oraz na żądanie. W repozytorium GitHub otwórz **Actions**, wybierz **Build Windows app**, uruchom workflow lub otwórz ostatni udany run i pobierz artefakt `TEDHandlowiec-Windows`. Artefakt jest przechowywany przez 30 dni.

Alternatywnie `Zbuduj_na_Windows.bat` buduje `dist\TEDHandlowiec.exe` na lokalnym komputerze Windows z Pythonem 3.10+ i dostępem do internetu. Gotowy EXE nie wymaga Pythona; zamyka się przez zamknięcie okna konsoli uruchomionego razem z aplikacją. Workflow Gitea `.gitea/workflows/windows-build.yml` wymaga włączonych Gitea Actions i dostępnego runnera Windows z etykietą `windows-latest`.

## Obsługa

- Domyślnie wybrane są najnowsze wydanie TED, gałęzie CPV 72* (usługi IT) i 48* (oprogramowanie i systemy informatyczne) oraz kraje zamawiającego UE i Polska. Filtr CPV przyjmuje wiele kodów oddzielonych przecinkami; gwiazdka szuka całej gałęzi, np. `7226*`. Puste pole wyłącza filtr.
- Wyszukiwarka ma filtry podobne do TED: zakres (najnowsze wydanie, aktywne lub archiwum), słowa w ogłoszeniu, CPV, kraj zamawiającego, miejsce realizacji, typ ogłoszenia, daty publikacji, sortowanie i liczbę wyników na stronie. Typ można ograniczyć do ogłoszeń o zamówieniu, wynikach lub zmianach; aplikacja filtruje API TED po kodach `notice-type`.
- W wynikach wybierz Wczytaj pełny opis, aby pobrać XML tylko dla oglądanego ogłoszenia.
- Wybór, status i notatka zapisują się lokalnie i pozostają po zamknięciu aplikacji.
- Eksport wypełnia sześć arkuszy skoroszytu `ogloszenia_TED_uslugi_IT_szablon.xlsx`: listę, dane postępowania, zamawiającego, części, kryteria i wyniki. Zachowuje układ, tabele i formatowanie szablonu. W aplikacji wybierz folder bazowy; metryczki zapisują się w jego podfolderze z datą generowania w formacie `YYYYMMDD` (np. `20261021`). Ogłoszenia z tego samego dnia trafiają do tego samego podfolderu.
- Jako folder zapisu można wskazać lokalny folder biblioteki SharePoint synchronizowany przez OneDrive. Aplikacja zapamiętuje wybór na tym komputerze.
- Pola, których nie ma w XML danego ogłoszenia, pozostają puste. Dane o częściach, kryteriach i wynikach są zapisywane w osobnych wierszach.
- Przed przygotowaniem oferty potwierdź termin i dokumentację w TED.

## Ograniczenia prototypu

- Wyszukiwanie opiera się na TED Search API v3 i pobiera maksymalnie 250 wyników na stronę.
- Plik `ogloszenia_TED_uslugi_IT_szablon.xlsx` musi znajdować się obok `app.py` (również przy późniejszym pakowaniu aplikacji do EXE).
- Aplikacja jest lokalna dla jednego użytkownika. Zapisane wybory nie synchronizują się między komputerami.
- Nie jest podpisana certyfikatem Apple; przy pierwszym uruchomieniu macOS może pokazać ostrzeżenie.
- Późniejsze wydanie Windows będzie osobno spakowane jako EXE.
