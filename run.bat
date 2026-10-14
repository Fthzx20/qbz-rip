@echo off
title QBZ-Rip
cd /d "%~dp0"

where py >nul 2>&1
if %ERRORLEVEL% equ 0 (
    py -B main.py
    goto end
)

where python >nul 2>&1
if %ERRORLEVEL% equ 0 (
    python -B main.py
    goto end
)

echo [ERROR] Python tidak ditemukan!
echo Silakan jalankan 'install.bat' terlebih dahulu.
pause
:end
