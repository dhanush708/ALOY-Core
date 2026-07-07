import logging
import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional

from .dependency_resolver import DependencyResolver
from .indexer import OfflineDocIndexer
from .cache import DocCache

logger = logging.getLogger(__name__)

class DocumentationIntelligence:
    """Orchestrates version-aware retrieval, indexing, summarization, and caching of documentation."""

    def __init__(self, db_pool, memory_manager, model_router):
        self.db_pool = db_pool
        self.memory_manager = memory_manager
        self.model_router = model_router
        
        self.resolver = DependencyResolver()
        self.indexer = OfflineDocIndexer(memory_manager)
        self.cache = DocCache(db_pool)

    async def search_docs(
        self,
        query: str,
        package: str,
        workspace_path: Optional[str | Path] = None,
        doc_type: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Retrieve and rank documentation chunks based on query, package, and version."""
        package = package.strip().lower()
        
        # 1. Resolve workspace version
        version = "unknown"
        if workspace_path:
            resolved = self.resolver.resolve_versions(workspace_path)
            version = resolved.get(package, "unknown")
            
        # 2. Retrieve memories with the package tag
        package_tag = f"package:{package}"
        scored_memories = await self.memory_manager.retrieve(
            query=query,
            types=["documentation"],
            limit=50,
            tags=[package_tag]
        )
        
        # 3. Post-filter and re-rank based on version similarity and doc_type
        ranked_results = []
        for sm in scored_memories:
            mem = sm.memory
            mem_meta = mem.metadata or {}
            
            # Verify package matches (extra check)
            if mem_meta.get("package", "").lower() != package:
                continue
                
            # Filter by doc_type if requested
            if doc_type and mem_meta.get("doc_type", "").lower() != doc_type.lower():
                continue
                
            mem_version = mem_meta.get("version", "unknown").lower()
            
            # Version compatibility multiplier
            version_multiplier = self._compute_version_score(version, mem_version)
            
            # Combine hybrid search score with version similarity
            final_score = sm.score * version_multiplier
            
            ranked_results.append({
                "memory_id": mem.id,
                "content": mem.content,
                "score": final_score,
                "version": mem_version,
                "doc_type": mem_meta.get("doc_type", "api_reference"),
                "file_name": mem_meta.get("file_name", "")
            })
            
        # Sort by final score descending
        ranked_results.sort(key=lambda x: x["score"], reverse=True)
        return ranked_results[:limit]

    async def get_summary_and_examples(
        self,
        query: str,
        package: str,
        workspace_path: Optional[str | Path] = None
    ) -> Dict[str, Any]:
        """Fetch cached summary/examples or generate using ModelRouter and cache it."""
        package = package.strip().lower()
        
        # Resolve version
        version = "unknown"
        if workspace_path:
            resolved = self.resolver.resolve_versions(workspace_path)
            version = resolved.get(package, "unknown")
            
        # 1. Check cache
        cached = self.cache.get(query, package, version)
        if cached:
            logger.info("Doc summary cache HIT")
            return cached
            
        # 2. Retrieve snippets
        snippets = await self.search_docs(query, package, workspace_path, limit=5)
        if not snippets:
            return {
                "summary": f"No offline documentation found for package '{package}'.",
                "examples": "",
                "sources": []
            }
            
        # 3. Compile snippets into prompt
        snippets_text = ""
        sources = []
        for s in snippets:
            snippets_text += f"\n--- Source: {s['file_name']} (v{s['version']}) ---\n{s['content']}\n"
            sources.append({
                "file_name": s["file_name"],
                "version": s["version"],
                "doc_type": s["doc_type"]
            })
            
        prompt = f"""You are ALOY's Documentation Intelligence engine.
Based on the official documentation snippets below for package '{package}' (version '{version}'), answer the user's technical query.

Query: {query}

Official Snippets:
{snippets_text}

Generate your response in JSON format with two keys:
- "summary": A concise technical summary answering the query.
- "examples": A clean, copy-pasteable Markdown code block containing code examples demonstrating the API usage. No other conversational text.

JSON format:
{{
   "summary": "...",
   "examples": "```python\\n...\\n```"
}}
"""
        
        try:
            # We route this request using routing key 'meta_request' or 'simple_chat'
            llm_response = await self.model_router.generate(
                task="meta_request",
                prompt=prompt
            )
            
            # Extract JSON from response
            result = self._parse_json_response(llm_response)
            result["sources"] = sources
            
            # Set cache
            self.cache.set(query, package, version, result)
            return result
        except Exception as e:
            logger.error(f"Failed to generate documentation summary: {e}")
            return {
                "summary": f"Error generating summary from documentation: {e}",
                "examples": "",
                "sources": sources
            }

    def _compute_version_score(self, target: str, candidate: str) -> float:
        """Compute version compatibility multiplier between target and candidate."""
        target = target.lower().strip()
        candidate = candidate.lower().strip()
        
        if target == candidate or target == "unknown" or candidate == "unknown":
            return 1.0
            
        # Parse major.minor.patch
        target_parts = re.split(r'[^0-9a-zA-Z]+', target)
        candidate_parts = re.split(r'[^0-9a-zA-Z]+', candidate)
        
        # Match major and minor
        if len(target_parts) >= 2 and len(candidate_parts) >= 2:
            if target_parts[0] == candidate_parts[0] and target_parts[1] == candidate_parts[1]:
                return 0.9 # Same minor version
            elif target_parts[0] == candidate_parts[0]:
                return 0.6 # Same major version
                
        return 0.3 # Different major version

    def _parse_json_response(self, text: str) -> Dict[str, str]:
        """Extract and parse JSON block from LLM string output."""
        text = text.strip()
        
        # Find JSON boundaries
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
                
        # Fallback in case of parsing failures
        return {
            "summary": text,
            "examples": ""
        }
