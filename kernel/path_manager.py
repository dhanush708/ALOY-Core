"""
ALOY Core — Centralized Path & Runtime Environment Manager

Provides a single source of truth for all application paths, resource loading,
user data directories (%LOCALAPPDATA%\\ALOY\\), frozen mode detection, log rotation,
and startup environmental validation.
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Tuple, List, Optional


class PathManager:
    """Centralized path management system for ALOY Desktop Application."""

    def __init__(self, override_app_data: Optional[Path] = None):
        self._override_app_data = override_app_data

    @property
    def is_frozen(self) -> bool:
        """Return True if running in packaged PyInstaller frozen mode."""
        return getattr(sys, "frozen", False)

    @property
    def app_root(self) -> Path:
        """Application install root directory containing the main executable."""
        if self.is_frozen:
            return Path(sys.executable).parent.resolve()
        return Path(__file__).resolve().parent.parent

    @property
    def resource_root(self) -> Path:
        """Root directory for read-only bundled application resources."""
        if self.is_frozen and hasattr(sys, "_MEIPASS"):
            return Path(getattr(sys, "_MEIPASS")).resolve()
        return self.app_root

    @property
    def app_data_root(self) -> Path:
        """Per-user writable directory under %LOCALAPPDATA%\\ALOY\\."""
        if self._override_app_data:
            return self._override_app_data.resolve()
        
        base_dir = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if not base_dir:
            base_dir = Path.home()
        return (Path(base_dir) / "ALOY").resolve()

    @property
    def config_dir(self) -> Path:
        """Directory for user configuration files."""
        return self.app_data_root / "config"

    @property
    def data_dir(self) -> Path:
        """Directory for user SQLite database and vector index stores."""
        return self.app_data_root / "data"

    @property
    def logs_dir(self) -> Path:
        """Directory for application log files."""
        return self.app_data_root / "logs"

    @property
    def cache_dir(self) -> Path:
        """Directory for temporary search and document intelligence caches."""
        return self.app_data_root / "cache"

    @property
    def downloads_dir(self) -> Path:
        """Directory for user export outputs and downloaded artifacts."""
        return self.app_data_root / "downloads"

    @property
    def temp_dir(self) -> Path:
        """Directory for transient runtime scratch files."""
        return self.app_data_root / "temp"

    # Application Read-Only Bundled Asset Paths
    @property
    def assets_dir(self) -> Path:
        """Directory for bundled graphics, icons, and tokenizers."""
        return self.resource_root / "assets"

    @property
    def icons_dir(self) -> Path:
        """Directory for application icons."""
        return self.assets_dir / "icons"

    @property
    def static_dir(self) -> Path:
        """Directory for frontend SPA static web files."""
        return self.resource_root / "static"

    @property
    def models_dir(self) -> Path:
        """Directory for bundled model definitions and weights."""
        return self.resource_root / "models"

    @property
    def tiktoken_cache_dir(self) -> Path:
        """Directory for bundled BPE tiktoken offline tokenizer files."""
        return self.assets_dir / "tiktoken_cache"

    # Specific Database File Paths
    @property
    def db_path(self) -> Path:
        """Primary SQLite user database file path."""
        return self.data_dir / "aloy.db"

    @property
    def trace_db_path(self) -> Path:
        """Telemetry and memory trace database file path."""
        return self.data_dir / "trace.db"

    def ensure_directories(self) -> None:
        """Safely create all required writable AppData directories on first launch."""
        writable_dirs = [
            self.app_data_root,
            self.config_dir,
            self.data_dir,
            self.logs_dir,
            self.cache_dir,
            self.downloads_dir,
            self.temp_dir,
        ]
        for folder in writable_dirs:
            folder.mkdir(parents=True, exist_ok=True)

    def get_resource_path(self, relative_path: str | Path) -> Path:
        """
        Resolve absolute path to a bundled application resource file.
        Prevents raw string path operations and enforces cross-platform safety.
        """
        rel = Path(relative_path)
        resolved = (self.resource_root / rel).resolve()
        return resolved

    def get_user_data_path(self, relative_path: str | Path) -> Path:
        """Resolve absolute path to a writable file inside %LOCALAPPDATA%\\ALOY\\."""
        rel = Path(relative_path)
        resolved = (self.app_data_root / rel).resolve()
        return resolved

    def validate_environment(self) -> Tuple[bool, List[str]]:
        """
        Perform pre-flight environmental validation prior to application boot.
        Verifies writable permissions, directory structures, and critical assets.
        """
        errors: List[str] = []

        # 1. Ensure user AppData directories can be created
        try:
            self.ensure_directories()
        except Exception as e:
            errors.append(f"Failed to create AppData directory structure: {e}")
            return False, errors

        # 2. Check write permissions in AppData directory
        test_file = self.temp_dir / ".write_test.tmp"
        try:
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink(missing_ok=True)
        except Exception as e:
            errors.append(f"AppData directory '%LOCALAPPDATA%\\ALOY\\' is not writable: {e}")

        # 3. Check critical bundled resources exist
        critical_resources = [
            ("Static UI Index", self.static_dir / "index.html"),
            ("Application Icon", self.icons_dir / "aloy.ico"),
        ]

        for name, resource_path in critical_resources:
            if not resource_path.exists():
                errors.append(f"Missing critical bundled asset '{name}' at path: {resource_path}")

        return (len(errors) == 0, errors)

    def setup_logging(
        self,
        log_filename: str = "aloy.log",
        max_bytes: int = 10 * 1024 * 1024,
        backup_count: int = 5,
        level: int = logging.INFO
    ) -> logging.Logger:
        """
        Configure rotating log file handler writing to %LOCALAPPDATA%\\ALOY\\logs\\.
        Max size: 10 MB per file, retaining up to 5 historical backup files.
        """
        self.ensure_directories()
        log_file_path = self.logs_dir / log_filename

        logger = logging.getLogger()
        logger.setLevel(level)

        # Remove duplicate existing handlers to prevent log duplication
        for handler in list(logger.handlers):
            if isinstance(handler, RotatingFileHandler):
                logger.removeHandler(handler)

        formatter = logging.formatters.Formatter(
            fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ) if hasattr(logging, "formatters") else logging.Formatter(
            fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )

        rotating_handler = RotatingFileHandler(
            filename=str(log_file_path),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8"
        )
        rotating_handler.setFormatter(formatter)
        logger.addHandler(rotating_handler)

        return logger


# Global singleton instance for convenient application-wide access
paths = PathManager()
