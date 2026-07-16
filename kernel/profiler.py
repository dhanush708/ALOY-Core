import time
from pathlib import Path
import os
import json
import logging

logger = logging.getLogger(__name__)

class StartupProfiler:
    def __init__(self):
        self.stages = {}
        self.start_time = time.perf_counter()
        self.log_file = Path(os.environ.get("APPDATA", Path.home())) / "ALOY" / "logs" / "startup_profile.json"

    def record(self, stage: str, duration_ms: float):
        self.stages[stage] = round(duration_ms, 2)
        logger.info(f"[STARTUP_PROFILE] {stage}: {self.stages[stage]} ms")
        self._write_to_log()

    def get_duration(self, start_t: float) -> float:
        return (time.perf_counter() - start_t) * 1000.0

    def _write_to_log(self):
        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_file, "w") as f:
                json.dump(self.stages, f, indent=2)
        except Exception:
            pass

profiler = StartupProfiler()
