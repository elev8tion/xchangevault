import os
import re
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



def scan_imports(root: Path, rel_paths: list) -> dict:
    """Scan files for relative imports and warn about missing ones."""
    rel_set = set(rel_paths)
    warnings: dict = {}

    for rel in rel_paths:
        path = root / rel
        suffix = path.suffix.lower()
        file_warnings = []

        try:
            text = path.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue

        if suffix == '.py':
            for m in re.finditer(r'from \.([\.\w]*)', text):
                mod = m.group(1)
                mod_parts = mod.split('.') if mod else []
                base_dir = Path(rel).parent
                candidate = base_dir
                for part in mod_parts:
                    if part:
                        candidate = candidate / part
                candidates = [
                    str(candidate) + '.py',
                    str(candidate / '__init__.py'),
                ]
                found = any(c in rel_set for c in candidates)
                if not found:
                    file_warnings.append(f"{rel} imports .{mod} (not in selection)")

        elif suffix in ('.js', '.ts', '.jsx', '.tsx', '.mjs', '.cjs'):
            base_dir = Path(rel).parent
            seen = set()
            js_patterns = [
                r"""from ['"](\./[^'"]+)['"]""",
                r"""from ['"](\.\./[^'"]+)['"]""",
                r"""require\(['"](\./[^'"]+)['"]\)""",
                r"""require\(['"](\.\./[^'"]+)['"]\)""",
            ]
            for pat in js_patterns:
                for m in re.finditer(pat, text):
                    imp = m.group(1)
                    norm_parts = []
                    for p in (base_dir / imp).parts:
                        if p == '..':
                            if norm_parts:
                                norm_parts.pop()
                        elif p != '.':
                            norm_parts.append(p)
                    candidate_base = '/'.join(norm_parts)
                    exts = ['.js', '.ts', '.jsx', '.tsx', '.mjs', '.cjs']
                    candidates = [candidate_base] + [candidate_base + e for e in exts] + [candidate_base + '/index' + e for e in exts]
                    found = any(c in rel_set for c in candidates)
                    if not found and candidate_base not in seen:
                        seen.add(candidate_base)
                        file_warnings.append(f"{rel} imports {imp} (not in selection)")

        if file_warnings:
            warnings[rel] = file_warnings

    return warnings


def categorize_file(name: str, path: str) -> str:
    """Categorize a file as source, test, doc, config, asset, or build."""
    lower_name = name.lower()
    lower_path = path.lower().replace('\\', '/')

    # build
    for seg in ('/dist/', '/build/', '/out/', '/.next/'):
        if seg in '/' + lower_path:
            return 'build'

    # test
    if (re.search(r'_test\.', lower_name) or
            re.search(r'\.test\.', lower_name) or
            re.search(r'\.spec\.', lower_name) or
            '/test/' in '/' + lower_path + '/' or
            '/tests/' in '/' + lower_path + '/'):
        return 'test'

    ext = Path(name).suffix.lower()

    # doc
    if ext in ('.md', '.rst', '.txt', '.adoc'):
        return 'doc'

    # config
    if ext in ('.json', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.env') or lower_name == '.env':
        return 'config'

    # asset
    asset_exts = {
        '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.webp',
        '.woff', '.woff2', '.ttf', '.eot',
        '.mp4', '.mp3', '.wav',
        '.zip', '.tar', '.gz', '.pdf',
    }
    if ext in asset_exts:
        return 'asset'

    return 'source'


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
            rel = str(path.relative_to(root))
            return {
                "type": "file",
                "name": path.name,
                "path": rel,
                "size": path.stat().st_size,
                "category": categorize_file(path.name, rel),
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

