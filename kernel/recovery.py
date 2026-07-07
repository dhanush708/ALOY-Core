import asyncio
import logging
from typing import Callable, Any, TypeVar, Awaitable

logger = logging.getLogger(__name__)

T = TypeVar('T')

class ErrorRecovery:
    """Centralized error recovery for all subsystem operations."""
    
    async def start(self):
        logger.info("Error Recovery system started.")
        
    async def stop(self):
        pass
        
    async def with_retry(
        self,
        func: Callable[[], Awaitable[T]],
        max_retries: int = 3,
        backoff_strategy: str = "exponential",  # 'none', 'linear', 'exponential'
        base_delay_seconds: float = 1.0,
        fallback: Callable[[], Awaitable[T]] = None
    ) -> T:
        """Execute with retry logic. If all retries fail, call fallback."""
        
        attempt = 0
        while attempt <= max_retries:
            try:
                return await func()
            except Exception as e:
                attempt += 1
                if attempt > max_retries:
                    logger.error(f"Operation failed after {max_retries} retries: {e}")
                    if fallback:
                        logger.info("Executing fallback operation")
                        return await fallback()
                    raise
                    
                # Calculate delay
                if backoff_strategy == "exponential":
                    delay = base_delay_seconds * (2 ** (attempt - 1))
                elif backoff_strategy == "linear":
                    delay = base_delay_seconds * attempt
                else:
                    delay = base_delay_seconds
                    
                logger.warning(f"Operation failed: {e}. Retrying {attempt}/{max_retries} in {delay}s...")
                await asyncio.sleep(delay)
                
        raise RuntimeError("Unreachable")
        
    async def with_fallback_model(
        self,
        prompt: str,
        primary_model: str,
        fallback_models: list[str],
        generate_func: Callable[[str, str], Awaitable[str]] # func(prompt, model)
    ) -> str:
        """Try primary model, fall back through alternatives on failure."""
        try:
            return await generate_func(prompt, primary_model)
        except Exception as e:
            logger.warning(f"Primary model {primary_model} failed: {e}. Attempting fallbacks.")
            
            for model in fallback_models:
                try:
                    logger.info(f"Trying fallback model: {model}")
                    return await generate_func(prompt, model)
                except Exception as ex:
                    logger.warning(f"Fallback model {model} failed: {ex}")
                    
            logger.error("All fallback models failed.")
            raise RuntimeError("All models failed generation") from e
