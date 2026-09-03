@echo off
TITLE Pocket TTS
cd C:\Users\jayge\Documents\AI\Gem-System-v2\tts\pocket-tts
call C:\Users\jayge\miniconda3\Scripts\activate.bat
call conda activate mcp_env_2
call Python server.py
cmd /k
