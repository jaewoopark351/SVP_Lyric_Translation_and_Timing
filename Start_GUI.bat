@echo off
setlocal EnableExtensions DisableDelayedExpansion
title SVP Lyric GUI
pushd "%~dp0"
if errorlevel 1 (
    echo [ERROR] Cannot open the project folder.
    pause
    exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Project Python was not found in .venv\Scripts\python.exe.
    echo Follow the virtual environment setup in README.md first.
    popd
    pause
    exit /b 1
)
if not exist "app.py" (
    echo [ERROR] app.py was not found. Keep this BAT in the project folder.
    popd
    pause
    exit /b 1
)
echo Starting SVP Lyric GUI...
echo Keep this window open while using the app.
echo To stop: press Ctrl+C in this window. Answer Y if prompted.
echo.
".venv\Scripts\python.exe" -u "app.py" %*
set "SVP_GUI_EXIT_CODE=%errorlevel%"
if not "%SVP_GUI_EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] The app exited with code %SVP_GUI_EXIT_CODE%.
    echo If the port is in use, close the existing app or use --port 28671.
    pause
)
popd
exit /b %SVP_GUI_EXIT_CODE%
