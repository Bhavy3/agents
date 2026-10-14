@echo off
setlocal

set "LLAMA_SERVER=%FRIDAY_LLAMA_SERVER%"
if not defined LLAMA_SERVER set "LLAMA_SERVER=C:\AI\llama.cpp\llama-server.exe"
set "LLAMA_MODEL=%FRIDAY_LLM_MODEL_PATH%"
if not defined LLAMA_MODEL set "LLAMA_MODEL=C:\AI\models\qwen2.5-3b-instruct-q5_k_m.gguf"
set "LLAMA_CONTEXT=%FRIDAY_LLM_CONTEXT%"
if not defined LLAMA_CONTEXT set "LLAMA_CONTEXT=4096"
set "LLAMA_GPU_LAYERS=%FRIDAY_LLM_GPU_LAYERS%"
if not defined LLAMA_GPU_LAYERS set "LLAMA_GPU_LAYERS=33"

if not exist "%LLAMA_SERVER%" (
    echo ERROR: llama-server.exe was not found: "%LLAMA_SERVER%"
    echo Set FRIDAY_LLAMA_SERVER to the correct executable path.
    exit /b 1
)
if not exist "%LLAMA_MODEL%" (
    echo ERROR: GGUF model was not found: "%LLAMA_MODEL%"
    echo Set FRIDAY_LLM_MODEL_PATH to the correct model path.
    exit /b 1
)

echo Starting llama-server on 127.0.0.1:8080 with %LLAMA_GPU_LAYERS% GPU layers...
"%LLAMA_SERVER%" -m "%LLAMA_MODEL%" -c "%LLAMA_CONTEXT%" --host 127.0.0.1 --port 8080 -ngl "%LLAMA_GPU_LAYERS%"
set "EXIT_CODE=%ERRORLEVEL%"
pause
exit /b %EXIT_CODE%
