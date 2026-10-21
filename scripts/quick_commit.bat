@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0.."

echo ========================================================
echo   LANDLOOM — QUICK GIT COMMIT & PUSH TO LAB
echo ========================================================
echo Current branch:
git branch --show-current
echo.

set "MSG=%~1"
if "%MSG%"=="" (
    set /p "MSG=Enter commit message (or press Enter for default): "
)
if "%MSG%"=="" (
    set "MSG=Update prompt templates and configuration"
)

echo.
echo [1/3] Staging changes...
git add app_parts/ modules/ scripts/ prompts/ tests/ app.py

echo [2/3] Committing with message: "%MSG%"...
git commit -m "%MSG%"

echo [3/3] Pushing to github/lab...
git push github lab

echo.
if %ERRORLEVEL% EQU 0 (
    echo ========================================================
    echo   SUCCESS: Changes successfully pushed to lab!
    echo ========================================================
) else (
    echo ========================================================
    echo   NOTICE: Git completed with status code %ERRORLEVEL%
    echo ========================================================
)
echo.
pause
