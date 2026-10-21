@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Nie znaleziono Python Launcher for Windows.
  echo Zainstaluj Python 3.10 lub nowszy i ponownie uruchom ten plik.
  pause
  exit /b 1
)

if not exist ".venv-winbuild\Scripts\python.exe" (
  py -3 -m venv .venv-winbuild
  if errorlevel 1 goto :failed
)

call ".venv-winbuild\Scripts\python.exe" -m pip install --upgrade pip pyinstaller
if errorlevel 1 goto :failed

call ".venv-winbuild\Scripts\python.exe" -m PyInstaller --clean --noconfirm --onefile --name TEDHandlowiec --add-data "ogloszenia_TED_uslugi_IT_szablon.xlsx;." app.py
if errorlevel 1 goto :failed

echo.
echo Gotowe. Aplikacja znajduje sie w:
echo %CD%\dist\TEDHandlowiec.exe
echo Skopiuj plik EXE do folderu, w ktorym ma byc uzywany.
pause
exit /b 0

:failed
echo.
echo Budowanie aplikacji nie powiodlo sie. Sprawdz komunikaty powyzej.
pause
exit /b 1
