@echo off
cd /d "%~dp0"
set STREAMLIT=C:\Users\seokchan\AppData\Local\Programs\Python\Python313\Scripts\streamlit.exe
start cmd /k "%STREAMLIT% run screening.py --server.port=8765"
timeout /t 8 /nobreak > nul
start http://localhost:8765
