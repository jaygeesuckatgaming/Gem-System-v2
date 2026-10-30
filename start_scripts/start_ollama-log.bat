@echo off
TITLE Ollama Log Proxy
cd /d C:\Users\jayge\Documents\AI\ollama-log-proxy
call C:\Users\jayge\miniconda3\Scripts\activate.bat
set PYTHONUTF8=1
ollama-log-proxy --dashboard 8089 --metrics-port 9090
cmd /k
