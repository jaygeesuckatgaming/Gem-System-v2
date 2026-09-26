@echo off
TITLE Laya Fast-Lane
set PYTHONUTF8=1
cd C:\Users\jayge\Documents\AI\Gem-System-v2
call C:\Users\jayge\miniconda3\Scripts\activate.bat
call conda activate laya
call Python -u clients\laya_server.py
cmd /k
