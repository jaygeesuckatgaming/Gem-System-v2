@echo off
TITLE m8 TTS Adapter (StyleTTS2)
cd C:\Users\jayge\Documents\AI\Gem-System-v2
call C:\Users\jayge\miniconda3\Scripts\activate.bat
call conda activate mcp_env_2
python clients\m8_styletts2_adapter.py
cmd /k
