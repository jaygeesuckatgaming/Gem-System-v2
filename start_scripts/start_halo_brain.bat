@echo off
TITLE Gem Halo Brain (LLM commander)
set PYTHONUTF8=1
set HALO_BRAIN_MODEL=gemma3:4b-it-qat
cd C:\Users\jayge\Documents\AI\Gem-System-v2
call C:\Users\jayge\miniconda3\Scripts\activate.bat
call conda activate mcp_env_2
call python halo_brain.py
cmd /k
