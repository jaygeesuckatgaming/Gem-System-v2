@echo off
TITLE Gem Drive
set PYTHONUTF8=1
cd C:\Users\jayge\Documents\AI\Gem-System-v2
call C:\Users\jayge\miniconda3\Scripts\activate.bat
call conda activate drive_game
call python -m drive_game
cmd /k
