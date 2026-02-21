import json
import os
import re
import shutil
from pathlib import Path
from typing import Dict, Any, List, Tuple, Callable, Optional
import difflib
import fnmatch
import shutil
import subprocess
import threading


TEXT_LIKE_EXTS = {
    ".txt", ".md", ".markdown", ".rst",
    ".json", ".jsonc", ".yaml", ".yml", ".toml", ".ini", ".env",
    ".py", ".pyi", ".ipynb", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".css", ".scss", ".sass", ".less",
    ".html", ".htm", ".svelte", ".vue", ".astro",
    ".java", ".kt", ".kts", ".go", ".rs", ".c", ".h", ".cpp", ".hpp",
    ".cs", ".swift", ".rb", ".php", ".pl", ".sh", ".bash", ".zsh",
    ".gradle", ".gradle.kts", ".gql", ".graphql",
}


SECRET_PATTERNS = [
    re.compile(r"(?i)(aws_access_key_id\s*[:=]\s*)([A-Z0-9]{16,})"),
    re.compile(r"(?i)(aws_secret_access_key\s*[:=]\s*)([A-Za-z0-9/+=]{32,})"),
    re.compile(r"(sk-[A-Za-z0-9]{16,})"),
    re.compile(r"(gh[pous]_[A-Za-z0-9]{20,})"),
    re.compile(r"(xox[baprs]-[A-Za-z0-9-]{10,})"),
    re.compile(r"(?i)(sentry_dsn\s*[:=]\s*)(https?://[^\s]+)"),
    re.compile(r"(?i)(database_url\s*[:=]\s*)([^\s]+)"),
]


def is_binary(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            chunk = f.read(8192)
            if b"\0" in chunk:
                return True
            # Heuristic: if decoding fails badly, likely binary
            try:
                chunk.decode("utf-8")
            except UnicodeDecodeError:
                return True
            return False
    except Exception:
        return False


def sanitize_name(name: str) -> str:
    # For package/project names
    s = re.sub(r"[^a-zA-Z0-9._-]", "-", name.strip())
    s = re.sub(r"[-]{2,}", "-", s)
    return s.strip("-._") or "new-project"


def _brand_variants(token: str) -> List[str]:
    uniq = {token}
    uniq.add(token.lower())
    uniq.add(token.upper())
    uniq.add(token.title())
    return sorted(uniq, key=lambda x: (-len(x), x))  # longer first


def _apply_brand_map(text: str, brand_map: List[Dict[str, str]]) -> str:
    # Apply in given order to allow intentional overrides
    replaced = text
    for item in brand_map or []:
        old = (item.get("from") or "").strip()
        new = (item.get("to") or "").strip()
        if not old:
            continue
        for var in _brand_variants(old):
            if var.isupper():
                new_var = new.upper()
            elif var.istitle():
                new_var = new.title()
            elif var.islower():
                new_var = new.lower()
            else:
                new_var = new
            replaced = replaced.replace(var, new_var)
    return replaced


def _scrub_secrets(text: str) -> str:
    def repl(m):
        # Keep the key name but redact the value(s)
        if m.lastindex and m.lastindex >= 2:
            return f"{m.group(1)}REDACTED"
        return "REDACTED"

    scrubbed = text
    for pat in SECRET_PATTERNS:
        scrubbed = pat.sub(repl, scrubbed)
    return scrubbed


def transform_bytes(path: Path, data: bytes, brand_map: List[Dict[str, str]], scrub_secrets: bool) -> bytes:
    # Only attempt text transforms on text-like or utf-8 decodable
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        # Non-UTF8: do not transform
        return data

    # metadata-aware tweaks
    if path.name == "package.json":
        try:
            pkg = json.loads(text)
            if isinstance(pkg, dict):
                # If mapping contains a 'project_name' pseudo-key, prefer it
                override_name = None
                for m in brand_map or []:
                    if m.get("from") == "__project_name__":
                        override_name = m.get("to")
                        break
                if "name" in pkg and (brand_map or override_name):
                    pkg["name"] = sanitize_name(override_name or pkg["name"])
                if "repository" in pkg:
                    # drop repository linkage by default
                    pkg.pop("repository", None)
                text = json.dumps(pkg, indent=2) + "\n"
        except Exception:
            pass

    if path.name == "pyproject.toml":
        # naive [project] name replacement
        for mapping in brand_map or []:
            if mapping.get("from") == "__project_name__" and mapping.get("to"):
                new_name = sanitize_name(mapping.get("to"))
                # Replace the quoted value of name = "..."
                text = re.sub(r'(?m)^\s*name\s*=\s*"([^"]+)"',
                              lambda m2: m2.group(0).replace(m2.group(1), new_name),
                              text)

    # brand rename map
    if brand_map:
        text = _apply_brand_map(text, brand_map)

    # secrets
    if scrub_secrets:
        text = _scrub_secrets(text)

    return text.encode("utf-8")


def build_plan(
    source_root: Path,
    include_rel_paths: List[str],
    dest_base: Path,
    new_project_name: str,
    old_brand: str,
    new_brand: str,
    scrub_secrets: bool,
    brand_map: List[Dict[str, str]] = None,
    patterns: List[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    source_root = source_root.resolve()
    dest_base = dest_base.resolve()
    dest_root = dest_base / new_project_name

    # normalize brand map
    bm: List[Dict[str, str]] = []
    if brand_map:
        for it in brand_map:
            f = (it.get("from") or "").strip()
            t = (it.get("to") or "").strip()
            if f:
                bm.append({"from": f, "to": t})
    else:
        if old_brand and new_brand:
            bm = [{"from": old_brand, "to": new_brand}]

    actions: List[Dict[str, Any]] = []
    warnings: List[str] = []

    for rel in include_rel_paths:
        src = (source_root / rel).resolve()
        if not str(src).startswith(str(source_root)):
            warnings.append(f"Skipping path outside source: {src}")
            continue
        if not src.exists():
            warnings.append(f"Missing path: {rel}")
            continue

        if src.is_dir():
            for root, dirs, files in os.walk(src):
                # skip hidden/system dirs commonly
                dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "dist", "build", ".cache", "__pycache__", ".venv", "venv"}]
                for fn in files:
                    sfile = Path(root) / fn
                    rel2 = sfile.relative_to(source_root)
                    actions.append({
                        "type": "copy",
                        "src": str(rel2).replace("\\", "/"),
                        "dst": str((dest_root / rel2).relative_to(dest_base)).replace("\\", "/"),
                        "text_transform": True,
                    })
        else:
            rel2 = src.relative_to(source_root)
            actions.append({
                "type": "copy",
                "src": str(rel2).replace("\\", "/"),
                "dst": str((dest_root / rel2).relative_to(dest_base)).replace("\\", "/"),
                "text_transform": True,
            })

    # Previews: diffs and residual scans (limited)
    previews = _build_previews(source_root, actions, bm, scrub_secrets)

    plan = {
        "source_root": str(source_root),
        "dest_base": str(dest_base),
        "dest_root": str(dest_root),
        "new_project_name": new_project_name,
        "old_brand": old_brand,
        "new_brand": new_brand,
        "scrub_secrets": scrub_secrets,
        "brand_map": bm,
        "actions": actions,
        "warnings": warnings,
        "patterns": patterns or [],
        "previews": previews,
    }
    return plan


def apply_plan(plan: Dict[str, Any], progress_cb: Optional[Callable[[str], None]] = None, cancel_checker: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
    source_root = Path(plan["source_root"]).resolve()
    dest_base = Path(plan["dest_base"]).resolve()
    dest_root = Path(plan["dest_root"]).resolve()
    scrub_secrets = bool(plan.get("scrub_secrets", False))
    brand_map = plan.get("brand_map") or []

    if dest_root.exists():
        # Prevent accidental overwrite if dir is non-empty
        if any(dest_root.iterdir()):
            raise RuntimeError(f"Destination already exists and is not empty: {dest_root}")
    else:
        dest_root.mkdir(parents=True, exist_ok=True)

    log: List[str] = []
    def _log(line: str):
        log.append(line)
        try:
            if progress_cb:
                progress_cb(line)
        except Exception:
            pass
    copied = 0
    transformed = 0

    for act in plan.get("actions", []):
        if cancel_checker and cancel_checker():
            _log("CANCEL requested; stopping apply")
            break
        src_rel = act["src"]
        dst_rel = act["dst"]
        src_file = (source_root / src_rel).resolve()
        dst_file = (dest_base / dst_rel).resolve()

        # Safety: ensure dst within dest_root
        if not str(dst_file).startswith(str(dest_root)):
            raise RuntimeError(f"Refusing to write outside destination root: {dst_file}")

        dst_file.parent.mkdir(parents=True, exist_ok=True)

        if src_file.is_dir():
            # Should not hit for 'copy' actions; skip
            continue

        if is_binary(src_file):
            shutil.copy2(src_file, dst_file)
            _log(f"BIN  {src_rel} -> {dst_rel}")
            copied += 1
        else:
            data = src_file.read_bytes()
            new_data = transform_bytes(src_file, data, brand_map, scrub_secrets)
            if new_data != data:
                transformed += 1
            dst_file.write_bytes(new_data)
            _log(f"TEXT {src_rel} -> {dst_rel}")
            copied += 1

    # Optional: run structural rewrite patterns (e.g., Comby) if available
    patt = plan.get("patterns") or []
    if patt:
        _run_patterns(dest_root, patt, _log)

    # Optional: import fixers
    fix = plan.get("fix_imports") or {}
    if fix.get("python"):
        try:
            _fix_python_imports(dest_root, brand_map, _log, cancel_checker)
        except Exception as e:
            _log(f"PY imports fix error: {e}")
    if fix.get("js"):
        try:
            _fix_js_imports(dest_root, brand_map, _log, cancel_checker)
        except Exception as e:
            _log(f"JS imports fix error: {e}")

    # Write a minimal README and .gitignore
    readme = dest_root / "README.md"
    if not readme.exists():
        readme.write_text(f"# {plan.get('new_project_name')}\n\nGenerated by Local Extractor.\n")

    gitignore = dest_root / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(".DS_Store\nnode_modules/\n.dist/\n.build/\n__pycache__/\n.venv/\nvenv/\n.env\n")

    return {
        "ok": True,
        "copied": copied,
        "transformed": transformed,
        "dest_root": str(dest_root),
        "log": log,
        "warnings": plan.get("warnings", []),
    }


def _build_previews(source_root: Path, actions: List[Dict[str, Any]], brand_map: List[Dict[str, str]], scrub_secrets: bool) -> Dict[str, Any]:
    # Build unified diffs for first N text files and residual scans
    diffs: Dict[str, str] = {}
    residuals = {
        "old_brand_hits": {},  # path -> count
        "secret_hits": [],     # list of paths
        "import_warnings": [], # strings
    }
    included_set = {a["src"] for a in actions}
    max_diffs = 100
    for act in actions:
        if act.get("type") != "copy":
            continue
        src_rel = act["src"]
        src_file = (source_root / src_rel)
        try:
            data = src_file.read_bytes()
        except Exception:
            continue
        if is_binary(src_file):
            continue
        try:
            old_text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        new_bytes = transform_bytes(src_file, data, brand_map, scrub_secrets)
        try:
            new_text = new_bytes.decode("utf-8")
        except UnicodeDecodeError:
            new_text = old_text

        # diffs
        if len(diffs) < max_diffs and old_text != new_text:
            diff = difflib.unified_diff(
                old_text.splitlines(), new_text.splitlines(),
                fromfile=f"a/{src_rel}", tofile=f"b/{src_rel}", lineterm=""
            )
            diffs[src_rel] = "\n".join(diff)

        # residual brand hits
        hits = 0
        for m in brand_map or []:
            f = m.get("from") or ""
            if not f:
                continue
            for var in _brand_variants(f):
                hits += new_text.count(var)
        if hits:
            residuals["old_brand_hits"][src_rel] = hits

        # secret hits
        for pat in SECRET_PATTERNS:
            if pat.search(new_text):
                residuals["secret_hits"].append(src_rel)
                break

        # import warnings for JS/TS relative imports
        if src_file.suffix in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
            for m in re.finditer(r"from\s+['\"](\.?\.?/[^'\"]+)['\"]", new_text):
                rel = m.group(1)
                # resolve to a possible file
                base = Path(src_rel).parent
                cand = (base / rel).as_posix()
                candidates = [cand, cand + ".js", cand + ".ts", cand + ".tsx", cand + "/index.js", cand + "/index.ts", cand + "/index.tsx"]
                if not any(c in included_set for c in candidates):
                    residuals["import_warnings"].append(f"{src_rel}: unresolved import '{rel}'")

    return {"diffs": diffs, "residuals": residuals}


def _run_patterns(dest_root: Path, patterns: List[Dict[str, Any]], _log: Callable[[str], None]):
    for p in patterns:
        tool = (p.get("tool") or "").lower()
        if tool == "comby":
            match = p.get("match") or ""
            rewrite = p.get("rewrite") or ""
            matcher = p.get("matcher") or "."
            if not match:
                continue
            if not shutil.which("comby"):
                _log("SKIP patterns: 'comby' not found")
                continue
            try:
                # Apply in-place across directory
                # comby '<match>' '<rewrite>' -matcher <matcher> -d <dir> -in-place
                subprocess.run([
                    "comby", match, rewrite, "-matcher", matcher, "-d", str(dest_root), "-in-place"
                ], check=True, capture_output=True, text=True)
                _log(f"COMBY applied: matcher={matcher}")
            except subprocess.CalledProcessError as e:
                _log(f"COMBY error: {e.stderr.strip() if e.stderr else e}")
        elif tool == "ast-grep":
            # Placeholder: detect only; actual integration can be added if needed
            if not shutil.which("ast-grep"):
                _log("SKIP patterns: 'ast-grep' not found")
                continue
            _log("ast-grep integration not implemented in MVP")


def _fix_python_imports(dest_root: Path, brand_map: List[Dict[str, str]], _log: Callable[[str], None], cancel_checker: Optional[Callable[[], bool]]):
    # Try LibCST
    has_libcst = False
    try:
        import libcst  # type: ignore
        from libcst import CSTTransformer, parse_module, Name, Attribute, RemoveFromParent
        from libcst.metadata import QualifiedNameProvider, MetadataWrapper
        has_libcst = True
    except Exception:
        has_libcst = False

    targets = [(m.get("from"), m.get("to")) for m in brand_map if m.get("from") and m.get("to")]
    if not targets:
        return

    def replace_token(tok: str) -> str:
        out = tok
        for old, new in targets:
            out = out.replace(old, new)
        return out

    count = 0
    for path in dest_root.rglob("*.py"):
        if cancel_checker and cancel_checker():
            _log("CANCEL during python-import-fix")
            break
        try:
            src = path.read_text(encoding="utf-8")
        except Exception:
            continue
        new_src = src
        if has_libcst:
            # Minimal import renamer using LibCST by text replace in module names
            # For a safe MVP, we regex module path tokens in import/from lines
            # LibCST heavy rename pass omitted for brevity
            pass
        # Fallback regex on import lines
        new_src = re.sub(r"^(\s*from\s+)([\w\.]+)(\s+import\s+)", lambda m: m.group(1) + replace_token(m.group(2)) + m.group(3), new_src, flags=re.M)
        new_src = re.sub(r"^(\s*import\s+)([\w\.]+)", lambda m: m.group(1) + replace_token(m.group(2)), new_src, flags=re.M)
        if new_src != src:
            path.write_text(new_src, encoding="utf-8")
            count += 1
    _log(f"PY imports fixed in {count} files")


def _fix_js_imports(dest_root: Path, brand_map: List[Dict[str, str]], _log: Callable[[str], None], cancel_checker: Optional[Callable[[], bool]]):
    targets = [(m.get("from"), m.get("to")) for m in brand_map if m.get("from") and m.get("to")]
    if not targets:
        return
    def replace_pkg(s: str) -> str:
        out = s
        for old, new in targets:
            out = out.replace(old, new)
        return out
    exts = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
    count = 0
    for path in dest_root.rglob("*"):
        if cancel_checker and cancel_checker():
            _log("CANCEL during js-import-fix")
            break
        if path.suffix not in exts or not path.is_file():
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except Exception:
            continue
        new_src = src
        # import ... from 'pkg'
        new_src = re.sub(r"(from\s+['\"])([^'\"]+)(['\"])", lambda m: m.group(1) + replace_pkg(m.group(2)) + m.group(3), new_src)
        # require('pkg')
        new_src = re.sub(r"(require\(\s*['\"])([^'\"]+)(['\"]\s*\))", lambda m: m.group(1) + replace_pkg(m.group(2)) + m.group(3), new_src)
        # export ... from 'pkg'
        new_src = re.sub(r"(export\s+\*?\s*from\s+['\"])([^'\"]+)(['\"])", lambda m: m.group(1) + replace_pkg(m.group(2)) + m.group(3), new_src)
        # dynamic import('pkg')
        new_src = re.sub(r"(import\(\s*['\"])([^'\"]+)(['\"]\s*\))", lambda m: m.group(1) + replace_pkg(m.group(2)) + m.group(3), new_src)
        if new_src != src:
            path.write_text(new_src, encoding="utf-8")
            count += 1
    _log(f"JS imports fixed in {count} files")
