@echo off
setlocal EnableDelayedExpansion
title CLI Engage Roster Manager — Setup and Launch

REM ═══════════════════════════════════════════════════════════
REM  SKYWARD → CLI ENGAGE  |  Windows Launcher
REM  Double-click this file to set up and run the importer.
REM  You only need to do setup once; after that it launches
REM  directly to the main menu.
REM ═══════════════════════════════════════════════════════════

echo.
echo  ══════════════════════════════════════════════════════
echo   Skyward ^> CLI Engage Roster Manager  —  Launcher
echo  ══════════════════════════════════════════════════════
echo.

REM ── Locate this script's folder so we can find the .py file ──────────────────
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "PY_SCRIPT=%SCRIPT_DIR%\skyward_to_cliengage.py"

if not exist "%PY_SCRIPT%" (
    echo  [ERROR] Cannot find skyward_to_cliengage.py
    echo          Make sure LAUNCH_WINDOWS.bat and skyward_to_cliengage.py
    echo          are in the same folder.
    echo.
    pause
    exit /b 1
)

REM ── Check if Python is already available ─────────────────────────────────────
set "PYTHON_CMD="
for %%C in (python python3 py) do (
    if "!PYTHON_CMD!"=="" (
        %%C --version >nul 2>&1
        if !errorlevel!==0 set "PYTHON_CMD=%%C"
    )
)

if not "!PYTHON_CMD!"=="" goto :check_pandas

REM ── Python not found — try to install via winget (Windows 10/11) ─────────────
echo  [INFO] Python is not installed on this computer.
echo         The script will now attempt to install it automatically.
echo         This requires an internet connection and may take a minute or two.
echo.
echo         If you see a User Account Control (UAC) prompt, click Yes.
echo.

winget --version >nul 2>&1
if !errorlevel! neq 0 goto :manual_python

echo  [INFO] Installing Python via Windows Package Manager (winget)...
winget install --id Python.Python.3.12 --source winget --accept-package-agreements --accept-source-agreements --silent
if !errorlevel! neq 0 goto :manual_python

REM Refresh PATH so the new Python is visible in this session
for /f "tokens=*" %%P in ('where python 2^>nul') do set "PYTHON_CMD=%%P"
if "!PYTHON_CMD!"=="" (
    REM winget may have installed to a user path not yet in PATH; try py launcher
    py --version >nul 2>&1
    if !errorlevel!==0 set "PYTHON_CMD=py"
)

if "!PYTHON_CMD!"=="" goto :manual_python

echo.
echo  [OK] Python installed successfully.
goto :check_pandas

:manual_python
echo.
echo  ══════════════════════════════════════════════════════
echo   MANUAL PYTHON INSTALLATION REQUIRED
echo  ══════════════════════════════════════════════════════
echo.
echo   The automatic install did not work on this computer.
echo   Please follow these steps:
echo.
echo   1. Open your web browser and go to:
echo         https://www.python.org/downloads/
echo.
echo   2. Click the big yellow "Download Python" button.
echo.
echo   3. Run the installer.  IMPORTANT:
echo      Check the box that says "Add Python to PATH"
echo      before clicking Install Now.
echo.
echo   4. After installation finishes, close this window
echo      and double-click LAUNCH_WINDOWS.bat again.
echo.
start https://www.python.org/downloads/
pause
exit /b 1

REM ── Check / install pandas ────────────────────────────────────────────────────
:check_pandas
echo  [INFO] Checking for required Python libraries...
!PYTHON_CMD! -c "import pandas" >nul 2>&1
if !errorlevel!==0 (
    echo  [OK]   pandas is already installed.
    goto :launch
)

echo  [INFO] Installing pandas (this takes about 30 seconds)...
!PYTHON_CMD! -m pip install --upgrade pip --quiet
!PYTHON_CMD! -m pip install pandas --quiet
if !errorlevel! neq 0 (
    echo.
    echo  [ERROR] Could not install pandas automatically.
    echo          Please run this command in a Command Prompt and try again:
    echo.
    echo              pip install pandas
    echo.
    pause
    exit /b 1
)
echo  [OK]   pandas installed successfully.

REM ── Launch the main script ────────────────────────────────────────────────────
:launch
echo.
echo  [INFO] Starting Skyward to CLI Engage Roster Manager...
echo.
cd /d "%SCRIPT_DIR%"
!PYTHON_CMD! "%PY_SCRIPT%" %*

REM Keep the window open if the script exits with an error
if !errorlevel! neq 0 (
    echo.
    echo  [ERROR] The script exited with an error (code !errorlevel!).
    echo          Review the messages above for details.
    pause
)
endlocal
