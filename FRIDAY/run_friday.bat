@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Python virtual environment not found at "%CD%\.venv".
    echo Create it with: py -3.12 -m venv .venv
    echo Then install requirements with: .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

if not exist "requirements.txt" (
    echo ERROR: requirements.txt is missing from "%CD%".
    pause
    exit /b 1
)

echo Checking local LLM backend...
curl.exe --silent --fail --max-time 2 http://127.0.0.1:8080/v1/models >nul 2>&1
if errorlevel 1 (
    echo Local LLM is not running. Launching with start_friday_local.bat...
    call "%~dp0start_friday_local.bat"
    set "EXIT_CODE=%ERRORLEVEL%"
    pause
    exit /b %EXIT_CODE%
)

echo Starting FRIDAY from "%CD%"...
".venv\Scripts\python.exe" main.py
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" echo FRIDAY exited with code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
