import ast
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class ASTInspector:
    """Uses Python's ast module to extract class signatures, functions, imports, etc."""

    @staticmethod
    def inspect_code(code: str) -> Dict[str, Any]:
        """Parses Python source code and extracts elements, checking for syntax validity."""
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return {
                "syntax_valid": False,
                "error": f"SyntaxError at line {e.lineno}, offset {e.offset}: {e.text.strip() if e.text else ''}",
                "classes": [],
                "functions": [],
                "imports": [],
            }

        classes = []
        functions = []
        imports = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases = []
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        bases.append(base.id)
                    elif isinstance(base, ast.Attribute):
                        bases.append(f"{base.value.id if hasattr(base.value, 'id') else ''}.{base.attr}")

                docstring = ast.get_docstring(node)
                classes.append({
                    "name": node.name,
                    "bases": bases,
                    "lineno": node.lineno,
                    "docstring": docstring or "",
                })
            elif isinstance(node, ast.FunctionDef):
                args = [arg.arg for arg in node.args.args]
                docstring = ast.get_docstring(node)
                functions.append({
                    "name": node.name,
                    "args": args,
                    "lineno": node.lineno,
                    "docstring": docstring or "",
                })
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append({
                        "module": alias.name,
                        "name": alias.asname or alias.name,
                        "lineno": node.lineno,
                    })
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imports.append({
                        "module": f"{node.module}.{alias.name}" if node.module else alias.name,
                        "name": alias.asname or alias.name,
                        "lineno": node.lineno,
                    })

        return {
            "syntax_valid": True,
            "error": None,
            "classes": classes,
            "functions": functions,
            "imports": imports,
        }

    @staticmethod
    def inspect_file(file_path: str) -> Dict[str, Any]:
        """Reads a file and returns its AST structure."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                code = f.read()
            return ASTInspector.inspect_code(code)
        except Exception as e:
            return {
                "syntax_valid": False,
                "error": f"Failed to read file: {e}",
                "classes": [],
                "functions": [],
                "imports": [],
            }
