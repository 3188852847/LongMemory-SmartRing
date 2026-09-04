@echo off
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
  echo Project Python environment not found. See docs/guides.
  pause
  exit /b 1
)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0scripts\development\launcher\app.py"
