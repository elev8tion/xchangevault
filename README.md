XchangeVault (MVP)

Purpose
- Extract selected folders/files from an existing project into a clean, de-linked new project.
- Generic text transforms to support any language.
- Simple, local-only UI designed for non-technical use.

Quick Start
1) Run the server:
   - Python 3.9+
   - `python server.py`
   - Opens at http://127.0.0.1:5055

2) In your browser:
   - Step 1: Enter the absolute path to your source project and Scan.
   - Step 2: Select files to include (checked by default). Use Select all/none/invert.
   - Step 3: Enter the new project name, destination base folder, brand map (multi‑token), and optional structural patterns. Optionally scrub secrets.
   - Step 4: Review Plan: residual scan (leftover OldBrand, secret‑like, import warnings), diff preview, actions. Save plan if desired.
   - Step 5: Generate the new project into the destination folder.

Notes
- Nothing in the source project is modified; the tool only writes to the destination.
- Destination is created as `<dest path>/<New Project Name>` and must not already contain files.
- Brand rename applies to common case variants (OLD, Title, lower, exact).
- Secret scrubbing applies regex-based replacements for common keys (e.g., `sk-...`, `AKIA...`, `SENTRY_DSN`, `DATABASE_URL`).

Tech
- Backend: Python stdlib `http.server` (no extra deps). Endpoints:
  - GET `/api/scan?path=...` → file tree + stats + stack indicators
  - POST `/api/plan` → returns copy/transform plan
  - POST `/api/apply` → executes plan (sync)
  - POST `/api/apply/start` + GET `/api/apply/stream?id=...` → streaming logs (SSE) with cancel via `POST /api/apply/cancel`
  - GET `/api/tools` → available structural tools (comby, ast-grep)
  - GET `/api/plans` (list), POST `/api/plans` (save), GET `/api/plans/:id` (load)
  - GET `/api/recipe/load?path=...` → load JSON or simple‑YAML recipe; POST `/api/recipe/save` to write one
- Frontend: Single HTML (`frontend/index.html`), no build step.

Mac Launcher
- Double-click app: `XchangeVault.app` launches the local server, finds a free port (3000–3009), opens your browser, and auto-cleans old logs.
- Quick launch: run `Launch XchangeVault (Clean).command` to start with a clean state.
- Global CLI: `./install-global.sh` installs `xchangevault` into `~/.local/bin`.
- Kill: `./kill_xchangevault.sh` stops running servers and shows port status.
- Setup: `./setup.sh` creates a venv and installs Python dependencies from `requirements.txt`.
- First‑time Gatekeeper: if macOS blocks the .app or .command, run `xattr -cr XchangeVault.app` and `chmod +x "Launch XchangeVault (Clean).command"`.

Security & Safety
- Prevents writing outside the destination root.
- Skips symlinks and common heavy/irrelevant directories by default.
- Binary files are copied without text transforms.

Customization
- Adjust exclusions in `scanner.py: DEFAULT_EXCLUDES`.
- Extend text detection/types in `rewriter.py: TEXT_LIKE_EXTS`.
- Tune secret patterns in `rewriter.py: SECRET_PATTERNS`.
- Structural patterns: Comby is supported if installed (`comby` on PATH). Patterns are applied in-place during apply.
- Import fixers: Optional. Python via LibCST if available (fallback regex); JS/TS via jscodeshift if available (fallback regex). Enable in Step 3.

AI Assistant (DeepSeek)
- Optional. Uses DeepSeek via OpenAI-compatible API.
- Configure: Click the "💬 Assistant" button and paste your API key, or set `DEEPSEEK_API_KEY` env var. Config persists to `.chat_config.json` (gitignored).
- Where it helps:
  - Step 3: "Get AI suggestions" populates brand_map, patterns, and import fix flags.
  - Step 4: "Analyze with AI" adds risks and recommendations to the plan review.
- Endpoints:
  - GET `/api/config` → chat config status
  - POST `/api/chat/config` → save API key/model
  - POST `/api/chat` → freeform chat (optionally include `{ plan }` or `{ scan }`)
  - POST `/api/chat/structured` → returns JSON suggestions `{ brand_map, patterns, import_fixes, risks, recommendations }`
