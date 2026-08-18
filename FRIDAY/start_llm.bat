@echo off
echo Starting llama-server with full GPU offload (-ngl 999)...
"D:\AI\llama.cpp\llama-server.exe" -m "D:\AI\models\qwen2.5-3b-instruct-q5_k_m.gguf" -c 4096 --host 127.0.0.1 --port 8080 -ngl 999
pause
