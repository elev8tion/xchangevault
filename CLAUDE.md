# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup (one-time)
./setup.sh                    # Creates venv, installs dependencies

# Run
python server.py              # Start server at http://127.0.0.1:5055
python server.py --port N     # Custom port

# Stop
./kill_xchangevault.sh        # Kills all running instances

# Global CLI install
./install-global.sh           # Installs to ~/.local/bin/xchangevault
```

No test suite or linter is configured.

## Architecture

XchangeVault is a local web tool that extracts and transforms software projects into clean, de-linked copies. The source project is **never modified**; all writes go to a destination directory.

**Stack**: Python 3.9+ stdlib HTTP server (`ThreadingHTTPServer`) + single HTML file frontend (vanilla JS, no build step). Optional dependencies: `openai` (DeepSeek AI), `tiktoken` (token counting), `comby`/`ast-grep`/`jscodeshift`/`LibCST` (structural transforms).

### Core modules

| File | Purpose |
|------|---------|
| `server.py` | HTTP request router, SSE streaming, PID management, recipe loading, plan persistence |
| `scanner.py` | Recursive directory walk, file tree builder, tech stack detection, excludes hidden dirs |
| `rewriter.py` | Plan builder (`build_plan`), file transformer (`apply_plan`), text transforms, import fixing, diff/residual preview generation |
| `chat.py` | DeepSeek API integration, structured JSON output, chat history, context assembly |
| `frontend/index.html` | Single-page UI (~2000 lines inline CSS/JS), 5-step workflow, SSE progress display |

### Request flow for a full extraction

1. `GET /api/scan?path=...` → `scanner.py` → file tree + stack detection
2. `POST /api/plan` → `rewriter.py:build_plan()` → action list + diffs + residual scan
3. `POST /api/apply/start` → worker thread → `rewriter.py:apply_plan()` → streams logs via `GET /api/apply/stream?id=JOB_ID` (SSE)

### File transformation pipeline (in `rewriter.py`)

1. Binary detection (null bytes + decode attempt) → copy unchanged if binary
2. Brand map replacements (case-aware: lower, UPPER, Title, exact)
3. Secret scrubbing (regex: AWS keys, GitHub tokens, OpenAI keys, Sentry DSN, DB URLs)
4. Structural patterns (Comby or ast-grep, if installed)
5. Import fixing (Python: LibCST or regex; JS/TS: jscodeshift or regex)
6. Write to destination

### Key constants to know

- `DEFAULT_EXCLUDES` in `scanner.py`: dirs skipped during scan (`.git`, `node_modules`, `venv`, etc.)
- `TEXT_LIKE_EXTS` in `rewriter.py`: extensions that get text transforms (40+ types)
- `SECRET_PATTERNS` in `rewriter.py`: regex list for secrets to scrub
- `INACTIVITY_TIMEOUT` in `server.py`: auto-shutdown after 600s idle

### Runtime paths

- `plans/` — saved extraction plans (JSON), created on first save
- `~/.xchangevault/server.pid` — PID file for single-instance enforcement
- `.chat_config.json` — AI API key + model, created on first chat config (gitignored)
