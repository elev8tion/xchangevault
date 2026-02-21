import os
import json
from pathlib import Path
from datetime import datetime

# ---- Config & Models -----------------------------------------------------

CONFIG_FILE = Path(__file__).parent / '.chat_config.json'

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

DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', '')
SELECTED_MODEL   = MODEL_DEEPSEEK_CHAT


def load_config() -> bool:
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
        except Exception:
            return False
    return False


def save_config(api_key: str = None, model: str = None) -> bool:
    global DEEPSEEK_API_KEY, SELECTED_MODEL
    if api_key is not None:
        DEEPSEEK_API_KEY = api_key
    if model is not None:
        SELECTED_MODEL = model
    try:
        cfg = {
            'api_key':  DEEPSEEK_API_KEY,
            'model':    SELECTED_MODEL,
            'saved_at': datetime.now().isoformat(),
        }
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
        return True
    except Exception:
        return False


# ---- Token counting ------------------------------------------------------
try:
    import tiktoken
    _ENCODING = tiktoken.get_encoding("cl100k_base")
except Exception:
    _ENCODING = None


def estimate_tokens(text: str) -> int:
    if _ENCODING:
        try:
            return len(_ENCODING.encode(text, disallowed_special=()))
        except Exception:
            pass
    return len(text) // 3


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    if _ENCODING:
        try:
            tokens = _ENCODING.encode(text, disallowed_special=())
            if len(tokens) <= max_tokens:
                return text
            return _ENCODING.decode(tokens[:max_tokens])
        except Exception:
            pass
    # Fallback character cut
    if estimate_tokens(text) <= max_tokens:
        return text
    return text[:max_tokens * 3]


# ---- Context builder for extractor --------------------------------------

def build_extractor_context(message: str, plan: dict = None, scan: dict = None) -> str:
    """Assemble a concise context for the extractor domain.

    Includes project roots, selection summary, brand map, patterns, and residuals/diffs snippets.
    """
    top = f"""REQUEST: {message}
"""

    middle = ""
    if plan:
        middle += f"""
PLAN SUMMARY:
source_root: {plan.get('source_root')}
dest_root:   {plan.get('dest_root')}
files:       {len(plan.get('actions', []))}
brand_map:   {plan.get('brand_map', [])}
patterns:    {plan.get('patterns', [])}
fix_imports: {plan.get('fix_imports', {})}
"""
        prev = plan.get('previews') or {}
        residuals = prev.get('residuals') or {}
        middle += f"""
RESIDUALS:
old_brand_hits: {list(residuals.get('old_brand_hits', {}).items())[:20]}
secret_hits:    {residuals.get('secret_hits', [])[:20]}
import_warns:   {residuals.get('import_warnings', [])[:20]}
"""
        diffs = prev.get('diffs') or {}
        if diffs:
            # include small sample of diffs, truncated
            sample = list(diffs.items())[:3]
            for path, diff in sample:
                middle += f"\nDIFF {path}:\n" + truncate_to_tokens(diff, 1500) + "\n"

    elif scan:
        middle += f"""
SCAN SUMMARY:
root:  {scan.get('root')}
files: {scan.get('stats', {}).get('files')}
dirs:  {scan.get('stats', {}).get('dirs')}
stack: {scan.get('stack')}
"""

    bottom = """
INSTRUCTIONS:
- Suggest concrete brand_map entries and safe structural patterns (Comby/ast-grep) if useful
- Suggest import fixes where necessary (Python/JS)
- Return actionable, concise steps
"""
    raw = top + middle + bottom
    return truncate_to_tokens(raw, max_tokens=60_000)


# ---- DeepSeek calls ------------------------------------------------------

def _client():
    if not DEEPSEEK_API_KEY:
        raise ValueError("DEEPSEEK_API_KEY not set. Configure via settings or DEEPSEEK_API_KEY env var.")
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("Run: pip install openai")
    return OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")


def call_chat(message: str, context: str, model: str = None, chat_history: list = None) -> str:
    m = (model or SELECTED_MODEL)
    temperature = OPTIMAL_TEMPS.get(m, 0.7)
    system_content = f"""You are a senior software engineer and code extraction assistant.

Context:
{context}

When suggesting changes:
- Use markdown lists and code blocks
- Be concise and specific
"""
    messages = []
    if system_content:
        messages.append({"role": "system", "content": system_content})
    if chat_history:
        messages.extend(chat_history[-10:])
    messages.append({"role": "user", "content": message})

    resp = _client().chat.completions.create(
        model=m,
        messages=messages,
        temperature=temperature,
        max_tokens=2000,
    )
    return resp.choices[0].message.content


def call_structured(message: str, context: str, model: str = None, schema: str = None) -> dict:
    m = (model or SELECTED_MODEL)
    if not schema:
        schema = """
{
  "summary": "Short overview",
  "brand_map": [{"from": "OldBrand", "to": "NewBrand"}],
  "patterns": [{"tool": "comby", "matcher": ".", "match": "...", "rewrite": "..."}],
  "import_fixes": {"python": false, "js": false},
  "risks": ["..."],
  "recommendations": ["..."]
}
"""
    system_content = f"""Analyze and return ONLY valid JSON matching this shape:
{schema}

Context:
{context}
"""
    resp = _client().chat.completions.create(
        model=m,
        messages=[
            {"role": "system", "content": system_content},
            {"role": "user",   "content": message},
        ],
        temperature=0.7,
        max_tokens=2000,
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content)


# ---- History -------------------------------------------------------------

PROJECT_HISTORIES: dict = {}


def get_history(pid: str) -> list:
    return PROJECT_HISTORIES.setdefault(pid or 'default', [])


def append_history(pid: str, role: str, content: str):
    get_history(pid).append({"role": role, "content": content})


def clear_history(pid: str = None):
    if pid and pid in PROJECT_HISTORIES:
        PROJECT_HISTORIES[pid] = []
    elif not pid:
        PROJECT_HISTORIES.clear()

