import os
import re
import json
import logging
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)

class DependencyResolver:
    """Parses project workspaces to resolve dependency versions."""

    def resolve_versions(self, workspace_path: str | Path) -> Dict[str, str]:
        """Scans the workspace directory to resolve versions of dependencies."""
        path = Path(workspace_path)
        versions = {}

        if not path.exists() or not path.is_dir():
            return versions

        # 1. Parse package.json (Node)
        package_json = path / "package.json"
        if package_json.exists():
            try:
                with open(package_json, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for dep_type in ["dependencies", "devDependencies"]:
                        for pkg, ver_spec in data.get(dep_type, {}).items():
                            # clean version specifier (e.g. ^1.2.3 -> 1.2.3)
                            clean_ver = re.sub(r'^[~^>=<]+', '', str(ver_spec)).strip()
                            if clean_ver:
                                versions[pkg.lower()] = clean_ver
            except Exception as e:
                logger.warning(f"Failed to parse package.json in {workspace_path}: {e}")

        # 2. Parse requirements.txt (Python)
        reqs_txt = path / "requirements.txt"
        if reqs_txt.exists():
            try:
                with open(reqs_txt, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        # Match name and version, e.g. fastapi==0.110.1 or fastapi>=0.100.0
                        parts = re.split(r'(==|>=|<=|~=|!=|>|<)', line)
                        if parts:
                            pkg = parts[0].strip().lower()
                            pkg = pkg.split("[")[0].strip()
                            if len(parts) > 2:
                                ver = parts[2].split(";")[0].strip()
                                ver = ver.split("#")[0].strip()
                                versions[pkg] = ver
                            else:
                                versions[pkg] = "unknown"
            except Exception as e:
                logger.warning(f"Failed to parse requirements.txt in {workspace_path}: {e}")

        # 3. Parse pyproject.toml (Python Poetry/PEP517)
        pyproject = path / "pyproject.toml"
        if pyproject.exists():
            try:
                with open(pyproject, "r", encoding="utf-8") as f:
                    content = f.read()
                lines = content.splitlines()
                in_dependencies = False
                for line in lines:
                    line = line.strip()
                    if line.startswith("[") and "dependencies" in line:
                        in_dependencies = True
                        continue
                    elif line.startswith("[") and in_dependencies:
                        in_dependencies = False
                    
                    if in_dependencies and "=" in line:
                        parts = line.split("=", 1)
                        pkg = parts[0].strip().strip('"').strip("'").lower()
                        val = parts[1].strip()
                        if val.startswith("{"):
                            v_match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', val)
                            if v_match:
                                ver = v_match.group(1)
                                versions[pkg] = re.sub(r'^[~^>=<]+', '', ver).strip()
                        else:
                            ver = val.strip('"').strip("'")
                            versions[pkg] = re.sub(r'^[~^>=<]+', '', ver).strip()
            except Exception as e:
                logger.warning(f"Failed to parse pyproject.toml in {workspace_path}: {e}")

        return versions
