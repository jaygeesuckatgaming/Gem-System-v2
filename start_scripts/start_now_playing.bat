@echo off
TITLE Now Playing
cd C:\Users\jayge\Documents\AI\Gem-System-v2\extras
call C:\Users\jayge\miniconda3\Scripts\activate.bat
call conda activate mcp_env_2
call Python now_playing.py
cmd /k
