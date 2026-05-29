@echo off
title Aura // Fitness AI Coach Launcher
echo ===================================================
echo Aura // Fitness AI Coach Launcher
echo ===================================================

REM 1. Check if streamlit is already in PATH
where streamlit >nul 2>nul
if %errorlevel% == 0 (
    echo Starting Aura Fitness AI Coach...
    streamlit run app.py
    goto end
)

REM 2. Look in AppData Roaming (standard --user path for pip)
for /d %%d in ("%APPDATA%\Python\Python*") do (
    if exist "%%d\Scripts\streamlit.exe" (
        echo Found Streamlit in %%d\Scripts
        set "PATH=%%d\Scripts;%PATH%"
        echo Starting Aura Fitness AI Coach...
        streamlit run app.py
        goto end
    )
)

REM 3. Look in AppData Local (sometimes Python installs scripts here)
for /d %%d in ("%LOCALAPPDATA%\Programs\Python\Python*") do (
    if exist "%%d\Scripts\streamlit.exe" (
        echo Found Streamlit in %%d\Scripts
        set "PATH=%%d\Scripts;%PATH%"
        echo Starting Aura Fitness AI Coach...
        streamlit run app.py
        goto end
    )
)

echo [ERROR] Could not find streamlit.exe in your PATH or AppData folders.
echo Make sure you ran 'pip install --user -r requirements.txt' successfully.
pause

:end
