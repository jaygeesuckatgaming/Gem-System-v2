@echo off
TITLE Cognee
cd C:\Users\jayge\Documents\AI\Gem-System-v2\cognee
call C:\Users\jayge\miniconda3\Scripts\activate.bat
call conda activate cognee
call Python cognee_server.py
cmd /k
