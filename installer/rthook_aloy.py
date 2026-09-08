# PyInstaller Runtime Hook for ALOY Application
import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        meipass_path = Path(meipass)
        os.environ["TIKTOKEN_CACHE_DIR"] = str(meipass_path / "assets" / "tiktoken_cache")
        os.environ["ALOY_BUNDLE_DIR"] = str(meipass_path)
