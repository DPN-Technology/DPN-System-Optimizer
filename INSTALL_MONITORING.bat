@echo off
setlocal
title DPN System Optimizer - Optional Monitoring Support
where py >nul 2>&1
if %ERRORLEVEL% EQU 0 (
  py -3 -m pip install --user -r "%~dp0requirements.txt"
) else (
  python -m pip install --user -r "%~dp0requirements.txt"
)
echo.
echo Restart DPN System Optimizer after installation.
pause
