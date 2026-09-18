@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" launch.py --demo
  goto finished
)
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 launch.py --demo
) else (
  python launch.py --demo
)
:finished
pause
