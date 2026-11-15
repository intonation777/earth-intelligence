@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo Run run_windows.bat once first.
 pause
 exit /b 1
)
call ".venv\Scripts\activate.bat"
pip install -r requirements-geospatial.txt
pause
