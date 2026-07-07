import re
import json
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class IssueDetector:
    """Detects repeated failures, semantic overlaps, prompt drift, and missing packages in ALOY."""

    def __init__(self, db_pool, model_tracker=None):
        self.db_pool = db_pool
        self.tracker = model_tracker

    def detect_all(self) -> Dict[str, List[Dict[str, Any]]]:
        """Runs all detection modules and returns list of findings."""
        return {
            "repeated_failures": self.detect_repeated_failures(),
            "semantic_overlaps": self.detect_semantic_overlaps(),
            "prompt_drift": self.detect_prompt_drift(),
            "missing_packages": self.detect_missing_packages(),
        }

    def detect_repeated_failures(self) -> List[Dict[str, Any]]:
        """Finds agent tasks or operations that have failed repeatedly (>= 2 times)."""
        logger.info("Detecting repeated failures...")
        query = """
            SELECT assigned_agent, title, error, COUNT(*) as fail_count
            FROM agent_tasks
            WHERE status = 'failed' AND error IS NOT NULL AND error != ''
            GROUP BY assigned_agent, title, error
            HAVING fail_count >= 2
        """
        findings = []
        try:
            with self.db_pool.get_read_connection() as conn:
                cursor = conn.execute(query)
                rows = cursor.fetchall()
                for row in rows:
                    findings.append({
                        "agent": row["assigned_agent"],
                        "task_title": row["title"],
                        "error_message": row["error"],
                        "fail_count": row["fail_count"],
                        "evidence": f"Agent '{row['assigned_agent']}' failed executing task '{row['title']}' {row['fail_count']} times with error: {row['error']}"
                    })
        except Exception as e:
            logger.error(f"Error detecting repeated failures: {e}")
        return findings

    def detect_semantic_overlaps(self) -> List[Dict[str, Any]]:
        """Finds semantic or permanent memories that overlap significantly (Jaccard similarity >= 0.7)."""
        logger.info("Detecting semantic overlaps...")
        query = """
            SELECT id, type, category, content
            FROM memories
            WHERE (tier = 'permanent' OR type = 'semantic') AND archived_at IS NULL
        """
        findings = []
        try:
            with self.db_pool.get_read_connection() as conn:
                cursor = conn.execute(query)
                memories = [dict(row) for row in cursor.fetchall()]

            # Compare pairs
            n = len(memories)
            for i in range(n):
                for j in range(i + 1, n):
                    m1 = memories[i]
                    m2 = memories[j]
                    
                    # Compute Jaccard Similarity
                    w1 = set(re.findall(r'\w+', m1["content"].lower()))
                    w2 = set(re.findall(r'\w+', m2["content"].lower()))
                    
                    if not w1 or not w2:
                        continue
                        
                    similarity = len(w1.intersection(w2)) / len(w1.union(w2))
                    if similarity >= 0.70:
                        findings.append({
                            "memory_id_1": m1["id"],
                            "memory_id_2": m2["id"],
                            "content_1": m1["content"],
                            "content_2": m2["content"],
                            "similarity": similarity,
                            "evidence": f"Memories '{m1['id']}' and '{m2['id']}' share {similarity:.2%} vocabulary overlap:\n- '{m1['content']}'\n- '{m2['content']}'"
                        })
        except Exception as e:
            logger.error(f"Error detecting semantic overlaps: {e}")
        return findings

    def detect_prompt_drift(self) -> List[Dict[str, Any]]:
        """Identifies prompt templates or model tasks that exhibit high latency or error rates."""
        logger.info("Detecting prompt drift...")
        findings = []

        # 1. Check in-memory ModelTracker if available
        if self.tracker:
            for key, call_count in self.tracker._calls.items():
                model, task = key
                err_count = self.tracker._errors.get(key, 0)
                error_rate = err_count / call_count if call_count else 0.0
                
                # Check latency
                lats = self.tracker._latencies.get(key, [])
                avg_latency = sum(lats) / len(lats) if lats else 0.0

                if error_rate >= 0.15 or avg_latency > 15000:
                    findings.append({
                        "model": model,
                        "task": task,
                        "error_rate": error_rate,
                        "avg_latency_ms": avg_latency,
                        "evidence": f"Model '{model}' for task '{task}' is degraded: error rate {error_rate:.2%}, avg latency {avg_latency/1000:.2f}s"
                    })
                    
        # 2. Check telemetry DB table for system.latency_ms and model info
        query = """
            SELECT metric, tags, AVG(value) as avg_val, COUNT(*) as count
            FROM telemetry
            WHERE metric IN ('llm.tokens_in', 'llm.tokens_out', 'system.latency_ms')
            GROUP BY metric, tags
        """
        try:
            with self.db_pool.get_read_connection() as conn:
                cursor = conn.execute(query)
                rows = cursor.fetchall()
                # Aggregate by tag hash to compute telemetry findings
                for row in rows:
                    tags = json.loads(row["tags"] or "{}")
                    metric = row["metric"]
                    if metric == "system.latency_ms" and tags.get("operation") == "llm.inference" and row["avg_val"] > 15000:
                        findings.append({
                            "model": tags.get("model", "unknown"),
                            "task": tags.get("task", "unknown"),
                            "avg_latency_ms": row["avg_val"],
                            "evidence": f"Telemetry indicates high average inference latency ({row['avg_val']/1000:.2f}s) for model '{tags.get('model')}' on task '{tags.get('task')}'."
                        })
        except Exception as e:
            logger.error(f"Error detecting prompt drift from telemetry: {e}")

        # De-duplicate findings by task
        seen_tasks = set()
        unique_findings = []
        for f in findings:
            task = f.get("task")
            if task not in seen_tasks:
                seen_tasks.add(task)
                unique_findings.append(f)
                
        return unique_findings

    def detect_missing_packages(self) -> List[Dict[str, Any]]:
        """Scans failed task results/errors for package import issues (Python/Node)."""
        logger.info("Detecting missing packages...")
        findings = []
        query = """
            SELECT id, assigned_agent, title, error, result
            FROM agent_tasks
            WHERE (error LIKE '%ModuleNotFoundError%' OR error LIKE '%ImportError%' OR error LIKE '%npm ERR!%')
        """
        try:
            with self.db_pool.get_read_connection() as conn:
                cursor = conn.execute(query)
                rows = cursor.fetchall()
                for row in rows:
                    err_txt = row["error"] or ""
                    res_txt = row["result"] or ""
                    combined = f"{err_txt}\n{res_txt}"

                    # Regex patterns
                    py_match = re.search(r"ModuleNotFoundError:\s*No\s*module\s*named\s*'([^']+)'", combined)
                    py_import_match = re.search(r"ImportError:\s*cannot\s*import\s*name\s*'([^']+)'", combined)
                    node_match = re.search(r"Cannot\s*find\s*module\s*'([^']+)'", combined)

                    pkg = None
                    sys_type = None

                    if py_match:
                        pkg = py_match.group(1).split('.')[0]
                        sys_type = "python"
                    elif py_import_match:
                        pkg = py_import_match.group(1)
                        sys_type = "python"
                    elif node_match:
                        pkg = node_match.group(1)
                        sys_type = "node"

                    if pkg:
                        findings.append({
                            "task_id": row["id"],
                            "agent": row["assigned_agent"],
                            "package_name": pkg,
                            "system": sys_type,
                            "evidence": f"Task '{row['title']}' failed due to missing {sys_type} package '{pkg}'. Log context: {combined[:150]}..."
                        })
        except Exception as e:
            logger.error(f"Error detecting missing packages: {e}")
            
        # Deduplicate missing packages
        seen_pkgs = set()
        unique_findings = []
        for f in findings:
            key = (f["package_name"], f["system"])
            if key not in seen_pkgs:
                seen_pkgs.add(key)
                unique_findings.append(f)

        return unique_findings
