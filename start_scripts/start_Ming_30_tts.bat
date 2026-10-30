@echo off
TITLE Ming-3.0-tts
cd C:\Users\jayge\Documents\AI\Gem-System-v2\tts\Ming-3.0-tts
call C:\Users\jayge\miniconda3\Scripts\activate.bat
call conda activate Ming-3.0-tts
set PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
call python server.py
cmd /k
