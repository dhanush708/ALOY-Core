import asyncio
import logging
import sys
from pathlib import Path

# Setup basic logging for the entry point
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("aloy")

async def main():
    logger.info("Starting ALOY...")
    
    # Check Python version
    if sys.version_info < (3, 11):
        logger.error("ALOY requires Python 3.11 or higher.")
        sys.exit(1)
        
    try:
        from kernel.boot import boot
        
        # Boot the kernel
        kernel = await boot()
        
        logger.info("ALOY booted successfully.")
        
        # Keep the main process alive
        # In the future, this will start the FastAPI server
        while True:
            await asyncio.sleep(3600)
            
    except KeyboardInterrupt:
        logger.info("ALOY shutting down gracefully...")
    except Exception as e:
        logger.exception(f"Fatal error during ALOY execution: {e}")
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
