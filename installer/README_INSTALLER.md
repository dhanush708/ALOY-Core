# ALOY Packaging Guide

This document explains how to build ALOY into a distributable desktop application for Windows.

---

## Prerequisites

| Tool | Version | Download |
|------|---------|----------|
| Python | 3.11+ | https://python.org |
| PyInstaller | Latest | `pip install pyinstaller` |
| Inno Setup | 6+ | https://jrsoftware.org/isinfo.php |
| Pillow (for icon) | Latest | `pip install pillow` |

---

## One-Command Build (Windows)

```bat
installer\build_windows.bat
```

This script:
1. Cleans previous build artifacts
2. Installs Python dependencies
3. Converts `assets/icons/aloy.png` → `aloy.ico`
4. Runs PyInstaller to create `dist/ALOY/`
5. Runs Inno Setup to create `dist/installer/ALOY-Setup-1.0.0.exe`

---

## Manual Steps

### Step 1: Build with PyInstaller

```bash
pyinstaller --noconfirm installer/aloy.spec
```

Output: `dist/ALOY/ALOY.exe` — a self-contained portable bundle.

### Step 2: Create Windows Installer

Install Inno Setup from https://jrsoftware.org/isinfo.php, then:

```bash
ISCC.exe installer/aloy.iss
```

Output: `dist/installer/ALOY-Setup-1.0.0.exe`

---

## Portable ZIP

To distribute a portable version (no installer required):

```powershell
Compress-Archive -Path "dist\ALOY\*" -DestinationPath "dist\ALOY-1.0.0-portable-win64.zip"
```

---

## Output Files

| File | Description |
|------|-------------|
| `dist/ALOY/ALOY.exe` | Portable executable (run anywhere) |
| `dist/installer/ALOY-Setup-1.0.0.exe` | Windows installer with shortcuts and uninstaller |
| `dist/ALOY-1.0.0-portable-win64.zip` | Portable ZIP for distribution |

---

## Notes

- The application bundles its own Python runtime — users do NOT need Python installed.
- Users DO need **Ollama** running locally. The app will guide them if it's missing.
- The first launch will auto-create the SQLite database and apply all migrations.
- Total installer size: approximately 150–300 MB (includes Python runtime + all deps).

---

## Code Signing (Optional)

To sign the EXE for Windows SmartScreen trust:

1. Obtain a code signing certificate
2. Uncomment `SignTool` lines in `installer/aloy.iss`
3. Run: `signtool sign /a /td sha256 /fd sha256 dist\installer\ALOY-Setup-1.0.0.exe`

---

## macOS / Linux

The same codebase runs on macOS and Linux via direct Python execution:

```bash
pip install -r requirements.txt
python run.py
```

Platform-specific packaging (`.dmg`, `.AppImage`) can be added in a future release.
