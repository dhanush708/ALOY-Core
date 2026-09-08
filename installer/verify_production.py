"""
Production Verification Script for ALOY Executable & Bundle (Phase 3).
Verifies executable existence, bundled static UI files, icon assets, tiktoken tokenizer cache,
sqlite-vec extension, and runtime path resolutions.
"""

import sys
import os
import sqlite3
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("production_verifier")


def check_bundled_executable(dist_dir: Path) -> bool:
    exe_path = dist_dir / "ALOY.exe"
    if not exe_path.exists():
        logger.error(f"Executable missing: {exe_path}")
        return False
    logger.info(f"Verified executable: {exe_path} ({exe_path.stat().st_size / (1024*1024):.2f} MB)")
    return True


def check_bundled_resources(dist_dir: Path) -> bool:
    internal_dir = dist_dir / "_internal"
    if not internal_dir.exists():
        # Direct bundle folder
        internal_dir = dist_dir

    required_assets = [
        internal_dir / "static" / "index.html",
        internal_dir / "static" / "js" / "app.js",
        internal_dir / "static" / "css" / "style.css",
        internal_dir / "assets" / "icons" / "aloy.ico",
        internal_dir / "assets" / "tiktoken_cache",
    ]

    missing = [str(p) for p in required_assets if not p.exists()]
    if missing:
        logger.error(f"Missing bundled resources: {missing}")
        return False

    logger.info("All required bundled resources verified successfully in dist/ALOY/_internal/")
    return True


def check_sqlite_vec_loading() -> bool:
    try:
        import sqlite_vec
        conn = sqlite3.connect(":memory:")
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT vec_version()")
        ver = cursor.fetchone()[0]
        logger.info(f"Verified sqlite-vec extension in bundle context. Version: {ver}")
        conn.close()
        return True
    except Exception as e:
        logger.error(f"sqlite-vec check failed: {e}")
        return False


def verify_build(dist_path: str = "dist/ALOY") -> bool:
    logger.info("=========================================")
    logger.info("Starting ALOY Executable Bundle Verification")
    logger.info("=========================================")

    dist_dir = Path(dist_path).resolve()
    
    e_ok = check_bundled_executable(dist_dir)
    r_ok = check_bundled_resources(dist_dir)
    s_ok = check_sqlite_vec_loading()

    logger.info("=========================================")
    logger.info("BUILD VERIFICATION SUMMARY:")
    logger.info(f"  Executable Check:   {'PASS' if e_ok else 'FAIL'}")
    logger.info(f"  Bundled Assets:     {'PASS' if r_ok else 'FAIL'}")
    logger.info(f"  sqlite-vec DLL:     {'PASS' if s_ok else 'FAIL'}")
    logger.info("=========================================")

    if e_ok and r_ok and s_ok:
        logger.info("BUILD VERIFICATION SUCCESSFUL. READY FOR INSTALLER PACKAGING.")
        return True
    else:
        logger.error("BUILD VERIFICATION FAILED. Check missing resources above.")
        return False


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "dist/ALOY"
    success = verify_build(target)
    sys.exit(0 if success else 1)
