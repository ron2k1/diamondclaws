"""Provider registry — read-only view of OpenClaw's LLM configuration.

API keys and model config live in OpenClaw (~/.openclaw/).
This module provides display data for the DiamondClaws UI.
"""

import json
import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = APP_ROOT / "data"
CONFIG_FILE = DATA_DIR / "config.json"
OPENCLAW_HOME = Path.home() / ".openclaw"
OPENCLAW_CONFIG = OPENCLAW_HOME / "openclaw.json"

FALLBACK_MODEL = "openrouter/google/gemini-2.0-flash-001"

# ── Provider Registry (for UI display) ──────────────────────────────

PROVIDERS = {
    "openrouter": {
        "name": "OpenRouter",
        "key_env": "OPENROUTER_API_KEY",
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
        "key_env": "OPENAI_API_KEY",
        "description": "GPT-4.1 models",
        "key_url": "https://platform.openai.com/api-keys",
        "models": [
            {"id": "gpt-4.1-mini", "name": "GPT-4.1 Mini"},
            {"id": "gpt-4.1", "name": "GPT-4.1"},
        ],
    },
    "anthropic": {
        "name": "Anthropic",
        "key_env": "ANTHROPIC_API_KEY",
        "description": "Claude models",
        "key_url": "https://console.anthropic.com/settings/keys",
        "models": [
            {"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4"},
            {"id": "claude-haiku-3-5-20241022", "name": "Claude 3.5 Haiku"},
        ],
    },
}


# ── JSON Helpers (also used by monitor for config persistence) ──────

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


# ── OpenClaw Config Reading ─────────────────────────────────────────

def _load_openclaw_config() -> dict:
    return _load_json(OPENCLAW_CONFIG)


def get_provider_status() -> dict:
    """Get provider status by reading OpenClaw's auth profiles."""
    result = {}
    for pid, prov in PROVIDERS.items():
        # Check if key is set in environment (OpenClaw uses env vars)
        env_val = os.getenv(prov["key_env"], "").strip()
        configured = bool(env_val)
        masked = f"{env_val[:4]}...{env_val[-4:]}" if env_val and len(env_val) >= 10 else None

        result[pid] = {
            "name": prov["name"],
            "configured": configured,
            "source": "openclaw" if configured else None,
            "masked": masked,
            "key_env": prov["key_env"],
            "key_url": prov["key_url"],
            "description": prov["description"],
            "models": [{"id": f"{pid}/{m['id']}", "name": m["name"]} for m in prov["models"]],
        }
    return result


def get_available_models() -> list[dict]:
    """Get all models from providers that have keys configured in OpenClaw."""
    models = []
    for pid, prov in PROVIDERS.items():
        if os.getenv(prov["key_env"], "").strip():
            for m in prov["models"]:
                models.append({
                    "id": f"{pid}/{m['id']}",
                    "name": m["name"],
                    "provider": prov["name"],
                    "provider_id": pid,
                })
    return models


def get_default_model() -> str:
    """Get default model from OpenClaw config."""
    oc = _load_openclaw_config()
    primary = oc.get("agents", {}).get("defaults", {}).get("model", {}).get("primary", "")
    return primary or FALLBACK_MODEL


def get_agent_model(agent_id: str) -> str:
    """Get model for a specific agent from OpenClaw config."""
    oc = _load_openclaw_config()
    agents = oc.get("agents", {}).get("list", [])
    for agent in agents:
        if agent.get("id") == agent_id:
            model = agent.get("model")
            if model:
                return model
    return get_default_model()
