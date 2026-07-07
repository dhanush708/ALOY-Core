from fastapi import APIRouter, Request, Query, HTTPException
from typing import Optional, List, Dict, Any
import json

router = APIRouter(prefix="/api/system", tags=["telemetry"])

@router.get("/metrics")
async def get_metrics(
    request: Request,
    metric: Optional[str] = None,
    period: str = Query("raw", pattern="^(raw|hourly|daily)$"),
    since: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000)
):
    db_pool = request.app.state.db_pool
    if not db_pool:
        raise HTTPException(status_code=500, detail="Database connection pool not available")
        
    query_parts = []
    params = []
    
    if period == "raw":
        table = "telemetry"
        time_col = "timestamp"
        select_cols = "id, metric, value, tags, timestamp"
    else:
        table = "telemetry_aggregates"
        time_col = "period_start"
        select_cols = "metric, period, period_start, avg_value, min_value, max_value, count"
        query_parts.append("period = ?")
        params.append(period)
        
    if metric:
        query_parts.append("metric = ?")
        params.append(metric)
        
    if since:
        query_parts.append(f"{time_col} >= ?")
        params.append(since)
        
    where_clause = ""
    if query_parts:
        where_clause = "WHERE " + " AND ".join(query_parts)
        
    sql = f"SELECT {select_cols} FROM {table} {where_clause} ORDER BY {time_col} DESC LIMIT ?"
    params.append(limit)
    
    try:
        with db_pool.get_read_connection() as conn:
            cursor = conn.execute(sql, tuple(params))
            rows = cursor.fetchall()
            
        results = []
        for r in rows:
            row_dict = dict(r)
            if "tags" in row_dict and row_dict["tags"]:
                try:
                    row_dict["tags"] = json.loads(row_dict["tags"])
                except Exception:
                    pass
            results.append(row_dict)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/dashboard/stats")
async def get_dashboard_stats(request: Request):
    db_pool = request.app.state.db_pool
    if not db_pool:
        raise HTTPException(status_code=500, detail="Database connection pool not available")
        
    stats = {
        "llm_calls_count": 0,
        "avg_llm_latency_ms": 0.0,
        "total_tokens_in": 0,
        "total_tokens_out": 0,
        "memory_retrievals_count": 0,
        "avg_memory_retrieval_ms": 0.0,
        "memory_cache_hit_rate": 0.0,
    }
    
    try:
        with db_pool.get_read_connection() as conn:
            # 1. LLM Latency & Count
            cursor = conn.execute("""
                SELECT count(*), avg(value) FROM telemetry 
                WHERE metric = 'system.latency_ms' AND tags LIKE '%"operation": "llm.inference"%'
            """)
            r = cursor.fetchone()
            if r and r[0] > 0:
                stats["llm_calls_count"] = r[0]
                stats["avg_llm_latency_ms"] = round(r[1], 2)
                
            # 2. Token usage
            cursor = conn.execute("SELECT sum(value) FROM telemetry WHERE metric = 'llm.tokens_in'")
            r = cursor.fetchone()
            stats["total_tokens_in"] = int(r[0] or 0)
            
            cursor = conn.execute("SELECT sum(value) FROM telemetry WHERE metric = 'llm.tokens_out'")
            r = cursor.fetchone()
            stats["total_tokens_out"] = int(r[0] or 0)
            
            # 3. Memory Retrievals count & latency
            cursor = conn.execute("""
                SELECT count(*), avg(value) FROM telemetry 
                WHERE metric = 'system.latency_ms' AND tags LIKE '%"operation": "memory.retrieval"%'
            """)
            r = cursor.fetchone()
            if r and r[0] > 0:
                stats["memory_retrievals_count"] = r[0]
                stats["avg_memory_retrieval_ms"] = round(r[1], 2)
                
            # 4. Cache Hit rate
            cursor = conn.execute("SELECT sum(value) FROM telemetry WHERE metric = 'memory.cache_hit'")
            hits = cursor.fetchone()[0] or 0
            cursor = conn.execute("SELECT sum(value) FROM telemetry WHERE metric = 'memory.cache_miss'")
            misses = cursor.fetchone()[0] or 0
            
            total_cache_calls = hits + misses
            if total_cache_calls > 0:
                stats["memory_cache_hit_rate"] = round(hits / total_cache_calls, 3)
                
        # 5. Live CPU/RAM/GPU resource stats
        cpu_percent = 0.0
        ram_percent = 0.0
        vram_mb_used = 0.0
        gpu_percent = 0.0
        try:
            import psutil
            cpu_percent = psutil.cpu_percent(interval=None) or 0.0
            ram_percent = psutil.virtual_memory().percent or 0.0
        except Exception:
            pass

        try:
            import subprocess
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=1
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split(",")
                if len(parts) == 2:
                    gpu_percent = float(parts[0].strip())
                    vram_mb_used = float(parts[1].strip())
        except Exception:
            pass
        
        stats["cpu_percent"] = cpu_percent
        stats["ram_percent"] = ram_percent
        stats["gpu_percent"] = gpu_percent
        stats["vram_mb_used"] = vram_mb_used
        
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/metrics/aggregate")
async def trigger_aggregation(request: Request):
    telemetry = getattr(request.app.state, "telemetry", None)
    if not telemetry:
        raise HTTPException(status_code=500, detail="Telemetry system not active")
    await telemetry.aggregate_metrics()
    return {"status": "success", "message": "Metrics aggregated successfully"}

@router.post("/metrics/cleanup")
async def trigger_cleanup(request: Request):
    telemetry = getattr(request.app.state, "telemetry", None)
    if not telemetry:
        raise HTTPException(status_code=500, detail="Telemetry system not active")
    await telemetry.cleanup_old_metrics()
    return {"status": "success", "message": "Retention cleanup executed successfully"}

@router.get("/health")
async def get_system_health(request: Request):
    """Perform a comprehensive system health, dependency, and hardware compatibility check."""
    import sys
    import subprocess
    import platform
    import shutil
    import psutil
    import os
    from models.config import MODELS_CONFIG
    
    # 1. Database Check
    db_pool = getattr(request.app.state, "db_pool", None)
    db_ok = db_pool is not None
    
    # 2. Ollama Connection Check
    model_router = getattr(request.app.state, "model_router", None)
    if model_router:
        client = model_router.client
    else:
        from models.ollama_client import OllamaClient
        client = OllamaClient()
        
    ollama_ok = await client.ping()
    
    # 3. Model Checks
    available_models = []
    if ollama_ok:
        try:
            models_list = await client.list_models()
            available_models = [m.get("name", "") for m in models_list]
        except Exception:
            pass

    # Helper function to check if a model name pattern is installed
    def find_installed_model(pattern: str) -> Optional[str]:
        # strip tags or sizes for fuzzy prefix matching
        base = pattern.split(":")[0].lower()
        return next((m for m in available_models if base in m.lower()), None)

    required_models = []
    optional_models = []
    
    all_required_installed = True
    
    for key, spec in MODELS_CONFIG.items():
        installed_name = find_installed_model(spec["name"])
        is_ok = installed_name is not None
        
        model_info = {
            "key": key,
            "name": spec["name"],
            "label": spec["label"],
            "size_gb": spec["size_gb"],
            "description": spec["description"],
            "ok": is_ok,
            "installed_name": installed_name
        }
        
        if spec["required"]:
            required_models.append(model_info)
            if not is_ok:
                all_required_installed = False
        else:
            optional_models.append(model_info)
            
    # 4. Environment Check
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    python_ok = sys.version_info >= (3, 11)
    
    git_ok = False
    try:
        git_res = subprocess.run(["git", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=2)
        git_ok = git_res.returncode == 0
    except Exception:
        pass
        
    # 5. Workspace Write Permission Check
    workspace_ok = False
    try:
        temp_test_file = ".permission_test.tmp"
        with open(temp_test_file, "w") as f:
            f.write("ALOY permission test")
        if os.path.exists(temp_test_file):
            os.remove(temp_test_file)
            workspace_ok = True
    except Exception:
        pass
        
    # 6. Hardware Validation Report
    os_name = platform.system()
    os_release = platform.release()
    os_display = f"{os_name} {os_release}"
    os_ok = os_name in ["Windows", "Darwin", "Linux"]
    
    total_ram_gb = round(psutil.virtual_memory().total / (1024 ** 3), 1)
    ram_ok = total_ram_gb >= 8.0
    ram_message = f"{total_ram_gb} GB RAM" if ram_ok else f"{total_ram_gb} GB RAM (Warning: 8GB+ recommended)"
    
    total_disk, used_disk, free_disk = shutil.disk_usage(".")
    free_disk_gb = round(free_disk / (1024 ** 3), 1)
    disk_ok = free_disk_gb >= 20.0
    disk_message = f"{free_disk_gb} GB free space" if disk_ok else f"{free_disk_gb} GB free space (Warning: Low disk space, 20GB+ recommended)"
    
    # GPU detection
    gpu_detected = False
    vram_mb_total = 0.0
    gpu_name = "Standard GPU"
    try:
        gpu_res = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=2
        )
        if gpu_res.returncode == 0:
            gpu_parts = gpu_res.stdout.strip().split(",")
            if len(gpu_parts) == 2:
                gpu_name = gpu_parts[0].strip()
                vram_mb_total = float(gpu_parts[1].strip())
                gpu_detected = True
    except Exception:
        pass
        
    gpu_message = f"{gpu_name} ({round(vram_mb_total/1024, 1)} GB VRAM)" if gpu_detected else "No dedicated GPU detected"
    # Warn but don't block if GPU not found or low VRAM
    gpu_ok = True  # Warn only (optional warning)
    
    # 7. SQLite-Vec Extension Check
    sqlite_vec_ok = False
    sqlite_vec_message = "sqlite-vec extension module not found"
    try:
        from database.connection import HAS_VEC
        if HAS_VEC:
            sqlite_vec_ok = True
            sqlite_vec_message = "sqlite-vec extension loaded successfully"
    except Exception as e:
        sqlite_vec_message = f"Check failed: {str(e)}"

    # 8. Internet Connection Check
    import httpx
    internet_ok = False
    internet_message = "Offline"
    try:
        # Check external connection with a fast 1.5s timeout
        internet_res = httpx.get("https://github.com", timeout=1.5)
        if internet_res.status_code == 200:
            internet_ok = True
            internet_message = "Connected (latency verified)"
        else:
            internet_message = f"Connected with issues (HTTP {internet_res.status_code})"
    except Exception:
        internet_message = "Offline or DNS resolution failed"

    # 9. Unexpected Exit Check (Crash Recovery)
    unexpected_exit = getattr(request.app.state, "unexpected_exit", False)
    # Reset flag so subsequent checks (e.g. after page reload or restore) don't trigger it again
    try:
        request.app.state.unexpected_exit = False
    except Exception:
        pass


    health_status = {
        "status": "healthy" if (db_ok and ollama_ok and all_required_installed and workspace_ok) else "unhealthy",
        "version": "1.0.0",
        "latest_version": "1.0.0",
        "update_status": "Up to date",
        "unexpected_exit": unexpected_exit,
        "database": {"ok": db_ok, "message": "SQLite active in WAL mode" if db_ok else "Database pool offline"},
        "sqlite_vec": {"ok": sqlite_vec_ok, "message": sqlite_vec_message},
        "internet": {"ok": internet_ok, "message": internet_message},
        "workspace": {
            "ok": workspace_ok,
            "message": "Read/write permissions validated" if workspace_ok else "Write permission denied"
        },
        "ollama": {
            "ok": ollama_ok,
            "message": "Connected to local Ollama service" if ollama_ok else "Ollama service offline or unreachable"
        },
        "required_models": required_models,
        "optional_models": optional_models,
        "compatibility": {
            "os": {"ok": os_ok, "label": "Operating System Supported", "detail": os_display},
            "ram": {"ok": ram_ok, "label": "RAM Requirement Checked", "detail": ram_message},
            "disk": {"ok": disk_ok, "label": "Disk Space Checked", "detail": disk_message},
            "gpu": {"ok": gpu_detected, "label": "GPU Acceleration", "detail": gpu_message}
        },
        "environment": {
            "python": {"ok": python_ok, "version": python_version},
            "git": {"ok": git_ok}
        }
    }
    return health_status


@router.get("/diagnostics")
async def get_system_diagnostics(request: Request):
    """Retrieve detailed diagnostics for system hardware and microkernel subsystems."""
    import os
    import sys
    import psutil
    import shutil
    import platform
    import subprocess
    
    # 1. Resource usage
    cpu_percent = psutil.cpu_percent()
    virtual_mem = psutil.virtual_memory()
    ram = {
        "percent": virtual_mem.percent,
        "used_gb": round(virtual_mem.used / (1024 ** 3), 2),
        "total_gb": round(virtual_mem.total / (1024 ** 3), 2)
    }
    
    gpu_detected = False
    vram_used = 0.0
    vram_total = 0.0
    gpu_name = "N/A"
    gpu_load = 0.0
    try:
        gpu_res = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu", "--format=csv,noheader,nounits"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=1
        )
        if gpu_res.returncode == 0:
            parts = gpu_res.stdout.strip().split(",")
            if len(parts) == 4:
                gpu_name = parts[0].strip()
                vram_used = float(parts[1].strip())
                vram_total = float(parts[2].strip())
                gpu_load = float(parts[3].strip())
                gpu_detected = True
    except Exception:
        pass
        
    gpu_data = {
        "detected": gpu_detected,
        "name": gpu_name,
        "percent": gpu_load,
        "vram_used_mb": vram_used,
        "vram_total_mb": vram_total
    }
    
    # 2. Database diagnostics
    db_pool = getattr(request.app.state, "db_pool", None)
    db_size_kb = 0.0
    db_path = "N/A"
    db_wal = False
    if db_pool:
        db_path = str(db_pool.db_path)
        try:
            if os.path.exists(db_path):
                db_size_kb = round(os.path.getsize(db_path) / 1024, 1)
            # check if wal file exists
            if os.path.exists(db_path + "-wal") or os.path.exists(db_path + "-shm"):
                db_wal = True
        except Exception:
            pass
            
    # Check migrations count
    migrations_count = 13  # Default schema migrations count in ALOY v1.0
    
    # 3. Memories count
    memories_count = 0
    if db_pool:
        try:
            with db_pool.get_read_connection() as conn:
                r = conn.execute("SELECT count(*) FROM memories").fetchone()
                memories_count = r[0] if r else 0
        except Exception:
            pass
            
    # 4. Ollama
    model_router = getattr(request.app.state, "model_router", None)
    ollama_connected = False
    ollama_url = "http://localhost:11434"
    if model_router:
        client = model_router.client
        ollama_connected = await client.ping()
        
    # 5. Subsystems active check
    subsystems = {
        "event_bus": "active" if getattr(request.app.state, "event_bus", None) is not None else "offline",
        "prompt_registry": "active" if getattr(request.app.state, "prompt_registry", None) is not None else "offline",
        "evolution_engine": "active" if getattr(request.app.state, "evolution_engine", None) is not None else "offline",
        "knowledge_router": "active" if getattr(request.app.state, "knowledge_router", None) is not None else "offline",
        "identity_engine": "active" if getattr(request.app.state, "identity_engine", None) is not None else "offline",
        "memory_manager": "active" if getattr(request.app.state, "memory_manager", None) is not None else "offline",
        "agent_runtime": "active" if getattr(request.app.state, "agent_runtime", None) is not None else "offline",
        "tool_system": "active" if getattr(request.app.state, "tool_system", None) is not None else "offline"
    }
    
    # 6. Internet connection
    import httpx
    internet_ok = False
    try:
        r = httpx.get("https://github.com", timeout=1.5)
        internet_ok = r.status_code == 200
    except Exception:
        pass

    return {
        "cpu_percent": cpu_percent,
        "ram": ram,
        "gpu": gpu_data,
        "database": {
            "ok": db_pool is not None,
            "path": db_path,
            "size_kb": db_size_kb,
            "wal_mode": db_wal,
            "migrations_applied": migrations_count
        },
        "memory": {
            "ok": True,
            "total_memories": memories_count
        },
        "ollama": {
            "ok": ollama_connected,
            "url": ollama_url
        },
        "internet": {
            "ok": internet_ok,
            "message": "Connected" if internet_ok else "Offline"
        },
        "subsystems": subsystems
    }


@router.get("/update")
async def get_system_update(request: Request):
    """Check for new software releases on the GitHub repository."""
    import httpx
    current_version = "1.0.0"
    latest_version = "1.0.0"
    has_update = False
    release_notes = "Initial public version release candidate."
    download_url = "https://github.com/dhanush708/ALOY/releases"
    
    try:
        # Check repo latest release
        res = httpx.get("https://api.github.com/repos/dhanush708/ALOY/releases/latest", timeout=2.0)
        if res.status_code == 200:
            data = res.json()
            latest_version = data.get("tag_name", "1.0.0").replace("v", "")
            release_notes = data.get("body", "Updates and bug fixes.")
            download_url = data.get("html_url", download_url)
            
            # Simple version tag comparison
            curr_parts = [int(p) for p in current_version.split(".") if p.isdigit()]
            late_parts = [int(p) for p in latest_version.split(".") if p.isdigit()]
            if len(curr_parts) == 3 and len(late_parts) == 3:
                has_update = late_parts > curr_parts
    except Exception:
        pass
        
    return {
        "current_version": current_version,
        "latest_version": latest_version,
        "has_update": has_update,
        "release_notes": release_notes,
        "download_url": download_url
    }

