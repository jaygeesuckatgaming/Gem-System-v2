@echo off
TITLE Qwen3-TTS
set PYTHONUTF8=1
cd C:\Users\jayge\Documents\AI\Gem-System-v2\tts\Qwen3-TTS
call C:\Users\jayge\miniconda3\Scripts\activate.bat
call conda activate qwen3-tts_312
call python server.py
cmd /k
