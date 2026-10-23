@echo off
rem Projecute one-command start for Windows: double-click this file or run `run.bat`.
rem Creates a virtual environment, installs dependencies once, then starts the app
rem and opens it in your browser.
setlocal
cd /d "%~dp0"

rem 1. Check that Python is installed.
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.11 or newer from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during setup, then run this file again.
  pause
  exit /b 1
)

rem 2. Create the virtual environment the first time.
if not exist ".venv\Scripts\python.exe" (
  echo Creating a virtual environment...
  python -m venv .venv || goto :error
)

rem 3. Install dependencies once (a marker file remembers that it is done).
if not exist ".venv\.installed" (
  echo Installing dependencies. This happens once and takes a few minutes...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip || goto :error
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
  type nul > ".venv\.installed"
)

rem 4. Create .env from the example if it is missing.
if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo Created .env. Add a free Groq key there for live AI; without it the app runs in demo mode.
)

rem 5. Start the app; it opens the browser once the server is ready.
set OPEN_BROWSER=1
".venv\Scripts\python.exe" main.py
goto :eof

rem Shown if any setup step fails.
:error
echo.
echo Setup failed. See the messages above, or the Troubleshooting section in README.md.
pause
exit /b 1
