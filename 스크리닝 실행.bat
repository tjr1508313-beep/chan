@echo off
cd /d "%~dp0"
start cmd /k "streamlit run screening.py --server.port=8765"
timeout /t 8 /nobreak > nul
start http://localhost:8765
