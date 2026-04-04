"""OpenClaw gateway integration.

Reads agent config from the real OpenClaw installation at ~/.openclaw/.
Probes the live WebSocket gateway on port 18789 for real status.
SOUL.md loading from the repo's souls/ directory.
"""

import json
import os
from pathlib import Path
from typing import Optional

APP_ROOT = Path(__file__).resolve().parent.parent
SOULS_DIR = APP_ROOT / "souls"

# Real OpenClaw config
OPENCLAW_HOME = Path.home() / ".openclaw"
OPENCLAW_CONFIG = OPENCLAW_HOME / "openclaw.json"

# Agent ID <-> persona ID mapping
AGENT_PERSONA_MAP = {
    "diamond-bull": "bullish_alpha",
    "diamond-value": "value_contrarian",
    "diamond-quant": "quant_momentum",
}

PERSONA_AGENT_MAP = {v: k for k, v in AGENT_PERSONA_MAP.items()}

AGENT_ORDER = ["diamond-bull", "diamond-value", "diamond-quant"]


def _load_openclaw_config() -> dict:
    """Load the real ~/.openclaw/openclaw.json config."""
    if not OPENCLAW_CONFIG.exists():
        return {}
    try:
        return json.loads(OPENCLAW_CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_registered_agents() -> list[dict]:
    """Get diamond agents from the real OpenClaw config."""
    config = _load_openclaw_config()
    agents = config.get("agents", {}).get("list", [])
    result = []
    for agent in agents:
        aid = agent.get("id", "")
        if aid.startswith("diamond-"):
            result.append({
                "id": aid,
                "persona_id": AGENT_PERSONA_MAP.get(aid),
                "model": agent.get("model", "unknown"),
            })
    # Fallback if no openclaw config
    if not result:
        for aid, pid in AGENT_PERSONA_MAP.items():
            result.append({"id": aid, "persona_id": pid, "model": "unknown"})
    return result


async def get_gateway_status() -> dict:
    """Probe the real OpenClaw gateway and return live status."""
    from tools.gateway_client import probe_gateway

    agents = get_registered_agents()
    port = int(os.getenv("PORT", 8000))

    probe = await probe_gateway()

    return {
        "gateway": {
            "running": probe.get("running", False),
            "port": 18789 if probe.get("running") else port,
            "mode": "openclaw-ws" if probe.get("running") else "direct",
            "version": probe.get("version", "unknown"),
            "uptime_ms": probe.get("uptime_ms", 0),
            "channels": probe.get("channels", []),
            "url": "ws://127.0.0.1:18789" if probe.get("running") else None,
        },
        "agents": agents,
        "agent_count": len(agents),
        "gateway_agents": probe.get("diamond_agents", []),
        "gateway_total_agents": probe.get("agent_count", 0),
    }


def load_agent_soul(agent_id: str) -> Optional[str]:
    """Load SOUL.md for an agent from the repo's souls/ directory.

    Always uses the repo copy — the OpenClaw workspace copies contain
    tool-calling instructions (exec: python ...) that leak into chat.
    """
    pid = AGENT_PERSONA_MAP.get(agent_id)
    if pid:
        repo_soul = SOULS_DIR / f"{pid}.md"
        if repo_soul.exists():
            return repo_soul.read_text(encoding="utf-8")

    return None


def get_agent_metadata(agent_id: str) -> dict:
    """Get metadata for a registered agent."""
    config = _load_openclaw_config()
    agents = config.get("agents", {}).get("list", [])
    for agent in agents:
        if agent.get("id") == agent_id:
            return {
                "agent_id": agent_id,
                "persona_id": AGENT_PERSONA_MAP.get(agent_id),
                "model": agent.get("model", "unknown"),
                "registered": True,
                "source": "openclaw-gateway",
            }
    return {"agent_id": agent_id, "registered": False, "source": "direct"}
