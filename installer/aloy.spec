# -*- mode: python ; coding: utf-8 -*-
# ALOY — PyInstaller Spec File
# Run: pyinstaller --noconfirm installer/aloy.spec

import os

block_cipher = None

# All Python packages to include
import sqlite_vec
sqlite_vec_dir = os.path.dirname(sqlite_vec.__file__)

added_files = [
    # Frontend SPA
    ('../static', 'static'),
    # Database migrations (SQL files)
    ('../database/migrations', 'database/migrations'),
    # Configuration
    ('../config', 'config'),
    # Application icon
    ('../assets', 'assets'),
    # Documentation
    ('../docs', 'docs'),
    # License
    ('../LICENSE', '.'),
    ('../README.md', '.'),
    # sqlite-vec DLL extension
    (os.path.join(sqlite_vec_dir, 'vec0.dll'), 'sqlite_vec'),
]

hidden_imports = [
    # FastAPI & ASGI
    'fastapi', 'uvicorn', 'uvicorn.main', 'uvicorn.config',
    'uvicorn.lifespan.on', 'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.websockets.websockets_impl',
    'starlette', 'starlette.middleware', 'starlette.staticfiles',
    # Pydantic
    'pydantic', 'pydantic_settings',
    # Async
    'asyncio', 'aiofiles', 'aiohttp', 'websockets',
    # Data
    'sqlite3', 'json', 'yaml',
    # Network
    'httpx', 'httpx._transports.default',
    # System
    'psutil', 'psutil._pswindows',
    # SSE
    'sse_starlette',
    # Tokenizer + encoding registry (MUST include tiktoken_ext to register encodings)
    'tiktoken', 'tiktoken_ext', 'tiktoken_ext.openai_public',
    # SQLite extension
    'sqlite_vec',
    # App modules
    'api', 'api.server', 'api.routes',
    'models', 'models.config', 'models.router', 'models.ollama_client',
    'memory', 'memory.manager',
    'identity', 'identity.engine', 'identity.metadata',
    'kernel', 'kernel.boot', 'kernel.event_bus',
    'database', 'database.connection', 'database.migrator',
    'agent', 'agent.runtime',
    'conversation', 'conversation.engine',
    'knowledge', 'learning', 'reasoning',
    'security', 'security.confirmation',
    'evolution', 'evolution.service',
    'tools', 'tools.registry', 'tools.system',
    'project',
]

a = Analysis(
    ['../run.py'],
    pathex=['.'],
    binaries=[],
    datas=added_files,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'scipy', 'PIL'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ALOY',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # No terminal window — pure GUI app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='../assets/icons/aloy.ico',  # Windows taskbar/shortcut icon
    version='version_info.txt',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ALOY',
)
