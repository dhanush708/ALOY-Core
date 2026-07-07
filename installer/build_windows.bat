@echo off
REM ============================================================
REM  ALOY — Windows Build Script
REM  Produces: dist/ALOY/ (PyInstaller bundle)
REM            dist/installer/ALOY-Setup-1.0.0.exe (Inno Setup)
REM
REM  Prerequisites:
REM    pip install pyinstaller
REM    Inno Setup 6+ installed from https://jrsoftware.org/isinfo.php
REM ============================================================

echo.
echo  ==========================================
echo   ALOY Build System — Windows Release
echo   Version 1.0.0
echo  ==========================================
echo.

REM Step 1: Clean previous build artifacts
echo [1/5] Cleaning previous build artifacts...
if exist "build" rmdir /s /q "build"
if exist "dist\ALOY" rmdir /s /q "dist\ALOY"
echo       Done.

REM Step 2: Install / verify dependencies
echo [2/5] Verifying Python dependencies...
pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo ERROR: pip install failed. Ensure Python 3.11+ is on PATH.
    pause
    exit /b 1
)
echo       Done.

REM Step 3: Convert PNG icon to ICO (requires Pillow)
echo [3/5] Converting icon PNG to ICO format...
pip install pillow --quiet
python -c "from PIL import Image; img = Image.open('assets/icons/aloy.png'); img.save('assets/icons/aloy.ico', format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)]); print('  Icon converted successfully.')"
if %errorlevel% neq 0 (
    echo WARNING: Icon conversion failed. Continuing without .ico file.
)

REM Step 4: Run PyInstaller
echo [4/5] Building application with PyInstaller...
pyinstaller --noconfirm installer/aloy.spec
if %errorlevel% neq 0 (
    echo ERROR: PyInstaller build failed.
    pause
    exit /b 1
)
echo       Done. Output: dist\ALOY\

REM Step 5: Build Inno Setup installer (if ISCC is available)
echo [5/5] Building Windows installer with Inno Setup...
set "ISCC_PATH=%LOCALAPPDATA%\Programs\Antigravity IDE\resources\app\node_modules\innosetup\bin\ISCC.exe"
if exist "%ISCC_PATH%" (
    "%ISCC_PATH%" "installer/aloy.iss"
    if %errorlevel% neq 0 (
        echo WARNING: Inno Setup build failed. Check installer/aloy.iss
    ) else (
        echo       Done. Output: dist\installer\ALOY-Setup-1.0.0.exe
    )
) else (
    where ISCC.exe >nul 2>&1
    if %errorlevel% equ 0 (
        ISCC.exe "installer/aloy.iss"
        if %errorlevel% neq 0 (
            echo WARNING: Inno Setup build failed. Check installer/aloy.iss
        ) else (
            echo       Done. Output: dist\installer\ALOY-Setup-1.0.0.exe
        )
    ) else (
        echo WARNING: ISCC.exe not found. Skipping installer creation.
        echo          Download Inno Setup from https://jrsoftware.org/isinfo.php
        echo          Then re-run this script to generate the .exe installer.
    )
)

echo.
echo  ==========================================
echo   Build complete!
echo.
echo   Portable bundle : dist\ALOY\ALOY.exe
echo   Installer       : dist\installer\ALOY-Setup-1.0.0.exe
echo  ==========================================
echo.
pause
