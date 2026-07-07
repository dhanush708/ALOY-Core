import os
from pathlib import Path
import yaml
from typing import Dict, Any, List

DEFAULT_EXCLUDE_PATTERNS = [
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".aloy",
    "node_modules",
    "venv",
    ".venv",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "*.db",
    "*.db-journal",
    "*.db-wal",
]


class ManifestLoader:
    """Loads, validates, and writes project manifests (.aloy/manifest.yaml)."""

    @staticmethod
    def get_manifest_path(path_or_dir: str | Path) -> Path:
        path = Path(path_or_dir)
        if path.is_dir():
            return path / ".aloy" / "manifest.yaml"
        return path

    @classmethod
    def load(cls, path_or_dir: str | Path) -> Dict[str, Any]:
        manifest_path = cls.get_manifest_path(path_or_dir)
        if not manifest_path.exists():
            # Return default manifest based on the directory name if possible
            dir_name = Path(path_or_dir).name if Path(path_or_dir).is_dir() else Path(path_or_dir).parent.name
            return cls.get_default_manifest(dir_name)

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            # Fallback to default in case of error
            dir_name = Path(path_or_dir).name if Path(path_or_dir).is_dir() else Path(path_or_dir).parent.name
            return cls.get_default_manifest(dir_name)

        return cls.normalize(data, manifest_path.parent.parent.name)

    @classmethod
    def save(cls, path_or_dir: str | Path, data: Dict[str, Any]) -> None:
        manifest_path = cls.get_manifest_path(path_or_dir)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Ensure correct structure
        normalized = cls.normalize(data, manifest_path.parent.parent.name)
        
        with open(manifest_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(normalized, f, default_flow_style=False, sort_keys=False)

    @classmethod
    def init_manifest(cls, dir_path: str | Path, name: str, description: str = "") -> Path:
        manifest_path = cls.get_manifest_path(dir_path)
        if manifest_path.exists():
            return manifest_path
            
        data = {
            "project": {
                "name": name,
                "description": description,
                "version": "0.1.0",
                "exclude_patterns": DEFAULT_EXCLUDE_PATTERNS.copy(),
                "metadata": {}
            }
        }
        cls.save(manifest_path, data)
        return manifest_path

    @classmethod
    def get_default_manifest(cls, name: str) -> Dict[str, Any]:
        return {
            "project": {
                "name": name,
                "description": "",
                "version": "0.1.0",
                "exclude_patterns": DEFAULT_EXCLUDE_PATTERNS.copy(),
                "metadata": {}
            }
        }

    @classmethod
    def normalize(cls, data: Dict[str, Any], default_name: str) -> Dict[str, Any]:
        """Ensures the manifest matches the required structure and defaults."""
        if not isinstance(data, dict):
            data = {}
        
        project = data.get("project")
        if not isinstance(project, dict):
            project = {}
            
        name = project.get("name") or default_name
        description = project.get("description") or ""
        version = project.get("version") or "0.1.0"
        
        excludes = project.get("exclude_patterns")
        if not isinstance(excludes, list):
            excludes = DEFAULT_EXCLUDE_PATTERNS.copy()
        else:
            # Ensure they are strings
            excludes = [str(x) for x in excludes]
            
        metadata = project.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            
        return {
            "project": {
                "name": name,
                "description": description,
                "version": version,
                "exclude_patterns": excludes,
                "metadata": metadata
            }
        }
