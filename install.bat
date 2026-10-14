@echo off
title QBZ-Rip - Dependency Installer
cd /d "%~dp0"
echo ===================================================
echo      Installing Dependencies for QBZ-Rip
echo ===================================================
echo.

:: 1. Check for Python Launcher (py)
where py >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [OK] Menggunakan Python Launcher (py)...
    py -m pip install --upgrade pip
    py -m pip install -r requirements.txt
    goto success
)

:: 2. Check for python command
where python >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [OK] Menggunakan Python...
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    goto success
)

:: 3. Python is not installed or not in PATH
echo ===================================================
echo [ERROR] Python tidak terdeteksi di PC ini!
echo ===================================================
echo.
echo Penyebab:
echo 1. Python belum terinstall, ATAU
echo 2. Saat install, opsi "Add python.exe to PATH" lupa dicentang.
echo.
echo Solusi:
echo 1. Download Python di https://www.python.org/downloads/
echo 2. Buka installer, dan PASTIKAN CENTANG:
echo    [x] "Add python.exe to PATH" (di bagian bawah installer)
echo 3. Selesaikan install, lalu klik lagi install.bat ini.
echo.
pause
exit /b 1

:success
echo.
echo ===================================================
echo   Semua dependencies berhasil terinstall!
echo   Sekarang kamu bisa klik dua kali 'run.bat'
echo ===================================================
echo.
pause
