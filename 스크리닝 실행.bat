@echo off
cd /d "%~dp0"
start cmd /k "streamlit run screening.py"
timeout /t 8 /nobreak > nul
start http://localhost:8501
