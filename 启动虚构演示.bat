@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
if exist "runtime\python.exe" (
  set "PYTHONPATH=%~dp0packages"
  "runtime\python.exe" launch.py --demo %*
  goto finished
)
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" launch.py --demo %*
  goto finished
)
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 launch.py --demo %*
) else (
  python launch.py --demo %*
)
:finished
pause
