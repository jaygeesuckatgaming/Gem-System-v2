@echo off
TITLE Audio Listener
cd C:\Users\jayge\Documents\AI\Gem-System-v2
call C:\Users\jayge\miniconda3\Scripts\activate.bat
call conda activate mcp_env_2
python clients\listen.py
cmd /k
