import sys
import os
import sqlite3
import httpx
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("production_verifier")

def check_sqlite() -> bool:
    try:
        conn = sqlite3.connect(":memory:")
        cursor = conn.cursor()
        cursor.execute("SELECT sqlite_version()")
        ver = cursor.fetchone()[0]
        logger.info(f"SQLite loaded successfully. Version: {ver}")
        conn.close()
        return True
    except Exception as e:
        logger.error(f"SQLite check failed: {e}")
        return False

def check_sqlite_vec() -> bool:
    try:
        import sqlite_vec
        conn = sqlite3.connect(":memory:")
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        
        # Test vector extension
        cursor = conn.cursor()
        cursor.execute("SELECT vec_version()")
        ver = cursor.fetchone()[0]
        logger.info(f"sqlite-vec loaded successfully. Version: {ver}")
        
        # Test simple distance calculation
        cursor.execute("SELECT vec_distance_l2(?, ?)", (sqlite_vec.serialize_float32([1.0, 2.0]), sqlite_vec.serialize_float32([1.0, 3.0])))
        dist = cursor.fetchone()[0]
        logger.info(f"sqlite-vec distance calculation verified. L2 distance = {dist}")
        
        conn.close()
        return True
    except Exception as e:
        logger.error(f"sqlite-vec check failed: {e}")
        return False

async def check_ollama() -> bool:
    url = "http://localhost:11434/api/tags"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                logger.info(f"Ollama detected successfully. Available local models: {models}")
                return True
            else:
                logger.warning(f"Ollama returned status code {resp.status_code}")
                return False
    except Exception as e:
        logger.warning(f"Ollama server not reachable at http://localhost:11434. Ensure Ollama is running: {e}")
        return False

async def check_migrations() -> bool:
    # Set PYTHONPATH
    sys.path.insert(0, str(Path(__file__).parent.parent))
    try:
        from database.connection import DatabaseConnectionPool
        from database.migrator import Migrator
        
        db_path = "data/test_verify.db"
        if os.path.exists(db_path):
            os.remove(db_path)
            
        # Ensure data folder exists
        os.makedirs("data", exist_ok=True)
            
        db_pool = DatabaseConnectionPool(db_path)
        await db_pool.start()
        
        migrator = Migrator(db_pool)
        await migrator.migrate()
        logger.info("Database migrations successfully verified on clean DB state.")
        
        await db_pool.stop()
        if os.path.exists(db_path):
            os.remove(db_path)
        return True
    except Exception as e:
        logger.error(f"Database migration verification failed: {e}")
        return False

def check_first_run_files() -> bool:
    root = Path(__file__).parent.parent
    required_paths = [
        root / "config" / "default.yaml",
        root / "static" / "index.html",
        root / "static" / "js" / "app.js",
        root / "static" / "css" / "style.css",
    ]
    missing = []
    for p in required_paths:
        if not p.exists():
            missing.append(str(p))
            
    if missing:
        logger.error(f"Missing required distribution files: {missing}")
        return False
    else:
        logger.info("All required distribution files present and verified.")
        return True

async def main():
    logger.info("=========================================")
    logger.info("Starting ALOY Production Verification Suite")
    logger.info("=========================================")
    
    sq_ok = check_sqlite()
    sv_ok = check_sqlite_vec()
    ol_ok = await check_ollama()
    mg_ok = await check_migrations()
    fr_ok = check_first_run_files()
    
    logger.info("=========================================")
    logger.info("VERIFICATION SUMMARY:")
    logger.info(f"SQLite Loading:            {'PASS' if sq_ok else 'FAIL'}")
    logger.info(f"sqlite-vec Extension:      {'PASS' if sv_ok else 'FAIL'}")
    logger.info(f"Ollama Detection:          {'PASS' if ol_ok else 'WARNING (Ensure Ollama is running)'}")
    logger.info(f"Database Migrations:       {'PASS' if mg_ok else 'FAIL'}")
    logger.info(f"First-Run Assets:          {'PASS' if fr_ok else 'FAIL'}")
    logger.info("=========================================")
    
    if all([sq_ok, sv_ok, mg_ok, fr_ok]):
        logger.info("SYSTEM PRODUCTION READY FOR RELEASE.")
        sys.exit(0)
    else:
        logger.error("SYSTEM NOT READY FOR RELEASE. Please fix errors above.")
        sys.exit(1)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
