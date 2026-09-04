@echo off
TITLE System Viz
cd C:\Users\jayge\Documents\AI\Gem-System-v2\extras
call C:\Users\jayge\miniconda3\Scripts\activate.bat
call conda activate mcp_env_2
call Python gpu_viz.py
cmd /k
