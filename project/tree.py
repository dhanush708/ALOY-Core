import os
from pathlib import Path
import fnmatch
from typing import Dict, Any, List, Optional


class DirectoryTreeBuilder:
    """Recursively builds file trees, filtering out excluded patterns."""

    @staticmethod
    def should_exclude(path: Path, root_path: Path, exclude_patterns: List[str]) -> bool:
        # Check both relative path and name
        try:
            rel_path = path.relative_to(root_path)
            rel_str = rel_path.as_posix()
        except ValueError:
            rel_str = path.name

        name = path.name

        for pattern in exclude_patterns:
            # Standard fnmatch check
            if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(rel_str, pattern):
                return True
            # Subdirectory match (e.g. node_modules should match node_modules/foo)
            if "/" in pattern or "\\" in pattern:
                # normalize pattern to forward slashes
                norm_pat = pattern.replace("\\", "/").strip("/")
                if rel_str.startswith(norm_pat + "/") or rel_str == norm_pat:
                    return True
            else:
                # If pattern matches any individual directory segment
                for part in rel_path.parts:
                    if fnmatch.fnmatch(part, pattern):
                        return True
        return False

    @classmethod
    def build(cls, root_path: str | Path, exclude_patterns: Optional[List[str]] = None) -> Dict[str, Any]:
        """Builds a nested dictionary representation of the directory tree."""
        root = Path(root_path).resolve()
        if not root.exists():
            raise FileNotFoundError(f"Root path does not exist: {root}")

        if exclude_patterns is None:
            exclude_patterns = []

        return cls._build_node(root, root, exclude_patterns)

    @classmethod
    def _build_node(cls, current_path: Path, root_path: Path, exclude_patterns: List[str]) -> Dict[str, Any]:
        name = current_path.name if current_path != root_path else current_path.resolve().name
        
        if current_path.is_file():
            try:
                size = current_path.stat().st_size
            except OSError:
                size = 0
            return {
                "name": name,
                "type": "file",
                "path": current_path.relative_to(root_path).as_posix(),
                "size": size
            }

        # It is a directory
        children = []
        try:
            for item in sorted(current_path.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
                if cls.should_exclude(item, root_path, exclude_patterns):
                    continue
                children.append(cls._build_node(item, root_path, exclude_patterns))
        except PermissionError:
            # Handle permission errors gracefully
            pass

        return {
            "name": name,
            "type": "directory",
            "path": current_path.relative_to(root_path).as_posix() if current_path != root_path else "",
            "children": children
        }

    @classmethod
    def build_flat(cls, root_path: str | Path, exclude_patterns: Optional[List[str]] = None) -> List[Path]:
        """Returns a flat list of Path objects for all non-excluded files in the tree."""
        root = Path(root_path).resolve()
        if not root.exists():
            raise FileNotFoundError(f"Root path does not exist: {root}")

        if exclude_patterns is None:
            exclude_patterns = []

        files = []
        cls._build_flat_recursive(root, root, exclude_patterns, files)
        return files

    @classmethod
    def _build_flat_recursive(cls, current_path: Path, root_path: Path, exclude_patterns: List[str], result: List[Path]):
        if cls.should_exclude(current_path, root_path, exclude_patterns):
            return

        if current_path.is_file():
            result.append(current_path)
            return

        # It's a directory
        try:
            for item in current_path.iterdir():
                cls._build_flat_recursive(item, root_path, exclude_patterns, result)
        except PermissionError:
            pass

    @classmethod
    def to_string(cls, tree: Dict[str, Any], indent: str = "", is_last: bool = True) -> str:
        """Converts a nested tree dictionary into a visual ASCII/Unicode tree string."""
        lines = []
        name = tree["name"]
        
        if not indent:
            lines.append(f"{name}/")
        else:
            connector = "└── " if is_last else "├── "
            display_name = f"{name}/" if tree["type"] == "directory" else name
            lines.append(f"{indent}{connector}{display_name}")

        if tree["type"] == "directory" and "children" in tree:
            children = tree["children"]
            child_count = len(children)
            new_indent = indent + ("    " if is_last else "│   ")
            for idx, child in enumerate(children):
                last_child = (idx == child_count - 1)
                lines.append(cls.to_string(child, new_indent, last_child))

        return "\n".join(lines)
