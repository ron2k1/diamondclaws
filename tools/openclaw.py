"""OpenClaw embedded gateway integration.

DiamondClaws IS the gateway. Agent registration and SOUL.md loading
are self-contained — no external ~/.openclaw/ dependency required.
Config lives in config/openclaw.json, souls in souls/*.md.
"""

import json
import os
from pathlib import Path
from typing import Optional

APP_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = APP_ROOT / "config"
SOULS_DIR = APP_ROOT / "souls"
OPENCLAW_CONFIG = CONFIG_DIR / "openclaw.json"

# Agent ID <-> persona ID mapping
AGENT_PERSONA_MAP = {
    "diamond-bull": "bullish_alpha",
    "diamond-value": "value_contrarian",
    "diamond-quant": "quant_momentum",
}

PERSONA_AGENT_MAP = {v: k for k, v in AGENT_PERSONA_MAP.items()}

AGENT_ORDER = ["diamond-bull", "diamond-value", "diamond-quant"]


def _load_config() -> dict:
    """Load the embedded openclaw.json config."""
    if not OPENCLAW_CONFIG.exists():
        return {}
    try:
        return json.loads(OPENCLAW_CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_registered_agents() -> list[dict]:
    """Get all diamond agents from the embedded config."""
    config = _load_config()
    agents = config.get("agents", {}).get("list", [])
    result = []
    for agent in agents:
        aid = agent.get("id", "")
        result.append({
            "id": aid,
            "persona_id": agent.get("persona_id") or AGENT_PERSONA_MAP.get(aid),
            "model": agent.get("model", "unknown"),
            "soul": agent.get("soul", ""),
        })
    return result


def get_gateway_status() -> dict:
    """Gateway status — DiamondClaws IS the gateway, always running."""
    config = _load_config()
    gw = config.get("gateway", {})
    agents = get_registered_agents()
    port = int(os.getenv("PORT", 8000))

    return {
        "gateway": {
            "running": True,
            "port": port,
            "mode": gw.get("mode", "embedded"),
            "auth": gw.get("auth", {}).get("mode", "none"),
            "url": f"http://0.0.0.0:{port}",
        },
        "agents": agents,
        "agent_count": len(agents),
        "version": config.get("version", "1.0.0"),
        "config_path": str(OPENCLAW_CONFIG),
    }


def load_agent_soul(agent_id: str) -> Optional[str]:
    """Load SOUL.md for an agent from the souls/ directory."""
    config = _load_config()
    agents = config.get("agents", {}).get("list", [])

    # Find soul path from config
    for agent in agents:
        if agent.get("id") == agent_id:
            soul_path = APP_ROOT / agent.get("soul", "")
            if soul_path.exists():
                return soul_path.read_text(encoding="utf-8")
            break

    # Fallback: try persona_id mapping
    pid = AGENT_PERSONA_MAP.get(agent_id)
    if pid:
        fallback = SOULS_DIR / f"{pid}.md"
        if fallback.exists():
            return fallback.read_text(encoding="utf-8")

    return None


def get_agent_metadata(agent_id: str) -> dict:
    """Get metadata for a registered agent."""
    config = _load_config()
    agents = config.get("agents", {}).get("list", [])
    for agent in agents:
        if agent.get("id") == agent_id:
            return {
                "agent_id": agent_id,
                "persona_id": agent.get("persona_id") or AGENT_PERSONA_MAP.get(agent_id),
                "model": agent.get("model", "unknown"),
                "registered": True,
                "source": "diamondclaws-gateway",
            }
    return {"agent_id": agent_id, "registered": False, "source": "direct"}
