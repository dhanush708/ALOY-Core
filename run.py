import os
import sys
import traceback
import datetime
import socket
import time
from pathlib import Path

START_TIME = time.perf_counter()
from kernel.profiler import profiler
profiler.start_time = START_TIME

# Prevent uvicorn/logging crashes when running without a console (sys.stdout/stderr are None)
if sys.stdout is None:
    class NullWriter:
        def write(self, *args, **kwargs): pass
        def flush(self, *args, **kwargs): pass
        def isatty(self): return False
    sys.stdout = NullWriter()
if sys.stderr is None:
    class NullWriter:
        def write(self, *args, **kwargs): pass
        def flush(self, *args, **kwargs): pass
        def isatty(self): return False
    sys.stderr = NullWriter()

# ══════════════════════════════════════════════════════════════════════════════
# PATH BOOTSTRAP — Runs BEFORE any other imports.
#
# Problem: When launched from a Start Menu or Desktop shortcut, Windows sets
# CWD to %USERPROFILE% or %SYSTEM32% — NOT the install directory.
# Every relative path ("static/", "data/", "logs/", "config/") then resolves
# to the wrong location, causing a silent launch failure.
#
# Fix:
#   1. Detect frozen (PyInstaller) mode via sys.frozen.
#   2. Set CWD to the directory containing ALOY.exe.
#   3. Route all WRITES to %APPDATA%\ALOY\ (guaranteed writable, per-user).
#   4. Route all READS of bundled assets to sys._MEIPASS (_internal/).
# ══════════════════════════════════════════════════════════════════════════════

FROZEN = getattr(sys, "frozen", False)

# User-writable application data directory (guaranteed writable on any Windows)
APP_DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "ALOY"
LOG_DIR  = APP_DATA_DIR / "logs"
DATA_DIR = APP_DATA_DIR / "data"

# Create required write directories immediately — before any other code runs
try:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass  # If this fails we're in serious trouble; error dialog will catch it later

if FROZEN:
    # Fix 1: Set CWD to the install directory (where ALOY.exe lives)
    # sys.executable = C:\Program Files\ALOY\ALOY.exe
    # .parent        = C:\Program Files\ALOY\
    install_dir = Path(sys.executable).parent
    os.chdir(install_dir)

    # Fix 2: Redirect tiktoken to bundled offline cache
    bundle_dir = Path(sys._MEIPASS)
    os.environ["TIKTOKEN_CACHE_DIR"] = str(bundle_dir / "assets" / "tiktoken_cache")

    # Expose bundle dir for other modules to read
    os.environ["ALOY_BUNDLE_DIR"]   = str(bundle_dir)
    os.environ["ALOY_DATA_DIR"]     = str(DATA_DIR)
    os.environ["ALOY_LOG_DIR"]      = str(LOG_DIR)
else:
    # Development mode — source tree layout
    bundle_dir = Path(__file__).parent


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def show_error_dialog(title: str, message: str) -> None:
    """Display a native Windows error dialog (works even with console=False)."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
    except Exception:
        pass


def log_startup_error(error_msg: str) -> None:
    """Append an error to the guaranteed-writable startup log."""
    try:
        log_file = LOG_DIR / "startup.log"
        with open(log_file, "a", encoding="utf-8") as f:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{timestamp}] STARTUP ERROR:\n{error_msg}\n{'-' * 60}\n")
    except Exception:
        pass


def check_port_available(port: int) -> bool:
    """Return True if the given TCP port is free on 127.0.0.1."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
            return True
    except OSError:
        return False


# ══════════════════════════════════════════════════════════════════════════════
# IMPORT PHASE
# ══════════════════════════════════════════════════════════════════════════════

try:
    import uvicorn
    import logging
    import threading
    import webbrowser
    import time
    import httpx

    # Build log handlers — always write to file; stdout only in dev mode
    _handlers: list = []
    try:
        _file_handler = logging.FileHandler(
            str(LOG_DIR / "app.log"), encoding="utf-8"
        )
        _file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        _handlers.append(_file_handler)
    except Exception:
        pass

    if not FROZEN:
        # In dev mode also log to stdout
        _handlers.append(logging.StreamHandler(sys.stdout))

    if _handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=_handlers,
        )
    else:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )

    logger = logging.getLogger("aloy.run")

except Exception as e:
    err_msg = traceback.format_exc()
    log_startup_error(err_msg)
    show_error_dialog(
        "ALOY Startup Error",
        f"A critical error occurred during ALOY initialization:\n\n{e}"
        f"\n\nSee log: {LOG_DIR / 'startup.log'}",
    )
    sys.exit(1)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    profiler.record("Application boot", profiler.get_duration(profiler.start_time))
    PORT = 8000

    logger.info("=" * 60)
    logger.info("ALOY v1.0.0 — Starting up")
    if FROZEN:
        logger.info(f"Install dir : {Path(sys.executable).parent}")
    logger.info(f"Data dir    : {DATA_DIR}")
    logger.info(f"Log dir     : {LOG_DIR}")
    logger.info("=" * 60)

    # Python version guard
    if sys.version_info < (3, 11):
        msg = "ALOY requires Python 3.11 or higher."
        logger.error(msg)
        show_error_dialog("ALOY Version Error", msg)
        sys.exit(1)

    # Port availability check — before uvicorn, so we show a friendly message
    if not check_port_available(PORT):
        msg = (
            f"Port {PORT} is already in use.\n\n"
            "Another application (or a previous ALOY instance) may be running.\n"
            "Please close it and try again, or restart your computer."
        )
        logger.error(f"Port {PORT} is in use — cannot start server.")
        show_error_dialog("ALOY Port Conflict", msg)
        sys.exit(1)

    def launch_browser() -> None:
        logger.info("Browser auto-launch waiting for server readiness...")
        time.sleep(1.5)
        for _ in range(10):
            try:
                r = httpx.get(f"http://127.0.0.1:{PORT}/health", timeout=1.0)
                if r.status_code == 200:
                    profiler.record("Ready state", profiler.get_duration(profiler.start_time))
                    logger.info("Server is ready — opening browser.")
                    try:
                        httpx.get(f"http://127.0.0.1:{PORT}/api/system/health", timeout=5.0)
                    except Exception:
                        pass
                    webbrowser.open(f"http://127.0.0.1:{PORT}")
                    profiler.record("Browser launch", profiler.get_duration(profiler.start_time))
                    return
            except Exception:
                pass
            time.sleep(1.5)
        logger.warning(
            f"Browser auto-launch timed out. Open http://127.0.0.1:{PORT} manually."
        )

    LOCK_FILE = DATA_DIR / "running.tmp"
    
    def cleanup_lockfile():
        try:
            if LOCK_FILE.exists():
                LOCK_FILE.unlink()
                logger.info("Cleaned up lockfile.")
        except Exception:
            pass

    import signal
    def handle_exit_signal(signum, frame):
        logger.info(f"Signal {signum} received. Cleaning up and exiting.")
        cleanup_lockfile()
        sys.exit(0)

    if sys.platform == "win32":
        try:
            signal.signal(signal.SIGBREAK, handle_exit_signal)
        except ValueError:
            pass
    try:
        signal.signal(signal.SIGTERM, handle_exit_signal)
    except ValueError:
        pass

    try:
        threading.Thread(target=launch_browser, daemon=True).start()
        uvicorn.run(
            "api.server:app",
            host="127.0.0.1",
            port=PORT,
            log_level="info",
        )
    except KeyboardInterrupt:
        logger.info("ALOY shutting down gracefully.")
    except Exception as e:
        err_msg = traceback.format_exc()
        log_startup_error(err_msg)
        show_error_dialog(
            "ALOY Runtime Error",
            f"ALOY encountered a fatal error and must close:\n\n{e}"
            f"\n\nSee log: {LOG_DIR / 'startup.log'}",
        )
        sys.exit(1)
    finally:
        cleanup_lockfile()


if __name__ == "__main__":
    main()
