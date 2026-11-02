@echo off
setlocal
title Skin Studio launcher
if not exist "%~dp0runtime\python.exe" (
  echo Please extract the entire ZIP before opening Skin Studio.
  pause
  exit /b 1
)
if not exist "%~dp0app\outputs\EvrimaSkinEditor\skin_editor.py" (
  echo Skin Studio files are missing. Please extract the entire ZIP again.
  pause
  exit /b 1
)
echo Opening Skin Studio. Keep this window open while Studio is running.
"%~dp0runtime\python.exe" -I -B -X utf8 "%~dp0launch.py" %*
if errorlevel 1 (
  echo.
  echo Skin Studio could not start. The error above can help identify the problem.
  echo Startup details may also be in %%LOCALAPPDATA%%\EvrimaSkinStudio\startup-error.txt
  pause
  exit /b 1
)
