@echo off
title Aura // Register Auto Sync Scheduler
echo =======================================================
echo Aura Fitness AI Coach Auto-Sync Task Installer
echo =======================================================
echo.
echo This utility will register a Windows Scheduled Task to run
echo the fitness sync automatically every 2 hours in the background.
echo.
echo If it fails, please right-click this file and select
echo "Run as administrator".
echo.
echo Press any key to install...
pause >nul
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0register_task.ps1"
echo.
echo Press any key to exit...
pause >nul
