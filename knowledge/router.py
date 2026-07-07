import logging
import asyncio
import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional

from tools.impl.web_search import WebSearchTool
from project.manager import ProjectManager
from .verification import SourceVerifier
from .research_cache import ResearchCache

logger = logging.getLogger(__name__)

class KnowledgeRouter:
    """Escalates technical queries progressively through 6 information layers."""

    def __init__(self, db_pool, memory_manager, doc_intelligence, model_router):
        self.db_pool = db_pool
        self.memory_manager = memory_manager
        self.doc_intel = doc_intelligence
        self.model_router = model_router
        
        self.verifier = SourceVerifier(model_router)
        self.cache = ResearchCache(db_pool)
        self.project_mgr = ProjectManager(db_pool)
        self.search_tool = WebSearchTool()

    async def query_escalation(
        self,
        query: str,
        workspace_path: Optional[str | Path] = None,
        package: Optional[str] = None
    ) -> Dict[str, Any]:
        """Perform progressive query routing and return verified results."""
        logger.info(f"KnowledgeRouter: query='{query}' escalation started.")

        # Check Cache first
        cached = self.cache.get(query)
        if cached:
            logger.info("KnowledgeRouter: cache HIT.")
            return cached

        # Step 1: Global Episodic/Semantic Memory
        logger.info("KnowledgeRouter: Step 1 - Global Memory.")
        mem_results = await self.memory_manager.retrieve(query, types=["episodic", "semantic"], limit=3)
        if mem_results and mem_results[0].score >= 0.85:
            logger.info(f"KnowledgeRouter: Global Memory HIT (score={mem_results[0].score:.2f}).")
            res = {
                "answer": mem_results[0].memory.content,
                "layer": "global_memory",
                "confidence": mem_results[0].score,
                "sources": [{"type": "memory", "id": mem_results[0].memory.id}]
            }
            self.cache.set(query, res)
            return res

        # Step 2: Workspace Scoped Memory
        workspace_id = None
        if workspace_path:
            logger.info("KnowledgeRouter: Step 2 - Workspace Memory.")
            resolved_proj = self.project_mgr.get_project_by_root(workspace_path)
            if resolved_proj:
                workspace_id = resolved_proj["id"]
                ws_mem = await self.memory_manager.retrieve_workspace_memory(workspace_id, query, limit=3)
                if ws_mem and ws_mem[0].score >= 0.85:
                    logger.info(f"KnowledgeRouter: Workspace Memory HIT (score={ws_mem[0].score:.2f}).")
                    res = {
                        "answer": ws_mem[0].memory.content,
                        "layer": "workspace_memory",
                        "confidence": ws_mem[0].score,
                        "sources": [{"type": "workspace_memory", "id": ws_mem[0].memory.id}]
                    }
                    self.cache.set(query, res)
                    return res

        # Step 3: Project Documentation Search
        if workspace_path:
            logger.info("KnowledgeRouter: Step 3 - Project Documentation.")
            doc_hits = await self._search_project_docs(workspace_path, query)
            if doc_hits:
                # Verify hits
                verified = await self.verifier.verify(query, doc_hits)
                if verified["confidence_score"] >= 0.85:
                    logger.info(f"KnowledgeRouter: Project Documentation HIT (score={verified['confidence_score']:.2f}).")
                    res = {
                        "answer": verified["answer"],
                        "layer": "project_documentation",
                        "confidence": verified["confidence_score"],
                        "sources": doc_hits
                    }
                    self.cache.set(query, res)
                    return res

        # Step 4: Official Subsystem Documentation
        if package:
            logger.info("KnowledgeRouter: Step 4 - Official Subsystem Docs.")
            summary_res = await self.doc_intel.get_summary_and_examples(query, package, workspace_path)
            # If we found valid summary (not error/not empty)
            summary = summary_res.get("summary") or summary_res.get("answer") or ""
            examples = summary_res.get("examples") or ""
            if examples or ("No offline documentation" not in summary and summary.strip()):
                logger.info("KnowledgeRouter: Official Subsystem Docs HIT.")
                res = {
                    "answer": f"{summary}\n\nExamples:\n{examples}" if examples else summary,
                    "layer": "official_documentation",
                    "confidence": 0.90,
                    "sources": summary_res.get("sources", [])
                }
                self.cache.set(query, res)
                return res

        # Step 5: Internet Web Search
        logger.info("KnowledgeRouter: Step 5 - Internet Search.")
        search_str = await self.search_tool.execute({"query": query}, {})
        snippets = self._parse_ddg_results_to_snippets(search_str)
        if snippets:
            verified = await self.verifier.verify(query, snippets)
            if verified["confidence_score"] >= 0.60:
                logger.info(f"KnowledgeRouter: Internet Search HIT (score={verified['confidence_score']:.2f}).")
                res = {
                    "answer": verified["answer"],
                    "layer": "internet_search",
                    "confidence": verified["confidence_score"],
                    "sources": snippets[:3]
                }
                await self._store_temp_findings(query, verified["answer"], res["sources"], verified.get("lessons_learned", ""))
                self.cache.set(query, res)
                return res

        # Step 6: Community Sources (StackOverflow/GitHub)
        logger.info("KnowledgeRouter: Step 6 - Community Sources.")
        comm_query = f"{query} site:stackoverflow.com OR site:github.com"
        comm_search = await self.search_tool.execute({"query": comm_query}, {})
        comm_snippets = self._parse_ddg_results_to_snippets(comm_search)
        if comm_snippets:
            verified = await self.verifier.verify(query, comm_snippets)
            logger.info(f"KnowledgeRouter: Community Sources complete (score={verified['confidence_score']:.2f}).")
            res = {
                "answer": verified["answer"],
                "layer": "community_sources",
                "confidence": verified["confidence_score"],
                "sources": comm_snippets[:3]
            }
            await self._store_temp_findings(query, verified["answer"], res["sources"], verified.get("lessons_learned", ""))
            self.cache.set(query, res)
            return res

        return {
            "answer": "Escalation completed. Unable to find reliable information.",
            "layer": "none",
            "confidence": 0.0,
            "sources": []
        }

    async def consolidate_research(self) -> int:
        """Promote temporary research context memories to long-term memory."""
        # 1. Fetch temporary memories
        with self.db_pool.get_read_connection() as conn:
            cursor = conn.execute("SELECT id, content, metadata FROM memories WHERE tier = 'temporary'")
            rows = cursor.fetchall()
            
        if not rows:
            return 0
            
        count = 0
        for r in rows:
            mem_id = r["id"]
            content = r["content"]
            meta = json.loads(r["metadata"] or "{}")
            
            # Use LLM to consolidate it into clean long-term memory
            prompt = f"""You are ALOY's Memory Consolidation engine.
Convert the following temporary research findings into a clean, concise, permanent semantic insight. Avoid duplicates, conversational text, and keep only reusable developer advice, design choices, or package behaviors.

Temporary Findings:
{content}

Output format:
Directly output the final clean insight text. No JSON wrapping, no conversational introduction.
"""
            try:
                insight = await self.model_router.generate("summarization", prompt)
                
                # Save to permanent memory store
                await self.memory_manager.store(
                    type="semantic",
                    content=insight.strip(),
                    tier="long_term",
                    importance=0.7,
                    is_protected=False,
                    category="consolidated_research",
                    metadata={"consolidated_from": mem_id, "original_query": meta.get("query")}
                )
                
                # Delete the temporary memory
                await self.memory_manager.delete(mem_id, force=True)
                count += 1
            except Exception as e:
                logger.error(f"Failed to consolidate research memory {mem_id}: {e}")
                
        return count

    async def _search_project_docs(self, workspace_path: str | Path, query: str) -> List[Dict[str, Any]]:
        """Search text/markdown documentation files in the active workspace."""
        path = Path(workspace_path)
        keywords = set(re.findall(r'\w+', query.lower()))
        
        matches = []
        # Look for md, txt, readmes
        for p in path.rglob("*"):
            if p.is_dir() or p.suffix not in [".md", ".txt", ".rst"]:
                continue
            # Ignore venv, git, node_modules, etc.
            if any(part in p.parts for part in ["venv", ".venv", ".git", "node_modules", ".pytest_cache", ".aloy"]):
                continue
                
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
                # Basic scoring: check keyword overlap
                content_lower = content.lower()
                score = sum(1 for kw in keywords if kw in content_lower)
                if score > 0:
                    matches.append({
                        "title": p.name,
                        "url": p.as_posix(),
                        "snippet": content[:800], # excerpt
                        "score": score
                    })
            except Exception:
                pass
                
        # Sort by score descending and return top 3
        matches.sort(key=lambda x: x["score"], reverse=True)
        return matches[:3]

    def _parse_ddg_results_to_snippets(self, text: str) -> List[Dict[str, Any]]:
        """Parse raw duckduckgo string results into individual snippet dicts."""
        snippets = []
        blocks = text.split("Title: ")
        for b in blocks:
            b = b.strip()
            if not b:
                continue
            try:
                title = b.split("\nURL: ")[0].strip()
                url = b.split("\nURL: ")[1].split("\nSnippet: ")[0].strip()
                snippet = b.split("\nSnippet: ")[1].strip().split("\n---")[0].strip()
                snippets.append({
                    "title": title,
                    "url": url,
                    "snippet": snippet
                })
            except Exception:
                pass
        return snippets

    async def _store_temp_findings(self, query: str, answer: str, sources: List[Dict[str, Any]], lessons: str):
        """Persist findings temporarily in memory."""
        try:
            content = f"[Research Answer] Query: {query}\nAnswer: {answer}\nSources: {sources}"
            metadata = {
                "query": query,
                "sources": sources,
                "lessons_learned": lessons
            }
            mem = await self.memory_manager.store(
                type="research_findings",
                content=content,
                tier="temporary",
                is_protected=True,
                metadata=metadata
            )
            self.memory_manager.tags.add_tags(mem.id, ["research", "temporary"])
        except Exception as e:
            logger.error(f"Failed to store temporary findings: {e}")
