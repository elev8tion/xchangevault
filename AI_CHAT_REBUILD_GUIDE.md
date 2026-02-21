# AI Chat System — Full Rebuild Guide

> Extracted from **Codebase Cartographer** (`cartographer.py` + `dashboard.html`)
> Drop this into any Python web-app project and wire it up in minutes.

---

## Table of Contents

1. [Overview](#overview)
2. [Dependencies](#dependencies)
3. [File Structure to Copy](#file-structure-to-copy)
4. [Backend — Python Modules](#backend--python-modules)
   - [Config & API Key Management](#config--api-key-management)
   - [Token Counting & Truncation](#token-counting--truncation)
   - [Context Builder](#context-builder)
   - [DeepSeek API Call Function](#deepseek-api-call-function)
   - [Structured JSON Analysis Variant](#structured-json-analysis-variant)
   - [Chat History State](#chat-history-state)
5. [HTTP Endpoints](#http-endpoints)
   - [GET /api/config](#get-apiconfig)
   - [POST /api/chat](#post-apichat)
   - [POST /api/chat/structured](#post-apichatstructured)
   - [POST /api/chat/config](#post-apichatconfig)
   - [POST /api/chat/clear](#post-apichatclear)
   - [GET /api/chat/history](#get-apichathistory)
6. [Frontend — HTML/JS Chat Widget](#frontend--htmljs-chat-widget)
   - [HTML Shell](#html-shell)
   - [CSS (paste into your stylesheet)](#css-paste-into-your-stylesheet)
   - [JavaScript (complete, self-contained)](#javascript-complete-self-contained)
7. [Model Selection & Configuration](#model-selection--configuration)
8. [Adapting the Context Builder](#adapting-the-context-builder)
9. [Multi-Project Mode](#multi-project-mode)
10. [Security Checklist](#security-checklist)
11. [Quick-Start Minimal Example](#quick-start-minimal-example)

---

## Overview

The AI chat is a **sidebar widget** powered by the **DeepSeek API** (OpenAI-compatible).
The backend is pure Python stdlib + `openai` pip package. No framework required.

```
Browser  ──POST /api/chat──►  Python HTTP Server  ──►  DeepSeek API
  ▲                                    │
  └────────── JSON response ───────────┘
```

Key design decisions:
- Context is **strategically assembled** per-query (relevance scoring, not full dump)
- Chat **history is stored in memory** per-project (or per-session); survives refreshes within the same server run
- Three models supported: `deepseek-chat` (fast/cheap), `deepseek-coder` (code-focused), `deepseek-reasoner` (deep reasoning / R1)
- Token counting via `tiktoken` with character-based fallback
- Config (API key + model choice) persisted to a local JSON file

---

## Dependencies

```bash
pip install openai          # DeepSeek uses the OpenAI SDK (same protocol)
pip install tiktoken        # Optional but recommended — accurate token counting
```

> DeepSeek API docs: https://platform.deepseek.com/docs
> Get your API key at: https://platform.deepseek.com/api_keys

---

## File Structure to Copy

```
your-project/
├── server.py               ← your HTTP server (add the chat code here)
├── .chat_config.json       ← auto-created on first config save (gitignore this!)
└── frontend/
    └── index.html          ← add chat HTML/CSS/JS here
```

Add `.chat_config.json` to `.gitignore` so the API key is never committed.

---

## Backend — Python Modules

### Config & API Key Management

```python
import os, json
from pathlib import Path
from datetime import datetime

CONFIG_FILE = Path(__file__).parent / '.chat_config.json'

# Model IDs
MODEL_DEEPSEEK_CODER    = 'deepseek-coder'
MODEL_DEEPSEEK_REASONER = 'deepseek-reasoner'
MODEL_DEEPSEEK_CHAT     = 'deepseek-chat'

TOKEN_LIMITS = {
    MODEL_DEEPSEEK_CODER:    128000,
    MODEL_DEEPSEEK_REASONER: 128000,
    MODEL_DEEPSEEK_CHAT:      64000,
}

OPTIMAL_TEMPS = {
    MODEL_DEEPSEEK_CODER:    0.7,
    MODEL_DEEPSEEK_REASONER: 0.6,
    MODEL_DEEPSEEK_CHAT:     0.7,
}

# Runtime state
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', '')
SELECTED_MODEL   = MODEL_DEEPSEEK_CHAT


def load_config():
    """Load API key + model from disk. Environment variable takes priority."""
    global DEEPSEEK_API_KEY, SELECTED_MODEL
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text())
            if not os.environ.get('DEEPSEEK_API_KEY'):
                key = cfg.get('api_key', '')
                if key:
                    DEEPSEEK_API_KEY = key
            model = cfg.get('model', '')
            if model:
                SELECTED_MODEL = model
            return True
        except Exception as e:
            print(f"Config load failed: {e}")
    return False


def save_config():
    """Persist API key + model to disk."""
    global DEEPSEEK_API_KEY, SELECTED_MODEL
    try:
        cfg = {
            'api_key':  DEEPSEEK_API_KEY,
            'model':    SELECTED_MODEL,
            'saved_at': datetime.now().isoformat()
        }
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
        return True
    except Exception as e:
        print(f"Config save failed: {e}")
        return False
```

**How to wire**: call `load_config()` once at startup, before starting the server.

---

### Token Counting & Truncation

```python
try:
    import tiktoken
    _ENCODING = tiktoken.get_encoding("cl100k_base")
except ImportError:
    _ENCODING = None


def estimate_tokens(text: str) -> int:
    if _ENCODING:
        try:
            return len(_ENCODING.encode(text, disallowed_special=()))
        except Exception:
            pass
    return len(text) // 3  # rough fallback: ~3 chars per token


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    if _ENCODING:
        try:
            tokens = _ENCODING.encode(text, disallowed_special=())
            if len(tokens) <= max_tokens:
                return text
            return _ENCODING.decode(tokens[:max_tokens])
        except Exception:
            pass
    # Fallback: character-based
    if estimate_tokens(text) <= max_tokens:
        return text
    return text[:max_tokens * 3]
```

---

### Context Builder

This is the function you **adapt for your own project data**.
In Cartographer it passes codebase scan results; replace the body with whatever domain context your app needs.

```python
def build_context(query: str, project_data: dict) -> str:
    """
    Assemble a context string to prepend to each AI message.

    Replace this with your own logic — the key rules are:
      1. Put the most critical info at TOP and BOTTOM (LLMs pay most attention there)
      2. Truncate to stay within the model's token budget
      3. Keep it query-relevant; don't dump everything

    `project_data` example shape (adapt to your domain):
    {
        'name': 'MyProject',
        'health_score': 85,
        'files': [...],          # list of file metadata dicts
        'agent_context': '...',  # pre-built summary string
        'contents': {file_id: raw_text},
    }
    """

    if not project_data:
        return "No project data available."

    # --- TOP (high LLM attention) ---
    top = f"""QUERY: {query}

PROJECT: {project_data.get('name', 'Unknown')}
HEALTH:  {project_data.get('health_score', 'N/A')}/100
FILES:   {len(project_data.get('files', []))}
"""

    # --- MIDDLE (supporting detail) ---
    middle = f"""
ARCHITECTURE SUMMARY:
{project_data.get('agent_context', 'No summary available')}
"""

    # Optionally include relevant file contents here
    relevant = _select_relevant_files(query, project_data.get('files', []))
    for node in relevant[:5]:
        content = project_data.get('contents', {}).get(node['id'], '')
        middle += f"\nFILE: {node['path']}\n```\n{content[:3000]}\n```\n"

    # --- BOTTOM (high LLM attention) ---
    bottom = f"""
INSTRUCTIONS:
- Use markdown code blocks with file paths
- Be specific and actionable
- Reference line numbers when relevant
"""

    raw = top + middle + bottom
    return truncate_to_tokens(raw, max_tokens=100_000)


def _select_relevant_files(query: str, files: list, max_files: int = 10) -> list:
    """Score and rank files by query relevance. Adapt field names to your schema."""
    q = query.lower()
    words = set(q.split())
    scored = []
    for f in files:
        score = 0
        if any(w in f.get('name', '').lower() for w in words): score += 5
        if any(w in f.get('path', '').lower() for w in words): score += 3
        if f.get('risk_score', 0) > 50: score += 2
        if score > 0:
            scored.append((f, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [f for f, _ in scored[:max_files]]
```

---

### DeepSeek API Call Function

```python
def call_deepseek(
    message: str,
    context: str,
    model: str = MODEL_DEEPSEEK_CHAT,
    chat_history: list = None,   # list of {"role": ..., "content": ...} dicts
) -> str:
    """
    Send a message to DeepSeek and return the assistant's reply.

    Args:
        message:      The user's message.
        context:      Pre-built context string (from build_context()).
        model:        One of MODEL_DEEPSEEK_CHAT / CODER / REASONER.
        chat_history: Recent conversation history (keep to last ~10 messages).

    Returns:
        The assistant's reply as a string.

    Raises:
        ValueError:  If API key is not set.
        ImportError: If `openai` package is missing.
    """
    global DEEPSEEK_API_KEY

    if not DEEPSEEK_API_KEY:
        raise ValueError("DEEPSEEK_API_KEY not set. Configure via settings or DEEPSEEK_API_KEY env var.")

    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("Run: pip install openai")

    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com"
    )

    temperature = OPTIMAL_TEMPS.get(model, 0.7)

    # ── Model-specific message formatting ──────────────────────────────────
    if model == MODEL_DEEPSEEK_REASONER:
        # R1: no system prompt; fold context into user message
        system_content = ""
        user_content = f"""Task: {message}

Context:
{context}

Output Format:
1. Analysis
2. Code changes (with file paths in code blocks)
3. Testing/verification plan"""

    elif model == MODEL_DEEPSEEK_CODER:
        system_content = f"""You are an expert software architect.

Context:
{context}

Guidelines:
- Reference specific files and line numbers
- Use ```lang\\n// File: path/to/file\\ncode\\n``` blocks
- Show before/after for any modifications
- Consider security, performance, maintainability"""
        user_content = message

    else:  # deepseek-chat (V3) — default
        system_content = f"""You are a senior software engineer.

Context:
{context}

When proposing changes:
- Use markdown code blocks with file paths
- Be concise and actionable
- Reference specific files from the context"""
        user_content = message

    # ── Build messages list ────────────────────────────────────────────────
    messages = []
    if system_content:
        messages.append({"role": "system", "content": system_content})

    # Append recent history (last 10 turns to keep token budget sane)
    if chat_history:
        messages.extend(chat_history[-10:])

    messages.append({"role": "user", "content": user_content})

    # ── Call API ───────────────────────────────────────────────────────────
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=8000,
    )

    return response.choices[0].message.content
```

---

### Structured JSON Analysis Variant

Use this when you want the AI to return machine-readable JSON instead of markdown prose.

```python
def call_deepseek_structured(message: str, context: str, model: str = MODEL_DEEPSEEK_CHAT) -> dict:
    """Returns a structured dict — useful for dashboards, reports, etc."""
    global DEEPSEEK_API_KEY

    if not DEEPSEEK_API_KEY:
        raise ValueError("DEEPSEEK_API_KEY not set")

    from openai import OpenAI
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

    system_content = f"""Analyze and return ONLY valid JSON in this exact shape:
{{
    "summary": "Brief overview",
    "issues": [{{
        "severity": "high|medium|low",
        "file": "path/to/file",
        "line": 42,
        "type": "security|performance|maintainability|bug",
        "description": "...",
        "fix": "..."
    }}],
    "recommendations": ["..."]
}}

Context:
{context}"""

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_content},
            {"role": "user",   "content": message},
        ],
        temperature=0.7,
        max_tokens=2000,
        response_format={"type": "json_object"},
    )

    return json.loads(response.choices[0].message.content)
```

---

### Chat History State

Store history in memory — one list per project/session:

```python
# Single session
CHAT_HISTORY: list = []  # [{"role": "user"|"assistant", "content": "..."}]

def append_history(role: str, content: str):
    CHAT_HISTORY.append({"role": role, "content": content})

def clear_history():
    global CHAT_HISTORY
    CHAT_HISTORY = []

def get_history() -> list:
    return CHAT_HISTORY
```

For multi-project use, key the history by project ID:

```python
PROJECT_HISTORIES: dict = {}  # {project_id: [{"role": ..., "content": ...}]}

def get_project_history(pid: str) -> list:
    return PROJECT_HISTORIES.setdefault(pid, [])
```

---

## HTTP Endpoints

These are plain Python `BaseHTTPRequestHandler` handlers. Adapt to Flask/FastAPI/Django as needed.

### GET /api/config

```python
# Returns current config status (never expose the key itself)
def handle_get_config(self):
    self._json({
        'api_key_set':    bool(DEEPSEEK_API_KEY),
        'selected_model': SELECTED_MODEL,
    })
```

---

### POST /api/chat

**Request body:**
```json
{
  "message":       "Explain the auth flow",
  "model":         "deepseek-chat",
  "include_files": ["file_id_1", "file_id_2"],
  "project_id":    "abc123"
}
```

**Handler:**
```python
def handle_post_chat(self, data: dict):
    message    = data.get('message', '').strip()
    model      = data.get('model', SELECTED_MODEL)
    project_id = data.get('project_id')

    if not message:
        self.send_error(400, 'Missing message')
        return

    # 1. Build context from your project data
    project_data = get_project_data(project_id)  # your own lookup
    context = build_context(message, project_data)

    # 2. Get history and call API
    history = get_project_history(project_id)
    try:
        reply = call_deepseek(message, context, model, history)
    except ValueError as e:
        self.send_error(400, str(e))
        return
    except Exception as e:
        self.send_error(500, str(e))
        return

    # 3. Persist to history
    history.append({"role": "user",      "content": message})
    history.append({"role": "assistant", "content": reply})

    self._json({'response': reply, 'model': model, 'context_size': len(context)})
```

---

### POST /api/chat/structured

```python
def handle_post_chat_structured(self, data: dict):
    message    = data.get('message', '').strip()
    model      = data.get('model', SELECTED_MODEL)
    project_id = data.get('project_id')

    project_data = get_project_data(project_id)
    context = build_context(message, project_data)

    try:
        result = call_deepseek_structured(message, context, model)
        self._json(result)
    except Exception as e:
        self.send_error(500, str(e))
```

---

### POST /api/chat/config

```python
def handle_post_chat_config(self, data: dict):
    global DEEPSEEK_API_KEY, SELECTED_MODEL

    api_key = data.get('api_key', '').strip()
    model   = data.get('model', '')

    # 'KEEP_EXISTING' is sent by the frontend model-switcher to avoid clearing the key
    if api_key and api_key != 'KEEP_EXISTING':
        DEEPSEEK_API_KEY = api_key

    if not DEEPSEEK_API_KEY:
        self.send_error(400, 'API key cannot be empty')
        return

    if model:
        SELECTED_MODEL = model

    saved = save_config()
    self._json({'success': True, 'model': SELECTED_MODEL, 'api_key_set': True, 'saved': saved})
```

---

### POST /api/chat/clear

```python
def handle_post_chat_clear(self, data: dict):
    project_id = data.get('project_id')
    if project_id and project_id in PROJECT_HISTORIES:
        PROJECT_HISTORIES[project_id] = []
    self._json({'success': True})
```

---

### GET /api/chat/history

```python
def handle_get_chat_history(self, project_id: str):
    history = get_project_history(project_id) if project_id else []
    self._json({'messages': history})
```

---

## Frontend — HTML/JS Chat Widget

### HTML Shell

Add this anywhere in your `<body>`. It is a slide-in sidebar that the JS toggles.

```html
<!-- Toggle button — put wherever suits your layout -->
<button class="btn" onclick="openChat()" id="chat-toggle-btn">💬 AI Chat</button>

<!-- Sidebar panel -->
<div id="chat-sidebar" style="display:none; width:450px; border-left:1px solid #333;
     flex-direction:column; background:#1e1e2e; position:fixed; right:0; top:0;
     bottom:0; z-index:1000; box-shadow:-4px 0 20px rgba(0,0,0,.4)">

  <!-- Header -->
  <div style="padding:16px; border-bottom:1px solid #333; display:flex;
       align-items:center; justify-content:space-between">
    <span style="font-weight:700; font-size:15px; color:#cdd6f4">DeepSeek AI</span>
    <div style="display:flex; gap:8px; align-items:center">
      <div id="model-badge" style="font-size:9px; padding:2px 8px; border-radius:12px;
           background:#89b4fa22; color:#89b4fa; border:1px solid #89b4fa44">V3</div>
      <button onclick="clearChat()" title="Clear chat"
              style="background:none; border:none; color:#6c7086; cursor:pointer; font-size:18px">🗑</button>
      <button onclick="closeChat()"
              style="background:none; border:none; color:#6c7086; cursor:pointer; font-size:20px">✕</button>
    </div>
  </div>

  <!-- Model switcher -->
  <div style="display:flex; gap:6px; padding:8px 16px; border-bottom:1px solid #333">
    <button id="model-chat-btn"     onclick="setChatModel('deepseek-chat')"
            style="flex:1; font-size:11px; padding:4px 8px; border-radius:6px;
                   background:#313244; border:1px solid #45475a; color:#cdd6f4; cursor:pointer">
      V3 Fast
    </button>
    <button id="model-coder-btn"    onclick="setChatModel('deepseek-coder')"
            style="flex:1; font-size:11px; padding:4px 8px; border-radius:6px;
                   background:#313244; border:1px solid #45475a; color:#cdd6f4; cursor:pointer">
      Coder
    </button>
    <button id="model-reasoner-btn" onclick="setChatModel('deepseek-reasoner')"
            style="flex:1; font-size:11px; padding:4px 8px; border-radius:6px;
                   background:#313244; border:1px solid #45475a; color:#cdd6f4; cursor:pointer">
      R1 Reasoning
    </button>
  </div>

  <!-- API key setup (shown only when key is not set) -->
  <div id="api-setup" style="display:none; padding:16px; border-bottom:1px solid #333">
    <p style="font-size:12px; color:#f38ba8; margin:0 0 8px">
      DeepSeek API key required.
      <a href="https://platform.deepseek.com/api_keys" target="_blank"
         style="color:#89b4fa">Get one here ↗</a>
    </p>
    <div style="display:flex; gap:8px">
      <input id="api-key-input" type="password" placeholder="sk-..."
             style="flex:1; padding:6px 10px; border-radius:6px; background:#313244;
                    border:1px solid #45475a; color:#cdd6f4; font-size:12px"/>
      <button onclick="saveApiKey()"
              style="padding:6px 12px; border-radius:6px; background:#89b4fa;
                     border:none; color:#1e1e2e; font-weight:700; cursor:pointer; font-size:12px">
        Save
      </button>
    </div>
  </div>

  <!-- Message list -->
  <div id="chatMessages" style="flex:1; overflow-y:auto; padding:16px;
       display:flex; flex-direction:column; gap:16px; scroll-behavior:smooth">
    <!-- Messages are injected here by JS -->
  </div>

  <!-- Input area -->
  <div style="padding:16px; border-top:1px solid #333; background:#1e1e2e">
    <div style="display:flex; gap:8px; align-items:flex-end; background:#313244;
         border:1px solid #45475a; border-radius:12px; padding:8px 12px">
      <textarea id="chatInput" rows="1" placeholder="Ask anything… (Cmd+Enter to send)"
                onkeydown="if((event.metaKey||event.ctrlKey) && event.key==='Enter') sendChatMessage()"
                oninput="this.style.height='auto'; this.style.height=this.scrollHeight+'px'"
                style="flex:1; resize:none; background:none; border:none; outline:none;
                       color:#cdd6f4; font-size:13px; max-height:140px; line-height:1.5">
      </textarea>
      <button onclick="sendChatMessage()" id="chat-send-btn"
              style="width:32px; height:32px; border-radius:50%; background:#89b4fa;
                     border:none; color:#1e1e2e; font-size:18px; cursor:pointer;
                     display:flex; align-items:center; justify-content:center;
                     flex-shrink:0; font-weight:700">
        ↑
      </button>
    </div>
    <div id="chat-status" style="font-size:10px; color:#6c7086; margin-top:6px; text-align:center; min-height:14px"></div>
  </div>
</div>
```

---

### CSS (paste into your stylesheet)

```css
/* ── Chat sidebar slide-in animation ── */
#chat-sidebar {
  transition: transform 0.25s ease;
  transform: translateX(100%);
}
#chat-sidebar.open {
  transform: translateX(0);
  display: flex !important;
}

/* ── Message bubbles ── */
.chat-msg-row {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}
.chat-msg-row.user {
  flex-direction: row-reverse;
}
.chat-avatar {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
  background: #313244;
}
.chat-bubble {
  max-width: 80%;
  padding: 10px 14px;
  border-radius: 16px;
  font-size: 13px;
  line-height: 1.55;
  color: #cdd6f4;
  background: #313244;
  white-space: pre-wrap;
  word-break: break-word;
}
.chat-msg-row.user .chat-bubble {
  background: #1e3a5f;
  border-bottom-right-radius: 4px;
}
.chat-msg-row.assistant .chat-bubble {
  border-bottom-left-radius: 4px;
}
/* Code blocks inside bubbles */
.chat-bubble pre {
  background: #181825;
  border-radius: 8px;
  padding: 12px;
  overflow-x: auto;
  margin: 8px 0 0;
  font-size: 11.5px;
  position: relative;
}
.chat-bubble code {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
}
/* Thinking indicator */
.thinking-dots {
  display: inline-flex;
  gap: 4px;
  padding: 10px 14px;
}
.thinking-dots span {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: #6c7086;
  animation: bounce 1.2s infinite;
}
.thinking-dots span:nth-child(2) { animation-delay: .2s; }
.thinking-dots span:nth-child(3) { animation-delay: .4s; }
@keyframes bounce {
  0%, 80%, 100% { transform: translateY(0); }
  40%           { transform: translateY(-6px); }
}
/* Active model button highlight */
button.model-active {
  background: #89b4fa !important;
  color: #1e1e2e !important;
  border-color: #89b4fa !important;
}
```

---

### JavaScript (complete, self-contained)

Paste this in a `<script>` tag at the bottom of your page. Adjust the two constants at the top.

```javascript
// ── CONFIG (adjust these) ─────────────────────────────────────────
const CHAT_API_BASE   = '';        // e.g. '' for same-origin, or 'http://localhost:3000'
const CHAT_PROJECT_ID = null;      // set to your project ID string, or null if single-project
// ──────────────────────────────────────────────────────────────────

let chatOpen     = false;
let chatMessages = [];              // [{role, content}]
let chatModel    = 'deepseek-chat';
let apiKeySet    = false;

// ── Lifecycle ─────────────────────────────────────────────────────

async function initChat() {
  try {
    const r = await fetch(CHAT_API_BASE + '/api/config');
    if (r.ok) {
      const cfg = await r.json();
      apiKeySet = cfg.api_key_set;
      if (cfg.selected_model) {
        chatModel = cfg.selected_model;
        updateModelButtons();
      }
    }
  } catch (e) { console.warn('Chat config check failed', e); }
}

async function openChat() {
  chatOpen = true;
  const sidebar = document.getElementById('chat-sidebar');
  sidebar.style.display = 'flex';
  sidebar.classList.add('open');
  document.getElementById('chat-toggle-btn').classList.add('model-active');

  document.getElementById('api-setup').style.display = apiKeySet ? 'none' : 'block';

  try {
    const url = CHAT_API_BASE + '/api/chat/history'
              + (CHAT_PROJECT_ID ? `?project_id=${CHAT_PROJECT_ID}` : '');
    const r = await fetch(url);
    if (r.ok) {
      const data = await r.json();
      chatMessages = data.messages || [];
      renderMessages();
    }
  } catch (e) { console.error('Load history failed', e); }

  document.getElementById('chatInput').focus();
}

function closeChat() {
  chatOpen = false;
  const sidebar = document.getElementById('chat-sidebar');
  sidebar.classList.remove('open');
  document.getElementById('chat-toggle-btn').classList.remove('model-active');
  setTimeout(() => { sidebar.style.display = 'none'; }, 250);
}

// ── Model switching ───────────────────────────────────────────────

function setChatModel(model) {
  chatModel = model;
  updateModelButtons();
  // Persist selection to server (sends 'KEEP_EXISTING' so it does not wipe the API key)
  fetch(CHAT_API_BASE + '/api/chat/config', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ api_key: 'KEEP_EXISTING', model })
  }).catch(console.warn);
}

function updateModelButtons() {
  ['chat', 'coder', 'reasoner'].forEach(m => {
    const btn = document.getElementById(`model-${m}-btn`);
    if (btn) btn.classList.toggle('model-active', chatModel === `deepseek-${m}`);
  });
  const badge = document.getElementById('model-badge');
  if (badge) badge.textContent = {
    'deepseek-chat':     'V3',
    'deepseek-coder':    'Coder',
    'deepseek-reasoner': 'R1',
  }[chatModel] || chatModel;
}

// ── API key setup ─────────────────────────────────────────────────

async function saveApiKey() {
  const key = document.getElementById('api-key-input').value.trim();
  if (!key) return;
  try {
    const r = await fetch(CHAT_API_BASE + '/api/chat/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ api_key: key, model: chatModel })
    });
    if (r.ok) {
      apiKeySet = true;
      document.getElementById('api-setup').style.display = 'none';
    }
  } catch (e) { alert('Failed to save API key: ' + e.message); }
}

// ── Send message ──────────────────────────────────────────────────

async function sendChatMessage() {
  const input = document.getElementById('chatInput');
  const message = input.value.trim();
  if (!message) return;

  if (!apiKeySet) {
    document.getElementById('api-setup').style.display = 'block';
    return;
  }

  input.value = '';
  input.style.height = 'auto';

  // Append user bubble immediately
  chatMessages.push({ role: 'user', content: message });
  renderMessages();
  showThinking();

  document.getElementById('chat-send-btn').disabled = true;
  setStatus('Generating…');

  try {
    const body = {
      message,
      model: chatModel,
      ...(CHAT_PROJECT_ID && { project_id: CHAT_PROJECT_ID }),
    };
    const r = await fetch(CHAT_API_BASE + '/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)
    });

    removeThinking();

    if (!r.ok) {
      const err = await r.text();
      throw new Error(err || `HTTP ${r.status}`);
    }

    const data = await r.json();
    chatMessages.push({ role: 'assistant', content: data.response });
    renderMessages();
    setStatus(`${chatModel} · ${(data.context_size / 1000).toFixed(1)}k ctx chars`);

  } catch (e) {
    removeThinking();
    chatMessages.push({ role: 'assistant', content: `Error: ${e.message}` });
    renderMessages();
    setStatus('');
  } finally {
    document.getElementById('chat-send-btn').disabled = false;
  }
}

// ── Clear chat ────────────────────────────────────────────────────

async function clearChat() {
  chatMessages = [];
  renderMessages();
  setStatus('');
  try {
    await fetch(CHAT_API_BASE + '/api/chat/clear', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ project_id: CHAT_PROJECT_ID })
    });
  } catch (e) { console.warn('Clear failed', e); }
}

// ── Rendering ─────────────────────────────────────────────────────

function renderMessages() {
  const container = document.getElementById('chatMessages');
  container.innerHTML = '';

  if (chatMessages.length === 0) {
    container.innerHTML = `
      <div style="text-align:center; color:#6c7086; font-size:12px; margin-top:40px">
        <div style="font-size:32px; margin-bottom:8px">🤖</div>
        <div>Ask me anything about your project.</div>
      </div>`;
    return;
  }

  for (const msg of chatMessages) {
    container.appendChild(buildBubble(msg.role, msg.content));
  }
  scrollToBottom();
}

function buildBubble(role, content) {
  const row = document.createElement('div');
  row.className = `chat-msg-row ${role}`;

  const avatar = document.createElement('div');
  avatar.className = 'chat-avatar';
  avatar.textContent = role === 'user' ? '👤' : '🤖';

  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble';
  bubble.innerHTML = formatMessage(content);  // see below

  row.appendChild(avatar);
  row.appendChild(bubble);
  return row;
}

function formatMessage(text) {
  // Minimal markdown-ish formatter — swap for a real library (marked.js, etc.) if desired
  return text
    // fenced code blocks
    .replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) =>
      `<pre><code class="language-${lang}">${escHtml(code.trim())}</code></pre>`)
    // inline code
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    // bold
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    // newlines → <br>
    .replace(/\n/g, '<br>');
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function showThinking() {
  const container = document.getElementById('chatMessages');
  const row = document.createElement('div');
  row.className = 'chat-msg-row assistant';
  row.id = 'thinking-indicator';
  row.innerHTML = `
    <div class="chat-avatar">🤖</div>
    <div class="chat-bubble thinking-dots">
      <span></span><span></span><span></span>
    </div>`;
  container.appendChild(row);
  scrollToBottom();
}

function removeThinking() {
  document.getElementById('thinking-indicator')?.remove();
}

function scrollToBottom() {
  const c = document.getElementById('chatMessages');
  c.scrollTop = c.scrollHeight;
}

function setStatus(msg) {
  const el = document.getElementById('chat-status');
  if (el) el.textContent = msg;
}

// ── Boot ──────────────────────────────────────────────────────────
initChat();
```

---

## Model Selection & Configuration

| Model | ID | Best for | Token limit | Notes |
|---|---|---|---|---|
| DeepSeek Chat (V3) | `deepseek-chat` | General Q&A, fast responses | 64k | Cheapest |
| DeepSeek Coder | `deepseek-coder` | Code analysis, refactoring | 128k | Default in Cartographer |
| DeepSeek Reasoner (R1) | `deepseek-reasoner` | Complex multi-step reasoning | 128k | Slower, no system prompt |

**Model-specific quirks:**
- **R1 (reasoner)**: Does not accept a `system` message — fold all context into the user message.
- **Coder**: Benefits from explicit file-path code block format (`// File: x.py`).
- **V3 (chat)**: Best for conversational explanations.

---

## Adapting the Context Builder

The `build_context()` function is the most project-specific piece. Here is what to plug in:

| Cartographer field | Your equivalent |
|---|---|
| `project_data['name']` | App/project name |
| `project_data['health_score']` | Any scalar health/quality metric |
| `project_data['files']` | List of document/record metadata dicts |
| `project_data['agent_context']` | Pre-generated summary (optional) |
| `project_data['contents'][id]` | Raw file text or document body |

If you have **no file system** (e.g. you're building a support chat), replace `build_context` with:

```python
def build_context(query: str, user_data: dict) -> str:
    return f"""USER CONTEXT:
- Account: {user_data.get('name')}
- Plan:    {user_data.get('plan')}
- History: {user_data.get('recent_actions')}

RELEVANT DOCS:
{user_data.get('kb_snippets', '')}
"""
```

---

## Multi-Project Mode

The original app supports loading two codebases simultaneously.

**Backend**: maintain a `PROJECTS` dict keyed by project ID. Pass both IDs when calling `build_multi_project_context`:

```python
PROJECTS = {}  # {project_id: {'root': str, 'scan_data': dict, 'chat_history': list}}

def build_multi_project_context(query, project_ids, include_files=[]):
    if len(project_ids) == 1:
        return build_context(query, PROJECTS[project_ids[0]]['scan_data'])

    combined = f"MULTI-PROJECT QUERY: {query}\n\n"
    for pid in project_ids[:2]:
        if pid not in PROJECTS:
            continue
        ctx = build_context(query, PROJECTS[pid]['scan_data'])
        combined += f"\n{'='*60}\nPROJECT: {PROJECTS[pid]['name']}\n{'='*60}\n{ctx}"

    combined += "\nCROSS-PROJECT INSTRUCTIONS:\n- Compare patterns between projects\n- Note integration points\n"
    return truncate_to_tokens(combined, max_tokens=100_000)
```

**Frontend**: add a multi-project toggle and pass `project_ids: [id1, id2]` in the POST body.

---

## Security Checklist

Before deploying beyond localhost:

- [ ] **Never expose the API key** — serve only `api_key_set: true/false`, not the key itself
- [ ] **Bind to localhost** — `HTTPServer(('127.0.0.1', port), Handler)` not `''` if internet-facing
- [ ] **Path traversal** — if you serve file contents, resolve and validate paths stay within the project root:
  ```python
  full = (root / rel_path).resolve()
  full.relative_to(root.resolve())  # raises ValueError if outside
  ```
- [ ] **Command injection** — if you expose `exec-command`, whitelist allowed commands; never pass raw user input to `shell=True`
- [ ] **Rate limiting** — add per-IP limits or a token bucket if deploying publicly
- [ ] **CORS** — the `Access-Control-Allow-Origin: *` header is fine for localhost tools; restrict it for production
- [ ] **`.chat_config.json`** — add to `.gitignore` immediately

---

## Quick-Start Minimal Example

A complete standalone script you can drop into any empty folder to get a working AI chat server:

```python
#!/usr/bin/env python3
"""
Minimal AI Chat Server
Run: python3 chat_server.py
Visit: http://localhost:8080
"""
import os, json, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime

# ── Paste the config, token, and API functions from sections above ──
# (load_config, save_config, estimate_tokens, truncate_to_tokens, call_deepseek)
# For this skeleton we assume they exist.

CHAT_HISTORY = []

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        from urllib.parse import urlparse
        p = urlparse(self.path).path
        if p in ('/', '/index.html'):
            html = Path('chat.html').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', len(html))
            self.end_headers()
            self.wfile.write(html)
        elif p == '/api/config':
            self._json({'api_key_set': bool(DEEPSEEK_API_KEY), 'selected_model': SELECTED_MODEL})
        elif p == '/api/chat/history':
            self._json({'messages': CHAT_HISTORY})
        else:
            self.send_error(404)

    def do_POST(self):
        from urllib.parse import urlparse
        length = int(self.headers.get('Content-Length', 0))
        body   = self.rfile.read(length).decode()
        data   = json.loads(body) if body else {}
        p      = urlparse(self.path).path

        if p == '/api/chat':
            msg   = data.get('message', '').strip()
            model = data.get('model', SELECTED_MODEL)
            if not msg:
                self.send_error(400, 'Missing message')
                return
            context = "No project loaded — general assistant mode."
            try:
                reply = call_deepseek(msg, context, model, CHAT_HISTORY)
                CHAT_HISTORY.append({'role': 'user',      'content': msg})
                CHAT_HISTORY.append({'role': 'assistant', 'content': reply})
                self._json({'response': reply, 'model': model, 'context_size': len(context)})
            except Exception as e:
                self.send_error(500, str(e))

        elif p == '/api/chat/config':
            global DEEPSEEK_API_KEY, SELECTED_MODEL
            key   = data.get('api_key', '').strip()
            model = data.get('model', '')
            if key and key != 'KEEP_EXISTING':
                DEEPSEEK_API_KEY = key
            if model:
                SELECTED_MODEL = model
            save_config()
            self._json({'success': True, 'api_key_set': bool(DEEPSEEK_API_KEY), 'model': SELECTED_MODEL})

        elif p == '/api/chat/clear':
            global CHAT_HISTORY
            CHAT_HISTORY = []
            self._json({'success': True})

        else:
            self.send_error(404)

    def _json(self, d):
        b = json.dumps(d).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(b))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, fmt, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {fmt % args}")


if __name__ == '__main__':
    load_config()
    server = HTTPServer(('127.0.0.1', 8080), Handler)
    print("Chat server running at http://localhost:8080")
    print("Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
```

Then create `chat.html` using the HTML + CSS + JS from the sections above.

---

*End of rebuild guide — generated from Codebase Cartographer on 2026-02-21*
