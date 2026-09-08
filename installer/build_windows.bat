@echo off
REM ============================================================
REM  ALOY — Windows Automated Build & Installer Generator
REM  Produces: dist/ALOY/ (PyInstaller bundle)
REM            dist/installer/ALOY-Setup-1.0.0.exe (Inno Setup)
REM ============================================================

echo.
echo  ==========================================
echo   ALOY Windows Release Build System
echo   Version 1.0.0
echo  ==========================================
echo.

REM Step 1: Clean previous build artifacts
echo [1/4] Cleaning previous build artifacts...
if exist "build" rmdir /s /q "build"
if exist "dist\ALOY" rmdir /s /q "dist\ALOY"
if exist "dist\installer" rmdir /s /q "dist\installer"
echo       Done.

REM Step 2: Run PyInstaller Build
echo [2/4] Building standalone executable bundle with PyInstaller...
pyinstaller --noconfirm installer/aloy.spec
if %errorlevel% neq 0 (
    echo ERROR: PyInstaller build failed.
    exit /b 1
)
echo       Done. Executable ready at dist\ALOY\ALOY.exe

REM Step 3: Run Executable Bundle Verification
echo [3/4] Running production executable verification...
python installer/verify_production.py dist/ALOY
if %errorlevel% neq 0 (
    echo ERROR: Production verification failed.
    exit /b 1
)
echo       Done. Verification successful.

REM Step 4: Build Inno Setup installer
echo [4/4] Building Windows installer with Inno Setup (ISCC)...
set "ISCC_EXE=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist "%ISCC_EXE%" (
    set "ISCC_EXE=C:\Users\%USERNAME%\AppData\Local\Programs\Antigravity IDE\resources\app\node_modules\innosetup\bin\ISCC.exe"
)

if exist "%ISCC_EXE%" (
    "%ISCC_EXE%" "installer/aloy.iss"
    if %errorlevel% neq 0 (
        echo ERROR: Inno Setup build failed. Check installer/aloy.iss
        exit /b 1
    )
    echo       Done. Installer generated at dist\installer\ALOY-Setup-1.0.0.exe
) else (
    where ISCC.exe >nul 2>&1
    if %errorlevel% equ 0 (
        ISCC.exe "installer/aloy.iss"
        if %errorlevel% neq 0 (
            echo ERROR: Inno Setup build failed. Check installer/aloy.iss
            exit /b 1
        )
        echo       Done. Installer generated at dist\installer\ALOY-Setup-1.0.0.exe
    ) else (
        echo ERROR: ISCC.exe not found on system.
        exit /b 1
    )
)

echo.
echo  ==========================================
echo   BUILD COMPLETE & VERIFIED!
echo.
echo   Executable Bundle : dist\ALOY\ALOY.exe
echo   Windows Installer : dist\installer\ALOY-Setup-1.0.0.exe
echo  ==========================================
echo.
