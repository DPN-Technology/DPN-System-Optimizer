@echo off
setlocal
cd /d "%~dp0"
title DPN Technology - System Optimizer v2.0
where py >nul 2>&1
if not errorlevel 1 goto use_py
where python >nul 2>&1
if not errorlevel 1 goto use_python
echo Python 3.10 or newer was not found.
echo Download: https://www.python.org/downloads/windows/
pause
exit /b 1
:use_py
py -3 "%~dp0dpn_system_optimizer.py" gui
if errorlevel 1 goto launch_error
exit /b 0
:use_python
python "%~dp0dpn_system_optimizer.py" gui
if errorlevel 1 goto launch_error
exit /b 0
:launch_error
echo.
echo The application could not launch. Check the error above.
pause
exit /b 1
