"""Multi-provider LLM registry.

Maps provider IDs to base URLs, API key env vars, and available models.
Resolves API keys from environment variables first, then data/api_keys.json
(for keys entered via the Settings UI).

Model ID format: "provider/model-id"
  - openai/gpt-4.1-mini        -> OpenAI direct
  - google/gemini-2.0-flash     -> Google AI Studio direct
  - openrouter/openai/gpt-4.1-mini -> via OpenRouter proxy
"""

import json
import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = APP_ROOT / "data"
API_KEYS_FILE = DATA_DIR / "api_keys.json"
CONFIG_FILE = DATA_DIR / "config.json"

# ── Provider Registry ────────────────────────────────────────────────

PROVIDERS = {
    "openrouter": {
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
        "format": "openai",
        "description": "Universal — access 200+ models with one key",
        "key_url": "https://openrouter.ai/keys",
        "models": [
            {"id": "google/gemini-2.0-flash-001", "name": "Gemini 2.0 Flash"},
            {"id": "google/gemini-2.5-pro", "name": "Gemini 2.5 Pro"},
            {"id": "anthropic/claude-sonnet-4", "name": "Claude Sonnet 4"},
            {"id": "anthropic/claude-3.5-haiku", "name": "Claude 3.5 Haiku"},
            {"id": "openai/gpt-4.1-mini", "name": "GPT-4.1 Mini"},
            {"id": "openai/gpt-4.1", "name": "GPT-4.1"},
            {"id": "deepseek/deepseek-chat-v3-0324", "name": "DeepSeek V3"},
            {"id": "meta-llama/llama-4-maverick", "name": "Llama 4 Maverick"},
            {"id": "x-ai/grok-3-mini", "name": "Grok 3 Mini"},
            {"id": "mistralai/mistral-large-2511", "name": "Mistral Large"},
            {"id": "qwen/qwen3-235b-a22b", "name": "Qwen 3 235B"},
        ],
    },
    "openai": {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "key_env": "OPENAI_API_KEY",
        "format": "openai",
        "description": "GPT-4.1 models",
        "key_url": "https://platform.openai.com/api-keys",
        "models": [
            {"id": "gpt-4.1-mini", "name": "GPT-4.1 Mini"},
            {"id": "gpt-4.1", "name": "GPT-4.1"},
        ],
    },
    "google": {
        "name": "Google",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_env": "GOOGLE_API_KEY",
        "format": "openai",
        "description": "Gemini models via AI Studio",
        "key_url": "https://aistudio.google.com/apikey",
        "models": [
            {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash"},
            {"id": "gemini-2.5-pro-preview-05-06", "name": "Gemini 2.5 Pro"},
        ],
    },
    "anthropic": {
        "name": "Anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "key_env": "ANTHROPIC_API_KEY",
        "format": "anthropic",
        "description": "Claude models",
        "key_url": "https://console.anthropic.com/settings/keys",
        "models": [
            {"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4"},
            {"id": "claude-haiku-3-5-20241022", "name": "Claude 3.5 Haiku"},
        ],
    },
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "key_env": "DEEPSEEK_API_KEY",
        "format": "openai",
        "description": "DeepSeek V3 and R1",
        "key_url": "https://platform.deepseek.com/api_keys",
        "models": [
            {"id": "deepseek-chat", "name": "DeepSeek V3"},
            {"id": "deepseek-reasoner", "name": "DeepSeek R1"},
        ],
    },
    "xai": {
        "name": "xAI",
        "base_url": "https://api.x.ai/v1",
        "key_env": "XAI_API_KEY",
        "format": "openai",
        "description": "Grok models",
        "key_url": "https://console.x.ai/",
        "models": [
            {"id": "grok-3-mini", "name": "Grok 3 Mini"},
        ],
    },
    "mistral": {
        "name": "Mistral",
        "base_url": "https://api.mistral.ai/v1",
        "key_env": "MISTRAL_API_KEY",
        "format": "openai",
        "description": "Mistral models",
        "key_url": "https://console.mistral.ai/api-keys",
        "models": [
            {"id": "mistral-large-latest", "name": "Mistral Large"},
        ],
    },
}

FALLBACK_MODEL = "openrouter/google/gemini-2.0-flash-001"


# ── API Key Management ───────────────────────────────────────────────

def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def get_api_key(provider_id: str) -> str | None:
    """Get API key for a provider. Env var takes precedence over saved keys."""
    provider = PROVIDERS.get(provider_id)
    if not provider:
        return None

    # 1. Environment variable
    env_val = os.getenv(provider["key_env"], "").strip()
    if env_val:
        return env_val

    # 2. Saved keys from UI
    saved = _load_json(API_KEYS_FILE)
    val = saved.get(provider_id, "").strip()
    return val if val else None


def save_api_key(provider_id: str, key: str):
    """Save an API key entered via the Settings UI."""
    saved = _load_json(API_KEYS_FILE)
    if key.strip():
        saved[provider_id] = key.strip()
    else:
        saved.pop(provider_id, None)
    _save_json(API_KEYS_FILE, saved)


def delete_api_key(provider_id: str):
    """Remove a saved API key."""
    saved = _load_json(API_KEYS_FILE)
    saved.pop(provider_id, None)
    _save_json(API_KEYS_FILE, saved)


def mask_key(key: str) -> str:
    """Mask an API key for display: show first 4 and last 4 chars."""
    if not key or len(key) < 10:
        return "****"
    return f"{key[:4]}...{key[-4:]}"


def get_provider_status() -> dict:
    """Get status of all providers: configured, source, masked key, models."""
    result = {}
    saved_keys = _load_json(API_KEYS_FILE)

    for pid, prov in PROVIDERS.items():
        env_val = os.getenv(prov["key_env"], "").strip()
        saved_val = saved_keys.get(pid, "").strip()

        if env_val:
            configured = True
            source = "env"
            masked = mask_key(env_val)
        elif saved_val:
            configured = True
            source = "ui"
            masked = mask_key(saved_val)
        else:
            configured = False
            source = None
            masked = None

        result[pid] = {
            "name": prov["name"],
            "configured": configured,
            "source": source,
            "masked": masked,
            "key_env": prov["key_env"],
            "key_url": prov["key_url"],
            "description": prov["description"],
            "models": [
                {"id": f"{pid}/{m['id']}", "name": m["name"]}
                for m in prov["models"]
            ],
        }
    return result


# ── Model Resolution ─────────────────────────────────────────────────

def resolve_model(model_string: str) -> tuple[str, str, dict]:
    """Parse 'provider/model-id' into (provider_id, api_model_id, provider_config).

    For openrouter: 'openrouter/google/gemini-2.0-flash-001'
      -> ('openrouter', 'google/gemini-2.0-flash-001', {...})

    For direct: 'openai/gpt-4.1-mini'
      -> ('openai', 'gpt-4.1-mini', {...})
    """
    provider_id, _, model_id = model_string.partition("/")

    if provider_id in PROVIDERS and model_id:
        return provider_id, model_id, PROVIDERS[provider_id]

    # Unknown provider — try OpenRouter as fallback
    if "openrouter" in PROVIDERS:
        return "openrouter", model_string, PROVIDERS["openrouter"]

    raise ValueError(f"Unknown provider in model string: {model_string}")


def get_available_models() -> list[dict]:
    """Get all models from providers that have API keys configured."""
    models = []
    for pid, prov in PROVIDERS.items():
        if get_api_key(pid):
            for m in prov["models"]:
                models.append({
                    "id": f"{pid}/{m['id']}",
                    "name": m["name"],
                    "provider": prov["name"],
                    "provider_id": pid,
                })
    return models


# ── Config (default model + per-agent models) ───────────────────────

def _load_config() -> dict:
    return _load_json(CONFIG_FILE)


def _save_config(config: dict):
    _save_json(CONFIG_FILE, config)


def get_default_model() -> str:
    config = _load_config()
    return config.get("default_model", FALLBACK_MODEL)


def set_default_model(model: str):
    config = _load_config()
    config["default_model"] = model
    _save_config(config)


def get_agent_model(agent_id: str) -> str:
    """Get the model for a specific agent. Returns agent override or default."""
    config = _load_config()
    agent_models = config.get("agent_models", {})
    override = agent_models.get(agent_id)
    if override and override != "__default__":
        return override
    return get_default_model()


def set_agent_model(agent_id: str, model: str | None):
    """Set per-agent model override. None clears the override."""
    config = _load_config()
    if "agent_models" not in config:
        config["agent_models"] = {}
    if model:
        config["agent_models"][agent_id] = model
    else:
        config["agent_models"].pop(agent_id, None)
    _save_config(config)
