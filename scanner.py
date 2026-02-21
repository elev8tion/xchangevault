import os
from pathlib import Path
from typing import Dict, Any, Tuple, List


# Default folders/files to exclude from scans
DEFAULT_EXCLUDES = [
    ".git", ".github", ".gitlab", ".svn", ".hg",
    "node_modules", "dist", "build", ".next", ".nuxt", ".cache", ".turbo",
    "venv", ".venv", "env", ".mypy_cache", ".pytest_cache", "__pycache__",
    ".idea", ".vscode", ".DS_Store", "Thumbs.db",
]


def is_excluded(name: str) -> bool:
    return name in DEFAULT_EXCLUDES


def detect_stack(root: Path) -> Dict[str, Any]:
    indicators = {
        "node": (root / "package.json").exists(),
        "python": (root / "pyproject.toml").exists() or (root / "setup.py").exists(),
        "go": (root / "go.mod").exists(),
        "rust": (root / "Cargo.toml").exists(),
        "java": any((root / d).exists() for d in ["pom.xml", "build.gradle", "build.gradle.kts"]),
        "dotnet": any((root / d).exists() for d in ["*.csproj", "global.json"]),
    }
    langs = []
    if indicators["node"]:
        langs.append("node")
    if indicators["python"]:
        langs.append("python")
    if indicators["go"]:
        langs.append("go")
    if indicators["rust"]:
        langs.append("rust")
    if indicators["java"]:
        langs.append("java")
    if indicators["dotnet"]:
        langs.append("dotnet")
    return {"indicators": indicators, "detected": langs}


def _walk(root: Path) -> Tuple[Dict[str, Any], Dict[str, int]]:
    # returns tree and stats
    root = root.resolve()
    stats = {"files": 0, "dirs": 0}

    def build_node(path: Path) -> Dict[str, Any]:
        if path.is_dir():
            stats["dirs"] += 1
            children = []
            for name in sorted(os.listdir(path)):
                if is_excluded(name):
                    continue
                child = path / name
                # skip symlinked dirs/files to avoid surprises
                if child.is_symlink():
                    continue
                children.append(build_node(child))
            return {
                "type": "dir",
                "name": path.name,
                "path": str(path.relative_to(root)),
                "children": children,
            }
        else:
            stats["files"] += 1
            return {
                "type": "file",
                "name": path.name,
                "path": str(path.relative_to(root)),
                "size": path.stat().st_size,
            }

    tree = build_node(root)
    return tree, stats


def flatten_files(tree: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    def walk(n: Dict[str, Any]):
        if n["type"] == "file":
            out.append(n["path"])  # already relative
        else:
            for c in n.get("children", []):
                walk(c)
    walk(tree)
    return out


def scan_project(root: Path):
    tree, stats = _walk(root)
    stack = detect_stack(root)
    return tree, stats, stack

