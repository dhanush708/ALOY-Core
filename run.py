import os
import sys
from pathlib import Path

# Setup tiktoken offline cache for PyInstaller packaged environment
if getattr(sys, 'frozen', False):
    bundle_dir = Path(sys._MEIPASS)
    os.environ["TIKTOKEN_CACHE_DIR"] = str(bundle_dir / "assets" / "tiktoken_cache")

import uvicorn
import logging

# Setup basic logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("aloy.run")

def main():
    logger.info("Starting ALOY production server...")
    if sys.version_info < (3, 11):
        logger.error("ALOY requires Python 3.11 or higher.")
        sys.exit(1)
        
    import threading
    import webbrowser
    import time
    import httpx

    def launch_browser():
        logger.info("Browser auto-launch agent active. Waiting for server...")
        time.sleep(1.5)
        for _ in range(5):
            try:
                r = httpx.get("http://127.0.0.1:8000/health", timeout=1.0)
                if r.status_code == 200:
                    logger.info("ALOY server detected. Launching default browser...")
                    webbrowser.open("http://127.0.0.1:8000")
                    return
            except Exception:
                pass
            time.sleep(1.5)
        logger.warning("Browser auto-launch timed out.")

    try:
        # Start browser launch thread
        threading.Thread(target=launch_browser, daemon=True).start()
        # Start uvicorn server serving the FastAPI app
        uvicorn.run("api.server:app", host="127.0.0.1", port=8000, log_level="info")

    except KeyboardInterrupt:
        logger.info("ALOY shutting down gracefully...")
    except Exception as e:
        logger.exception(f"Fatal error during ALOY execution: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
