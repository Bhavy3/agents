@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "LLAMA_SERVER=%FRIDAY_LLAMA_SERVER%"
if not defined LLAMA_SERVER set "LLAMA_SERVER=C:\AI\llama.cpp\llama-server.exe"
set "LLAMA_MODEL=%FRIDAY_LLM_MODEL_PATH%"
if not defined LLAMA_MODEL set "LLAMA_MODEL=C:\AI\models\qwen2.5-3b-instruct-q5_k_m.gguf"
set "LLAMA_GPU_LAYERS=%FRIDAY_LLM_GPU_LAYERS%"
if not defined LLAMA_GPU_LAYERS set "LLAMA_GPU_LAYERS=33"

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: .venv is missing. Create it with: py -3.12 -m venv .venv
    exit /b 1
)

curl.exe --silent --fail --max-time 2 http://127.0.0.1:8080/v1/models >nul 2>&1
if errorlevel 1 (
    if not exist "%LLAMA_SERVER%" (
        echo ERROR: llama-server.exe was not found: "%LLAMA_SERVER%"
        exit /b 1
    )
    if not exist "%LLAMA_MODEL%" (
        echo ERROR: GGUF model was not found: "%LLAMA_MODEL%"
        exit /b 1
    )
    echo Starting local llama.cpp server...
    start "FRIDAY llama.cpp" /b "%LLAMA_SERVER%" -m "%LLAMA_MODEL%" -c 4096 --host 127.0.0.1 --port 8080 -ngl "%LLAMA_GPU_LAYERS%"
    for /L %%N in (1,1,30) do (
        curl.exe --silent --fail --max-time 2 http://127.0.0.1:8080/v1/models >nul 2>&1
        if not errorlevel 1 goto LLM_READY
        timeout /t 1 /nobreak >nul
    )
    echo ERROR: llama.cpp did not become ready within 30 seconds.
    exit /b 1
)

:LLM_READY
echo Local LLM is ready. Starting FRIDAY...
".venv\Scripts\python.exe" main.py %*
exit /b %ERRORLEVEL%
