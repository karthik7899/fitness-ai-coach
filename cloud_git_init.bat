@echo off
title Aura // Cloud Git Initializer
echo ===================================================
echo Aura // Git Initializer & GitHub Pusher
echo ===================================================
echo.

where git >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Git is not found on your system.
    echo Please download and install Git from: https://git-scm.com/
    echo Once installed, reopen this command prompt and run this script again.
    pause
    exit /b 1
)

echo [1/3] Initializing local Git repository...
git init

echo.
echo [2/3] Committing files locally...
git add .
git commit -m "First commit: Deploying Aura to the Cloud"

echo.
echo ---------------------------------------------------
echo Create a PRIVATE repository on https://github.com/
echo and paste the URL here.
echo ---------------------------------------------------
set /p REPO_URL="Enter private GitHub Repository URL: "

if "%REPO_URL%"=="" (
    echo [INFO] No URL entered. Git initialized locally, but not pushed.
    pause
    exit /b 0
)

echo.
echo [3/3] Setting branch and pushing to remote...
git remote remove origin >nul 2>nul
git remote add origin %REPO_URL%
git branch -M main
git push -u origin main

if %errorlevel% == 0 (
    echo.
    echo ===================================================
    echo [SUCCESS] Code pushed successfully to your GitHub!
    echo ===================================================
) else (
    echo.
    echo [ERROR] Failed to push code to remote. 
    echo Ensure the repository URL is correct and you have push permissions.
)
pause
