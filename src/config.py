"""
Config management — persists to ~/.rentsearch/config.json
Never writes to the project directory to avoid accidental git commits.
"""

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".rentsearch"
CONFIG_PATH = CONFIG_DIR / "config.json"

# Supported LLM providers and their metadata
PROVIDERS: dict[str, dict] = {
    "Anthropic": {
        "models": ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5-20251001"],
        "default_model": "claude-sonnet-4-6",
        "needs_key": True,
        "default_base_url": "",
        "key_hint": "sk-ant-...",
        "key_url": "console.anthropic.com",
    },
    "OpenAI": {
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o3-mini"],
        "default_model": "gpt-4o",
        "needs_key": True,
        "default_base_url": "",
        "key_hint": "sk-...",
        "key_url": "platform.openai.com",
    },
    "Google Gemini": {
        "models": [
            "gemini/gemini-2.0-flash",
            "gemini/gemini-1.5-pro",
            "gemini/gemini-1.5-flash",
        ],
        "default_model": "gemini/gemini-2.0-flash",
        "needs_key": True,
        "default_base_url": "",
        "key_hint": "AIza...",
        "key_url": "aistudio.google.com",
    },
    "Groq": {
        "models": [
            "groq/llama-3.3-70b-versatile",
            "groq/llama3-70b-8192",
            "groq/mixtral-8x7b-32768",
            "groq/gemma2-9b-it",
        ],
        "default_model": "groq/llama-3.3-70b-versatile",
        "needs_key": True,
        "default_base_url": "",
        "key_hint": "gsk_...",
        "key_url": "console.groq.com",
    },
    "Mistral": {
        "models": [
            "mistral/mistral-large-latest",
            "mistral/mistral-small-latest",
            "mistral/open-mistral-7b",
        ],
        "default_model": "mistral/mistral-large-latest",
        "needs_key": True,
        "default_base_url": "",
        "key_hint": "...",
        "key_url": "console.mistral.ai",
    },
    "Ollama (local)": {
        "models": [
            "ollama/llama3",
            "ollama/llama3:70b",
            "ollama/mistral",
            "ollama/phi3",
            "ollama/gemma2",
        ],
        "default_model": "ollama/llama3",
        "needs_key": False,
        "default_base_url": "http://localhost:11434",
        "key_hint": "",
        "key_url": "ollama.ai",
    },
}

DEFAULTS = {
    "llm_provider": "Anthropic",
    "llm_model": "claude-sonnet-4-6",
    "llm_api_key": "",
    "llm_base_url": "",
    "default_city": "",
    "default_max_distance": 15,
    "default_min_price": 1000,
    "default_max_price": 3000,
    "default_min_beds": 1,
    "default_max_beds": 3,
}


def load_config() -> dict:
    """Load config from ~/.rentsearch/config.json.
    Returns defaults if the file doesn't exist or is malformed.
    """
    if not CONFIG_PATH.exists():
        return dict(DEFAULTS)
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return {**DEFAULTS, **data}
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULTS)


def save_config(config: dict) -> None:
    """Write config to ~/.rentsearch/config.json."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def has_api_key() -> bool:
    """Returns True if the selected provider is configured and ready to use."""
    cfg = load_config()
    provider = cfg.get("llm_provider", "Anthropic")
    meta = PROVIDERS.get(provider, {})
    if not meta.get("needs_key", True):
        return True  # Ollama — no key required
    return bool(cfg.get("llm_api_key", "").strip())


def test_llm_connection(
    provider: str, model: str, api_key: str, base_url: str
) -> tuple[bool, str]:
    """Validate the provider/model/key combo by making a minimal LLM call.
    Returns (success, message).
    """
    try:
        import litellm
        litellm.suppress_debug_info = True
        kwargs: dict = {
            "model": model,
            "messages": [{"role": "user", "content": "Say the word OK and nothing else."}],
            "max_tokens": 5,
        }
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["api_base"] = base_url
        litellm.completion(**kwargs)
        return True, f"Connected to {provider} successfully"
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if any(k in msg.lower() for k in ("auth", "401", "invalid", "api key", "permission")):
            return False, "Invalid API key — check and re-enter"
        return False, f"Connection error: {msg[:140]}"
