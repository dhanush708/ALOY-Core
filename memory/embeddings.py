import logging
import httpx
from typing import List, Optional

logger = logging.getLogger(__name__)

class EmbeddingEngine:
    """Generates embeddings via Ollama.
    
    Uses nomic-embed-text by default; falls back gracefully to None
    when the embedding model or /api/embed endpoint is unavailable.
    Memory retrieval degrades to FTS5-only mode in that case.
    """
    
    def __init__(self, ollama_url: str = "http://localhost:11434", model: str = "nomic-embed-text"):
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model
        self._warned = False  # emit warning only once per instance

    def _warn_once(self, msg: str) -> None:
        if not self._warned:
            logger.warning(msg)
            self._warned = True
        
    async def generate(self, text: str) -> Optional[List[float]]:
        """Generate a single embedding for the given text.
        
        Returns None if the embedding service is unavailable — callers
        must handle None gracefully (FTS5-only fallback).
        """
        if not text or not text.strip():
            return None
            
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.ollama_url}/api/embed",
                    json={"model": self.model, "input": text},
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    embeddings = data.get("embeddings", [])
                    if embeddings and len(embeddings) > 0:
                        return embeddings[0]
                else:
                    self._warn_once(
                        f"Embedding unavailable ({response.status_code}). "
                        "Memory retrieval will use FTS5 text-search only. "
                        "Pull 'nomic-embed-text' with `ollama pull nomic-embed-text` to enable vector search."
                    )
                    
        except Exception as e:
            self._warn_once(f"Embedding engine offline: {e}. FTS5-only mode active.")
            
        return None
        
    async def generate_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Generate embeddings for multiple texts.
        
        Returns a list of None values if the service is unavailable.
        """
        if not texts:
            return []
            
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.ollama_url}/api/embed",
                    json={"model": self.model, "input": texts},
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    embeddings = data.get("embeddings", [])
                    return embeddings
                else:
                    self._warn_once(
                        f"Batch embedding unavailable ({response.status_code}). FTS5-only mode active."
                    )
                    
        except Exception as e:
            self._warn_once(f"Batch embedding engine offline: {e}.")
            
        return [None] * len(texts)
