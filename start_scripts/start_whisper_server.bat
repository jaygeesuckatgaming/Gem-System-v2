@echo off
TITLE Whisper STT
cd C:\Users\jayge\Documents\AI\Gem-System-v2
call C:\Users\jayge\miniconda3\Scripts\activate.bat
call conda activate mcp_env_2
python clients\whisper_server.py
cmd /k
