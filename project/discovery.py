import os
from pathlib import Path
from typing import List, Optional

PROJECT_INDICATORS = [
    ".aloy/manifest.yaml",
    ".git",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "requirements.txt",
    "go.mod",
    "CMakeLists.txt",
    "Makefile"
]

IGNORE_SCAN_DIRS = {
    "node_modules",
    "venv",
    ".venv",
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".aloy",
    "dist",
    "build"
}


class ProjectDiscovery:
    """Auto-detects project roots using heuristics and scans parent/child directories."""

    @staticmethod
    def is_project_root(path: Path) -> bool:
        """Checks if a specific path contains any project indicators."""
        if not path.is_dir():
            return False

        # First priority: explicit ALOY manifest
        if (path / ".aloy" / "manifest.yaml").exists():
            return True

        # Other standard project markers
        for indicator in PROJECT_INDICATORS:
            if "/" in indicator:
                if (path / Path(indicator)).exists():
                    return True
            else:
                if (path / indicator).exists():
                    return True
        return False

    @classmethod
    def find_project_root(cls, start_path: str | Path) -> Optional[Path]:
        """Traverses up from start_path to find the nearest project root."""
        current = Path(start_path).resolve()
        
        # If it's a file, start from its directory
        if current.is_file():
            current = current.parent

        # Loop upwards
        while True:
            # First check if this is an explicit ALOY project
            if (current / ".aloy" / "manifest.yaml").exists():
                return current
                
            # Then check other indicators
            if cls.is_project_root(current):
                return current
                
            # Stop if we reached the root of the file system
            parent = current.parent
            if parent == current:
                break
            current = parent
            
        return None

    @classmethod
    def scan_for_projects(cls, search_root: str | Path, max_depth: int = 4) -> List[Path]:
        """Scans downward from search_root to find project roots."""
        root = Path(search_root).resolve()
        if not root.exists() or not root.is_dir():
            return []

        found_roots = []
        cls._scan_recursive(root, 0, max_depth, found_roots)
        return found_roots

    @classmethod
    def _scan_recursive(cls, current_dir: Path, current_depth: int, max_depth: int, results: List[Path]):
        if current_depth > max_depth:
            return

        if cls.is_project_root(current_dir):
            results.append(current_dir)
            # Once we find a project root, we stop recursing into its children
            # to avoid nesting projects unless explicitly separated.
            return

        try:
            for item in current_dir.iterdir():
                if item.is_dir() and item.name not in IGNORE_SCAN_DIRS:
                    cls._scan_recursive(item, current_depth + 1, max_depth, results)
        except PermissionError:
            pass
