# Pamięć projektu TED Handlowiec

## Cel

Prosta aplikacja desktopowa uruchamiana lokalnie w przeglądarce. Handlowiec wyszukuje postępowania w TED, przegląda opisy, zapisuje wybory i generuje osobne metryczki XLSX dla wybranych ogłoszeń. Metryczki można zapisywać w katalogu synchronizowanym przez OneDrive/SharePoint.

## Bieżący stan

- Aplikacja i serwer HTTP są w `app.py`; interfejs HTML/CSS/JS jest osadzony w tym pliku.
- Start na macOS: `Uruchom_na_Mac.command`.
- Wyszukiwanie korzysta z publicznego TED Search API v3.
- Wyniki oraz wybory użytkownika są przechowywane w SQLite w `~/Library/Application Support/TED Handlowiec`.
- Szablon eksportu to `ogloszenia_TED_uslugi_IT_szablon.xlsx`, przechowywany obok `app.py`.
- Nie są wymagane dodatkowe biblioteki Pythona.

## Ustalenia produktu i techniczne

- Domyślny CPV to prefiksy `72*` (usługi informatyczne) i `48*` (oprogramowanie i systemy informatyczne). Można wpisać kilka kodów rozdzielonych przecinkami, średnikami lub spacjami; `*` oznacza początek kodu i wyszukuje całą gałąź. Puste pole wyłącza filtr.
- Pozostałe domyślne filtry: najnowsze wydanie TED, kupujący z UE i Polska.
- Sortowanie jest przekazywane w `sortColumn` i `sortOrder`, poza ciągiem `query`.
- Metryczka zachowuje układ szablonu i zapisuje dane w osobnych arkuszach.
- Eksport tworzy w wybranym katalogu bazowym podkatalog `YYYYMMDD` według lokalnej daty generowania; wszystkie metryczki eksportowane tego samego dnia trafiają do tego katalogu.
- Aplikacja jest obecnie jednoosobowa i lokalna; zapisane wybory nie synchronizują się między komputerami.
- Wersja Windows jest pakowana do jednoplikowego EXE przez PyInstaller na runnerze Windows; PyInstaller nie jest cross-kompilatorem.
- Preferowany CI to `.github/workflows/windows-build.yml`, który buduje po pushu do `main` albo ręcznie i udostępnia artefakt na 30 dni. Projekt ma zdalne repozytorium Gitea; do uruchomienia tego workflow potrzebne jest też prywatne repo GitHub.
- `.gitea/workflows/windows-build.yml` pozostaje alternatywą wymagającą włączonych Gitea Actions i własnego runnera z etykietą `windows-latest`.
- Wdrożenie serwerowe jest odłożone na później.

## Następne obszary pracy

- Doprecyzować zestaw CPV dla usług informatycznych i powiązanych na podstawie zakresu działalności użytkownika.
- Rozwijać i weryfikować wyszukiwanie względem interfejsu TED oraz realnych wyników API.
- Sprawdzić gotowe EXE na Windows i dopracować instrukcje pierwszego uruchomienia.
