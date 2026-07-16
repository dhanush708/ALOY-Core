import sys
import os
import sqlite3
import socket
import traceback
from pathlib import Path

# Try to import required packages and log results
def check_imports():
    results = {}
    packages = [
        ("fastapi", "FastAPI web framework"),
        ("uvicorn", "ASGI server"),
        ("pydantic", "Data validation"),
        ("yaml", "PyYAML config parser"),
        ("sqlite_vec", "sqlite-vec vector search wrapper"),
        ("sse_starlette", "Server-Sent Events helper"),
        ("tiktoken", "BPE tokenizer"),
        ("psutil", "System process manager"),
        ("aiofiles", "Asynchronous file I/O"),
        ("aiohttp", "Asynchronous HTTP client/server"),
        ("websockets", "WebSocket protocol wrapper"),
        ("httpx", "HTTP client"),
    ]
    
    for pkg_name, desc in packages:
        try:
            __import__(pkg_name)
            results[pkg_name] = (True, "Import successful")
        except Exception as e:
            results[pkg_name] = (False, f"Failed to import: {str(e)}")
            
    return results

def check_sqlite_vec():
    try:
        import sqlite_vec
        conn = sqlite3.connect(":memory:")
        conn.enable_load_extension(True)
        try:
            sqlite_vec.load(conn)
            cursor = conn.cursor()
            cursor.execute("SELECT vec_version()")
            vec_version = cursor.fetchone()[0]
            
            # Run a dummy query to make sure distance calculations work
            cursor.execute(
                "SELECT vec_distance_l2(?, ?)",
                (sqlite_vec.serialize_float32([1.0, 2.0]), sqlite_vec.serialize_float32([1.0, 3.0]))
            )
            dist = cursor.fetchone()[0]
            
            conn.close()
            return True, f"sqlite-vec loaded successfully. Version: {vec_version}, Test distance L2: {dist}"
        except Exception as e:
            conn.close()
            return False, f"Failed to load vec0 extension: {str(e)}"
    except Exception as e:
        return False, f"Failed to import sqlite_vec: {str(e)}"

def check_appdata():
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return False, "APPDATA environment variable not found."
    
    aloy_dir = Path(appdata) / "ALOY"
    try:
        aloy_dir.mkdir(parents=True, exist_ok=True)
        test_file = aloy_dir / "test_write.tmp"
        test_file.write_text("test")
        test_file.unlink()
        return True, f"AppData directory is writable: {aloy_dir}"
    except Exception as e:
        return False, f"Failed to write to AppData directory {aloy_dir}: {str(e)}"

def check_migrations():
    # Detect if running in frozen package vs dev mode
    is_frozen = getattr(sys, "frozen", False)
    if is_frozen:
        migration_dir = Path(sys._MEIPASS) / "database" / "migrations"
    else:
        migration_dir = Path(__file__).parent.parent / "database" / "migrations"
        
    if not migration_dir.exists():
        return False, f"Migrations directory not found at: {migration_dir}"
        
    try:
        from database.migrator import MIGRATION_NAMES
        missing = []
        for name in MIGRATION_NAMES:
            mig_file = migration_dir / f"{name}.py"
            if not mig_file.exists():
                missing.append(name)
        if missing:
            return False, f"Missing migration files in {migration_dir}: {missing}"
        return True, f"All {len(MIGRATION_NAMES)} migrations found at {migration_dir}"
    except ImportError:
        # Fallback to direct directory scan
        files = list(migration_dir.glob("*.py"))
        py_files = [f.name for f in files if not f.name.startswith("__")]
        return True, f"Found {len(py_files)} migration files in {migration_dir} (Direct Scan)"
    except Exception as e:
        return False, f"Error scanning migrations: {str(e)}"

def check_config():
    is_frozen = getattr(sys, "frozen", False)
    if is_frozen:
        config_path = Path(sys._MEIPASS) / "config" / "default.yaml"
    else:
        config_path = Path(__file__).parent.parent / "config" / "default.yaml"
        
    if not config_path.exists():
        return False, f"Config file default.yaml not found at: {config_path}"
        
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        return True, f"Config file loaded successfully from {config_path}. Keys: {list(cfg.keys())}"
    except Exception as e:
        return False, f"Failed to load or parse config at {config_path}: {str(e)}"

def check_static_assets():
    is_frozen = getattr(sys, "frozen", False)
    if is_frozen:
        static_dir = Path(sys._MEIPASS) / "static"
    else:
        static_dir = Path(__file__).parent.parent / "static"
        
    if not static_dir.exists():
        return False, f"Static assets directory not found at: {static_dir}"
        
    index_file = static_dir / "index.html"
    if not index_file.exists():
        return False, f"Critical static asset index.html missing at: {index_file}"
        
    size = index_file.stat().st_size
    if size == 0:
        return False, f"Critical static asset index.html is empty (0 bytes) at: {index_file}"
        
    return True, f"Static assets verified at {static_dir}. index.html size: {size} bytes"

def check_ollama():
    import httpx
    url = "http://localhost:11434/api/tags"
    try:
        resp = httpx.get(url, timeout=2.0)
        if resp.status_code == 200:
            models = [m["name"] for m in resp.json().get("models", [])]
            return True, f"Ollama is running. Available models: {models}"
        else:
            return False, f"Ollama returned HTTP status {resp.status_code}"
    except Exception as e:
        return False, f"Ollama not reachable at {url}. Make sure Ollama is installed and running: {str(e)}"

def check_port_binding():
    port = 8000
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
        return True, f"Port {port} is free and writable for binding."
    except Exception as e:
        return False, f"Failed to bind to port {port} (already in use or permission denied): {str(e)}"

def check_db_initialization():
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return False, "Cannot initialize DB: APPDATA path missing."
        
    db_path = Path(appdata) / "ALOY" / "data" / "aloy_diagnostic_test.db"
    try:
        # Clean old run if exists
        if db_path.exists():
            db_path.unlink()
            
        # Test direct SQLite connection
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, val TEXT)")
        cursor.execute("INSERT INTO test_table (val) VALUES ('test_val')")
        cursor.execute("SELECT val FROM test_table WHERE id=1")
        val = cursor.fetchone()[0]
        conn.close()
        
        if val == "test_val":
            db_path.unlink()
            return True, f"SQLite DB creation and write verified successfully at: {db_path}"
        else:
            db_path.unlink()
            return False, f"Data mismatch during SQLite write test: {val}"
    except Exception as e:
        if db_path.exists():
            try: db_path.unlink() 
            except: pass
        return False, f"SQLite DB write test failed: {str(e)}"

def run_diagnostics():
    print("==================================================")
    print("           ALOY Deployment Diagnostics            ")
    print("==================================================")
    print(f"Python Runtime: {sys.version}")
    print(f"Platform:       {sys.platform}")
    print(f"Executable:     {sys.executable}")
    print(f"Frozen Package: {getattr(sys, 'frozen', False)}")
    print("--------------------------------------------------\n")
    
    # 1. AppData Permission Check
    ok, msg = check_appdata()
    print(f"[{'PASS' if ok else 'FAIL'}] AppData Directory:")
    print(f"       {msg}\n")
    
    # 2. Imports Check
    print("[INFO] Package Imports:")
    import_results = check_imports()
    all_imports_ok = True
    for pkg, (ok, msg) in import_results.items():
        print(f"       - {pkg:<20}: {'OK' if ok else 'FAIL (' + msg + ')'}")
        if not ok:
            all_imports_ok = False
    print()
            
    # 3. SQLite and Vector Extension Check
    ok, msg = check_sqlite_vec()
    print(f"[{'PASS' if ok else 'FAIL'}] sqlite-vec Extension:")
    print(f"       {msg}\n")
    
    # 4. Migrations Check
    ok, msg = check_migrations()
    print(f"[{'PASS' if ok else 'FAIL'}] Database Migrations:")
    print(f"       {msg}\n")
    
    # 5. Config Check
    ok, msg = check_config()
    print(f"[{'PASS' if ok else 'FAIL'}] Configuration Load:")
    print(f"       {msg}\n")
    
    # 6. Static Assets Check
    ok, msg = check_static_assets()
    print(f"[{'PASS' if ok else 'FAIL'}] Static Assets:")
    print(f"       {msg}\n")
    
    # 7. Port Binding Check
    ok, msg = check_port_binding()
    print(f"[{'PASS' if ok else 'FAIL'}] Port Binding (8000):")
    print(f"       {msg}\n")
    
    # 8. DB Initialization Check
    ok, msg = check_db_initialization()
    print(f"[{'PASS' if ok else 'FAIL'}] Database Write Test:")
    print(f"       {msg}\n")
    
    # 9. Ollama Check
    ok, msg = check_ollama()
    print(f"[{'PASS' if ok else 'WARNING'}] Ollama Local Service:")
    print(f"       {msg}\n")
    
    print("==================================================")
    print("             Diagnostics Completed                ")
    print("==================================================")

if __name__ == "__main__":
    run_diagnostics()
