@echo off
TITLE VibeVoice TTS
set PYTHONUTF8=1
cd C:\Users\jayge\Documents\AI\Gem-System-v2\tts\VibeVoice
call C:\Users\jayge\miniconda3\Scripts\activate.bat
call conda activate vibevoice
call python postapp.py --port 13000
cmd /k
