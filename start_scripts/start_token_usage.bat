@echo off
TITLE Token Usage
cd C:\Users\jayge\Documents\AI\Gem-System-v2\extras
call C:\Users\jayge\miniconda3\Scripts\activate.bat
call conda activate mcp_env_2
call Python token_usage.py
cmd /k
