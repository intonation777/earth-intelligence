@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python Launcher was not found. Install Python 3.11 from https://www.python.org/downloads/windows/
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  py -3.11 -m venv .venv
  if errorlevel 1 goto error
)
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 goto error
if not exist ".env" copy ".env.example" ".env" >nul
python manage.py check
if errorlevel 1 goto error
python manage.py migrate
if errorlevel 1 goto error
echo.
echo Starting NASA Unified Observatory at http://127.0.0.1:8000/
python manage.py runserver 127.0.0.1:8000
pause
exit /b 0
:error
echo.
echo Setup failed. Read the error above and the README.md troubleshooting notes.
pause
exit /b 1
