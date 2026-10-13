@echo off
setlocal
for %%I in ("%~dp0..\..\..") do set "PROJECT_ROOT=%%~fI"
if not exist "%PROJECT_ROOT%\.venv\Scripts\pythonw.exe" (
  echo Project Python environment not found. See docs/guides.
  pause
  exit /b 1
)
start "" "%PROJECT_ROOT%\.venv\Scripts\pythonw.exe" "%PROJECT_ROOT%\scripts\development\launcher\app.py"
