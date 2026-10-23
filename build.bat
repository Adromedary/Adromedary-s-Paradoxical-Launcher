@echo off
setlocal
cd /d "%~dp0"
echo === Adromedary's Paradoxical Launcher 2.0: building the .exe ===
python --version >nul 2>&1
if errorlevel 1 (
  echo Python was not found. Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
  pause
  exit /b 1
)
python -m pip install --upgrade pip
python -m pip install --upgrade -r requirements.txt pyinstaller
if errorlevel 1 goto :fail

rem The 'verify you are human' check window. Optional: if it can't install on your Python version,
rem the app still works, it just skips sites that show that check.
python -m pip install --upgrade pywebview
if errorlevel 1 (
  echo.
  echo NOTE: pywebview could not be installed. Building without the check window.
  echo.
)

if not exist icon.ico (
  echo icon.ico is missing: it must sit next to build.bat.
  goto :fail
)
python -m PyInstaller --noconfirm --clean --onefile --windowed --name ParadoxicalLauncher --icon icon.ico ^
  --add-data "icon.ico;." --collect-all customtkinter --collect-all curl_cffi --collect-all webview --collect-data certifi ^
  paradoxical_launcher.py
if errorlevel 1 goto :fail
echo.
echo Done. Your app: %~dp0dist\ParadoxicalLauncher.exe
echo Put it in a folder of its own: it keeps its settings and downloads next to itself.
pause
exit /b 0
:fail
echo.
echo Build failed - see the messages above.
pause
exit /b 1
