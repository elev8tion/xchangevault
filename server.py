import json
import os
import posixpath
import re
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from typing import Dict, Any

import scanner
import rewriter
import chat
import shutil
import time
import uuid
import fnmatch
from typing import Optional
import threading
import queue
import atexit


ROOT = Path(__file__).parent
FRONTEND_DIR = ROOT / "frontend"
APP_SLUG = "xchangevault"
PID_DIR = Path.home() / f".{APP_SLUG}"
PID_FILE = PID_DIR / "server.pid"

LAST_REQUEST_TIME = time.time()
INACTIVITY_TIMEOUT_SEC = int(os.environ.get("INACTIVITY_TIMEOUT", "600") or 600)


def json_response(handler: BaseHTTPRequestHandler, obj: Dict[str, Any], status: int = 200):
    data = json.dumps(obj).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def read_request_json(handler: BaseHTTPRequestHandler) -> Dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    raw = handler.rfile.read(length) if length else b""
    try:
        return json.loads(raw.decode("utf-8")) if raw else {}
    except Exception:
        return {}


class Handler(BaseHTTPRequestHandler):
    server_version = "ExtractorHTTP/0.1"

    # ---- Utility helpers -------------------------------------------------
    def _serve_static(self, rel_path: str):
        # prevent path traversal
        safe_path = posixpath.normpath("/" + rel_path).lstrip("/")
        fs_path = (FRONTEND_DIR / safe_path).resolve()
        if not str(fs_path).startswith(str(FRONTEND_DIR.resolve())):
            self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
            return
        if fs_path.is_dir():
            fs_path = fs_path / "index.html"
        if not fs_path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        # very small MIME map
        if fs_path.suffix == ".html":
            ctype = "text/html; charset=utf-8"
        elif fs_path.suffix == ".js":
            ctype = "application/javascript; charset=utf-8"
        elif fs_path.suffix == ".css":
            ctype = "text/css; charset=utf-8"
        elif fs_path.suffix in {".png", ".jpg", ".jpeg", ".gif", ".svg"}:
            ctype = "image/" + fs_path.suffix.lstrip(".")
        else:
            ctype = "application/octet-stream"
        data = fs_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj: Dict[str, Any], status: int = 200):
        json_response(self, obj, status)

    # ---- Routing ---------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        global LAST_REQUEST_TIME
        LAST_REQUEST_TIME = time.time()

        if path == "/api/config":
            return self._json({
                'api_key_set':    bool(chat.DEEPSEEK_API_KEY),
                'selected_model': chat.SELECTED_MODEL,
            })

        if path == "/api/apply/stream":
            job_id = (parse_qs(parsed.query).get("id") or [""])[0]
            return self._sse(job_id)

        if path == "/" or path == "/index.html":
            return self._serve_static("index.html")

        if path.startswith("/frontend/"):
            return self._serve_static(path[len("/frontend/"):])

        if path == "/api/scan":
            qs = parse_qs(parsed.query)
            src = (qs.get("path") or [""])[0].strip()
            if not src:
                return self._json({"error": "Missing 'path' query param"}, 400)
            source_path = Path(src).expanduser().resolve()
            if not source_path.exists() or not source_path.is_dir():
                return self._json({"error": f"Path not found or not a directory: {source_path}"}, 400)
            try:
                tree, stats, stack = scanner.scan_project(source_path)
                return self._json({
                    "root": str(source_path),
                    "tree": tree,
                    "stats": stats,
                    "stack": stack,
                    "excludes": scanner.DEFAULT_EXCLUDES,
                })
            except Exception as e:
                return self._json({"error": str(e)}, 500)

        if path == "/api/health":
            return self._json({"ok": True})

        if path == "/api/plans":
            return self._handle_list_plans()

        if path.startswith("/api/plans/"):
            plan_id = path.split("/api/plans/")[-1]
            return self._handle_get_plan(plan_id)

        if path == "/api/tools":
            return self._json({
                "comby": bool(shutil.which("comby")),
                "ast_grep": bool(shutil.which("ast-grep")),
                "jscodeshift": bool(shutil.which("jscodeshift")),
                "libcst": self._has_libcst(),
            })

        if path == "/api/recipe/load":
            qs = parse_qs(parsed.query)
            rp = (qs.get("path") or [""])[0].strip()
            if not rp:
                return self._json({"error": "Missing 'path' query param"}, 400)
            try:
                settings = load_recipe(Path(rp).expanduser())
                return self._json({"settings": settings})
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        return self.send_error(HTTPStatus.NOT_FOUND, "Unknown route")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        data = read_request_json(self)
        global LAST_REQUEST_TIME
        LAST_REQUEST_TIME = time.time()

        if path == "/api/chat/config":
            key = (data.get('api_key') or '').strip()
            model = data.get('model')
            ok = chat.save_config(key or None, model)
            return self._json({'ok': ok})

        if path == "/api/chat":
            msg = (data.get('message') or '').strip()
            if not msg:
                return self._json({'error': 'Missing message'}, 400)
            model = data.get('model') or chat.SELECTED_MODEL
            plan = data.get('plan')
            scan = data.get('scan')
            ctx = chat.build_extractor_context(msg, plan=plan, scan=scan)
            pid = (plan or {}).get('source_root') or (scan or {}).get('root') or 'default'
            history = chat.get_history(pid)
            try:
                reply = chat.call_chat(msg, ctx, model, chat_history=history)
            except Exception as e:
                return self._json({'error': str(e)}, 400)
            chat.append_history(pid, 'user', msg)
            chat.append_history(pid, 'assistant', reply)
            return self._json({'response': reply, 'model': model})

        if path == "/api/chat/structured":
            msg = (data.get('message') or '').strip()
            if not msg:
                return self._json({'error': 'Missing message'}, 400)
            model = data.get('model') or chat.SELECTED_MODEL
            plan = data.get('plan')
            scan = data.get('scan')
            ctx = chat.build_extractor_context(msg, plan=plan, scan=scan)
            try:
                result = chat.call_structured(msg, ctx, model)
            except Exception as e:
                return self._json({'error': str(e)}, 400)
            return self._json({'result': result, 'model': model})

        if path == "/api/chat/clear":
            pid = (data.get('project_id') or '').strip()
            chat.clear_history(pid or None)
            return self._json({'ok': True})

        if path == "/api/plan":
            return self._handle_plan(data)

        if path == "/api/apply":
            return self._handle_apply(data)

        if path == "/api/plans":
            return self._handle_save_plan(data)

        if path == "/api/apply/start":
            return self._handle_apply_start(data)

        if path == "/api/apply/cancel":
            return self._handle_apply_cancel(data)

        if path == "/api/recipe/save":
            return self._handle_recipe_save(data)

        if path == "/api/shutdown":
            return self._handle_shutdown()

        return self.send_error(HTTPStatus.NOT_FOUND, "Unknown route")

    # ---- Endpoint implementations ---------------------------------------
    def _handle_plan(self, data: Dict[str, Any]):
        try:
            source_path = Path(data.get("source_path", "")).expanduser().resolve()
            include_paths = data.get("include_paths") or []
            new_project_name = (data.get("new_project_name") or "NewProject").strip()
            old_brand = data.get("old_brand") or "OldBrand"
            new_brand = data.get("new_brand") or "NewBrand"
            scrub_secrets = bool(data.get("scrub_secrets", False))
            dest_path = Path(data.get("dest_path", "")).expanduser().resolve()
            brand_map = data.get("brand_map") or []
            patterns = data.get("patterns") or []
            fix_imports = data.get("fix_imports") or {"python": False, "js": False}

            if not source_path.exists() or not source_path.is_dir():
                return self._json({"error": f"Invalid source_path: {source_path}"}, 400)
            if not include_paths:
                return self._json({"error": "include_paths array required"}, 400)
            if not new_project_name:
                return self._json({"error": "new_project_name required"}, 400)
            if not dest_path:
                return self._json({"error": "dest_path required"}, 400)

            # Build plan
            plan = rewriter.build_plan(
                source_root=source_path,
                include_rel_paths=include_paths,
                dest_base=dest_path,
                new_project_name=new_project_name,
                old_brand=old_brand,
                new_brand=new_brand,
                scrub_secrets=scrub_secrets,
                brand_map=brand_map,
                patterns=patterns,
            )
            plan["fix_imports"] = {"python": bool(fix_imports.get("python")), "js": bool(fix_imports.get("js"))}
            return self._json({"plan": plan})
        except Exception as e:
            return self._json({"error": str(e)}, 500)

    def _handle_apply(self, data: Dict[str, Any]):
        try:
            plan = data.get("plan")
            if not plan:
                # For convenience, allow same body as /api/plan
                p = rewriter.build_plan(
                    source_root=Path(data.get("source_path", "")).expanduser().resolve(),
                    include_rel_paths=data.get("include_paths") or [],
                    dest_base=Path(data.get("dest_path", "")).expanduser().resolve(),
                    new_project_name=(data.get("new_project_name") or "NewProject").strip(),
                    old_brand=data.get("old_brand") or "OldBrand",
                    new_brand=data.get("new_brand") or "NewBrand",
                    scrub_secrets=bool(data.get("scrub_secrets", False)),
                    brand_map=data.get("brand_map") or [],
                    patterns=data.get("patterns") or [],
                )
                p["fix_imports"] = data.get("fix_imports") or {"python": False, "js": False}
                return self._handle_apply({"plan": p})

            applied = rewriter.apply_plan(plan)
            return self._json(applied)
        except Exception as e:
            return self._json({"error": str(e)}, 500)

    # ---- Plans -----------------------------------------------------------
    def _plans_dir(self) -> Path:
        p = ROOT / "plans"
        p.mkdir(exist_ok=True)
        return p

    def _handle_list_plans(self):
        items = []
        for f in sorted(self._plans_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            items.append({
                "id": f.stem,
                "path": str(f),
                "name": f.name,
                "modified": int(f.stat().st_mtime),
                "size": f.stat().st_size,
            })
        return self._json({"plans": items})

    def _handle_get_plan(self, plan_id: str):
        f = self._plans_dir() / f"{plan_id}.json"
        if not f.exists():
            return self._json({"error": "Plan not found"}, 404)
        try:
            return self._json({"plan": json.loads(f.read_text())})
        except Exception as e:
            return self._json({"error": str(e)}, 500)

    def _handle_save_plan(self, data: Dict[str, Any]):
        plan = data.get("plan")
        name = (data.get("name") or "").strip()
        if not plan:
            return self._json({"error": "Missing plan"}, 400)
        plan_id = name or time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        f = self._plans_dir() / f"{plan_id}.json"
        try:
            f.write_text(json.dumps(plan, indent=2))
            return self._json({"id": plan_id, "path": str(f)})
        except Exception as e:
            return self._json({"error": str(e)}, 500)

    def _handle_shutdown(self):
        # Respond immediately, then shut down the server gracefully.
        try:
            self._json({"ok": True, "message": "Shutting down"})
        except Exception:
            pass

        def _stop():
            try:
                if PID_FILE.exists():
                    PID_FILE.unlink()
            except Exception:
                pass
            try:
                # Give the response a moment to flush
                time.sleep(0.2)
                self.server.shutdown()
            except Exception:
                pass
            # Ensure process exits
            os._exit(0)

        t = threading.Thread(target=_stop, daemon=True)
        t.start()
        return None

    def _handle_recipe_save(self, data: Dict[str, Any]):
        out_path = (data.get("path") or "").strip()
        settings = data.get("settings") or {}
        if not out_path:
            return self._json({"error": "Missing path"}, 400)
        try:
            p = Path(out_path).expanduser().resolve()
            save_recipe(p, settings)
            return self._json({"ok": True, "path": str(p)})
        except Exception as e:
            return self._json({"error": str(e)}, 500)

    # ---- Streaming apply -------------------------------------------------
    JOBS: Dict[str, Any] = {}

    def _handle_apply_start(self, data: Dict[str, Any]):
        plan = data.get("plan")
        if not plan:
            return self._json({"error": "Missing plan"}, 400)
        job_id = uuid.uuid4().hex[:12]
        q: "queue.Queue[tuple]" = queue.Queue()
        state = {"done": False, "result": None, "cancel": False, "queue": q}

        def cancel_checker():
            return state["cancel"]

        def progress_cb(line: str):
            try:
                q.put(("log", line))
            except Exception:
                pass

        def worker():
            try:
                res = rewriter.apply_plan(plan, progress_cb=progress_cb, cancel_checker=cancel_checker)
                state["result"] = res
            except Exception as e:
                state["result"] = {"ok": False, "error": str(e)}
            finally:
                state["done"] = True
                try:
                    q.put(("done", json.dumps(state["result"])) )
                except Exception:
                    pass

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        self.JOBS[job_id] = state
        return self._json({"id": job_id})

    def _handle_apply_cancel(self, data: Dict[str, Any]):
        job_id = (data.get("id") or "").strip()
        st = self.JOBS.get(job_id)
        if not st:
            return self._json({"error": "Job not found"}, 404)
        st["cancel"] = True
        return self._json({"ok": True})

    def _has_libcst(self) -> bool:
        try:
            import importlib.util
            return importlib.util.find_spec("libcst") is not None
        except Exception:
            return False

    def do_STREAM(self):  # not used
        pass

    def _sse(self, job_id: str):
        st = self.JOBS.get(job_id)
        if not st:
            self.send_error(404, "Job not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q: queue.Queue = st["queue"]
        try:
            # initial ping
            self.wfile.write(b":ok\n\n")
            self.wfile.flush()
            while True:
                try:
                    kind, payload = q.get(timeout=1.0)
                    if kind == "log":
                        msg = f"event: log\ndata: {payload}\n\n".encode("utf-8")
                        self.wfile.write(msg)
                        self.wfile.flush()
                    elif kind == "done":
                        msg = f"event: done\ndata: {payload}\n\n".encode("utf-8")
                        self.wfile.write(msg)
                        self.wfile.flush()
                        break
                except queue.Empty:
                    # keepalive
                    self.wfile.write(b":keepalive\n\n")
                    self.wfile.flush()
                    if st["done"] and q.empty():
                        break
        except BrokenPipeError:
            pass

    # Remove duplicate do_GET (handled earlier)


# ---- Recipe loading ------------------------------------------------------
def load_recipe(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    text = path.read_text()
    # Try JSON first
    try:
        obj = json.loads(text)
        return _normalize_recipe(obj)
    except Exception:
        pass
    # Minimal YAML support (simple keys + lists + list of dicts)
    return _parse_yaml_minimal(text)


def _normalize_recipe(obj: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "includes": obj.get("includes") or [],
        "excludes": obj.get("excludes") or [],
        "brand_map": obj.get("brand_map") or [],
        "scrub": obj.get("scrub") or [],
        "patterns": obj.get("patterns") or [],
    }


def _parse_yaml_minimal(text: str) -> Dict[str, Any]:
    # Extremely limited YAML: top-level keys, lists (- item), and list of dicts for patterns/brand_map
    result: Dict[str, Any] = {"includes": [], "excludes": [], "brand_map": [], "scrub": [], "patterns": []}
    current_key: Optional[str] = None
    current_obj: Optional[Dict[str, Any]] = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith('#'):
            continue
        if not line.startswith(' ') and ':' in line:
            key, val = line.split(':', 1)
            key = key.strip()
            val = val.strip()
            current_key = key
            if val:
                # simple scalar
                result[key] = val
            else:
                if key not in result:
                    result[key] = []
            current_obj = None
            continue
        if current_key and line.lstrip().startswith('- '):
            item = line.strip()[2:]
            if current_key in ("includes", "excludes", "scrub"):
                result[current_key].append(item)
                current_obj = None
            else:
                # list of dicts start
                current_obj = {}
                result[current_key].append(current_obj)
                if ':' in item:
                    k, v = item.split(':', 1)
                    current_obj[k.strip()] = v.strip()
            continue
        if current_obj is not None and ':' in line:
            k, v = line.strip().split(':', 1)
            current_obj[k.strip()] = v.strip()
    return _normalize_recipe(result)


def save_recipe(path: Path, settings: Dict[str, Any]) -> None:
    # Write a simple YAML (best-effort) or JSON if extension .json
    if path.suffix.lower() == ".json":
        path.write_text(json.dumps(settings, indent=2))
        return
    def dump_list(lst):
        return "\n".join([f"- {item}" if not isinstance(item, dict) else "- " + ", ".join(f"{k}: {v}" for k,v in item.items()) for item in lst])
    lines = []
    for key in ["includes", "excludes", "brand_map", "scrub", "patterns"]:
        val = settings.get(key)
        if val is None:
            continue
        lines.append(f"{key}:")
        if isinstance(val, list):
            if not val:
                continue
            for item in val:
                if isinstance(item, dict):
                    # one-line dict entries
                    items = []
                    for k, v in item.items():
                        v = str(v).replace('\n', ' ')
                        items.append(f"{k}: {v}")
                    lines.append("- " + ", ".join(items))
                else:
                    lines.append(f"- {item}")
        else:
            lines.append(f"  {val}")
    path.write_text("\n".join(lines) + "\n")



def run(host="127.0.0.1", port=5055):
    try:
        chat.load_config()
    except Exception:
        pass
    httpd = ThreadingHTTPServer((host, port), Handler)
    # Write PID file
    try:
        PID_DIR.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()))
    except Exception:
        pass

    def _cleanup_pid():
        try:
            if PID_FILE.exists():
                PID_FILE.unlink()
        except Exception:
            pass

    atexit.register(_cleanup_pid)

    print(f"Extractor server running at http://{host}:{port}")
    print(f"Serving frontend from {FRONTEND_DIR}")

    # Background inactivity monitor
    def _monitor():
        while True:
            try:
                time.sleep(5)
                if INACTIVITY_TIMEOUT_SEC > 0 and (time.time() - LAST_REQUEST_TIME) > INACTIVITY_TIMEOUT_SEC:
                    print("Inactivity timeout reached; shutting down.")
                    try:
                        httpd.shutdown()
                    except Exception:
                        pass
                    os._exit(0)
            except Exception:
                pass

    t = threading.Thread(target=_monitor, daemon=True)
    t.start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    host = os.environ.get("EXTRACTOR_HOST", "127.0.0.1")
    port = int(os.environ.get("EXTRACTOR_PORT", "5055"))
    # CLI override: --port N
    args = sys.argv[1:]
    if "--port" in args:
        try:
            idx = args.index("--port")
            port = int(args[idx + 1])
        except Exception:
            pass
    run(host, port)
