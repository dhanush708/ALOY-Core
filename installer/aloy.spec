# -*- mode: python ; coding: utf-8 -*-
# ALOY — Production PyInstaller Spec File (Phase 3 Specification)
# Build command: pyinstaller --noconfirm installer/aloy.spec

import os
import sys
from PyInstaller.utils.hooks import copy_metadata

block_cipher = None

# Root directory of the repository
ROOT_DIR = os.path.abspath(os.path.join(SPECPATH, '..'))

# sqlite-vec DLL extension lookup
import sqlite_vec
sqlite_vec_dir = os.path.dirname(sqlite_vec.__file__)
sqlite_vec_dll = os.path.join(sqlite_vec_dir, 'vec0.dll')

# Bundled data files (Source Path, Target Directory in _MEIPASS)
added_files = [
    (os.path.join(ROOT_DIR, 'static'), 'static'),
    (os.path.join(ROOT_DIR, 'config'), 'config'),
    (os.path.join(ROOT_DIR, 'assets'), 'assets'),
    (os.path.join(ROOT_DIR, 'database', 'migrations'), 'database/migrations'),
    (os.path.join(ROOT_DIR, 'docs'), 'docs'),
    (os.path.join(ROOT_DIR, 'LICENSE'), '.'),
    (os.path.join(ROOT_DIR, 'README.md'), '.'),
]

if os.path.exists(sqlite_vec_dll):
    added_files.append((sqlite_vec_dll, 'sqlite_vec'))

added_files += copy_metadata('email-validator')
added_files += copy_metadata('pydantic')

# Complete production hidden imports list
hidden_imports = [
    # FastAPI & ASGI Web Engine
    'fastapi', 'uvicorn', 'uvicorn.main', 'uvicorn.config',
    'uvicorn.lifespan.on', 'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.websockets.websockets_impl',
    'starlette', 'starlette.middleware', 'starlette.staticfiles',
    # Pydantic & Validation
    'pydantic', 'pydantic_settings', 'email_validator',
    # Async & Networking
    'asyncio', 'aiofiles', 'aiohttp', 'websockets', 'httpx', 'httpx._transports.default',
    # SQLite & Vector Search
    'sqlite3', 'sqlite_vec', 'json', 'yaml',
    # System & Telemetry
    'psutil', 'psutil._pswindows', 'sse_starlette',
    # Tokenizer & Token Encoding Engine
    'tiktoken', 'tiktoken_ext', 'tiktoken_ext.openai_public',
    # ALOY Application Core Packages
    'kernel', 'kernel.path_manager', 'kernel.boot', 'kernel.event_bus', 'kernel.telemetry', 'kernel.prompts',
    'api', 'api.server', 'api.routes', 'api.schemas',
    'models', 'models.config', 'models.router', 'models.ollama_client',
    'memory', 'memory.manager',
    'identity', 'identity.engine', 'identity.profile', 'identity.integrity',
    'database', 'database.connection', 'database.migrator',
    'agent', 'agent.runtime',
    'conversation', 'conversation.engine', 'conversation.pipeline', 'conversation.context_builder',
    'knowledge', 'knowledge.v2', 'knowledge.v2.models', 'knowledge.v2.interfaces',
    'knowledge.v2.providers.registry', 'knowledge.v2.providers.duckduckgo',
    'knowledge.v2.retrieval_layer', 'knowledge.v2.relevance_engine',
    'knowledge.v2.context_assembler', 'knowledge.v2.decision_engine',
    'knowledge.v2.query_planner', 'knowledge.v2.search_pipeline', 'knowledge.v2.integration',
    'learning', 'reasoning',
    'security', 'security.confirmation',
    'evolution', 'evolution.service',
    'tools', 'tools.registry', 'tools.system',
    'project',
]

a = Analysis(
    [os.path.join(ROOT_DIR, 'run.py')],
    pathex=[ROOT_DIR],
    binaries=[],
    datas=added_files,
    hiddenimports=hidden_imports,
    hookspath=[os.path.join(SPECPATH, 'hooks')],
    hooksconfig={},
    runtime_hooks=[os.path.join(SPECPATH, 'rthook_aloy.py')],
    excludes=[
        'tkinter', '_tkinter',
        'pygame', 'pygame._sdl2',
        'torch', 'torchvision', 'torchaudio',
        'tensorflow', 'keras',
        'transformers', 'onnxruntime', 'onnx',
        'numpy', 'scipy', 'sklearn', 'pandas', 'matplotlib',
        'spacy', 'nltk', 'PIL', 'cv2',
        'boto3', 'botocore', 'google.cloud',
        'pytest', 'pytest_asyncio',
    ],
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
    console=False,  # Windowed desktop application (no console)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.abspath(os.path.join(ROOT_DIR, 'assets', 'icons', 'aloy.ico')),
    version=os.path.join(SPECPATH, 'version_info.txt'),
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
