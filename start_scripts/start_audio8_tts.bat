@echo off
TITLE Audio8-TTS
cd C:\Users\jayge\Documents\AI\Gem-System-v2\tts\Audio8_TTS
call C:\Users\jayge\miniconda3\Scripts\activate.bat
call conda activate audio8_tts
call python server.py
cmd /k
