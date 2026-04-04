"""OpenClaw gateway integration.

Reads agent registration from ~/.openclaw/openclaw.json and provides
gateway status, agent metadata, and SOUL.md loading from registered
agent directories.
"""

import json
import os
from pathlib import Path
from typing import Optional

OPENCLAW_HOME = Path.home() / ".openclaw"
OPENCLAW_CONFIG = OPENCLAW_HOME / "openclaw.json"
GATEWAY_PORT = 18789

# Agent ID → persona ID mapping (reverse of OPENCLAW_AGENT_MAP)
AGENT_PERSONA_MAP = {
    "diamond-bull": "bullish_alpha",
    "diamond-value": "value_contrarian",
    "diamond-quant": "quant_momentum",
}

PERSONA_AGENT_MAP = {v: k for k, v in AGENT_PERSONA_MAP.items()}

AGENT_ORDER = ["diamond-bull", "diamond-value", "diamond-quant"]


def load_openclaw_config() -> dict:
    """Load the master openclaw.json config."""
    if not OPENCLAW_CONFIG.exists():
        return {}
    try:
        return json.loads(OPENCLAW_CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_registered_agents() -> list[dict]:
    """Get all diamond agents registered in OpenClaw."""
    config = load_openclaw_config()
    agents = config.get("agents", {}).get("list", [])
    diamond_agents = []
    for agent in agents:
        aid = agent.get("id", "")
        if aid.startswith("diamond-"):
            diamond_agents.append({
                "id": aid,
                "persona_id": AGENT_PERSONA_MAP.get(aid),
                "model": agent.get("model", "unknown"),
                "workspace": agent.get("workspace", ""),
                "agent_dir": agent.get("agentDir", ""),
            })
    return diamond_agents


def get_gateway_config() -> dict:
    """Get gateway configuration."""
    config = load_openclaw_config()
    gw = config.get("gateway", {})
    return {
        "port": gw.get("port", GATEWAY_PORT),
        "mode": gw.get("mode", "unknown"),
        "auth": gw.get("auth", {}).get("mode", "none"),
    }


def is_gateway_running() -> bool:
    """Check if the OpenClaw gateway is listening."""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", GATEWAY_PORT), timeout=1):
            return True
    except (ConnectionRefusedError, OSError, TimeoutError):
        return False


def get_gateway_status() -> dict:
    """Full gateway status for the API."""
    agents = get_registered_agents()
    gw_config = get_gateway_config()
    running = is_gateway_running()

    return {
        "gateway": {
            "running": running,
            "port": gw_config["port"],
            "mode": gw_config["mode"],
            "auth": gw_config["auth"],
            "url": f"ws://127.0.0.1:{gw_config['port']}" if running else None,
        },
        "agents": agents,
        "agent_count": len(agents),
        "openclaw_version": _get_version(),
        "config_path": str(OPENCLAW_CONFIG),
    }


def _get_version() -> str:
    """Try to get OpenClaw version from config or CLI."""
    config = load_openclaw_config()
    return config.get("version", "unknown")


def load_agent_soul(agent_id: str) -> Optional[str]:
    """Load SOUL.md from a registered agent's workspace directory.

    This proves the web app reads from the actual registered OpenClaw
    agent configurations, not just the repo's souls/ directory.
    """
    # Try workspace SOUL.md first (has operational context)
    workspace_soul = OPENCLAW_HOME / "agents" / agent_id / "workspace" / "SOUL.md"
    if workspace_soul.exists():
        return workspace_soul.read_text(encoding="utf-8")

    # Fall back to agent-level SOUL.md (personality only)
    agent_soul = OPENCLAW_HOME / "agents" / agent_id / "agent" / "SOUL.md"
    if agent_soul.exists():
        return agent_soul.read_text(encoding="utf-8")

    return None


def get_agent_metadata(agent_id: str) -> dict:
    """Get metadata for a registered agent."""
    config = load_openclaw_config()
    agents = config.get("agents", {}).get("list", [])
    for agent in agents:
        if agent.get("id") == agent_id:
            # Check for active sessions
            sessions_file = OPENCLAW_HOME / "agents" / agent_id / "sessions" / "sessions.json"
            session_count = 0
            if sessions_file.exists():
                try:
                    sdata = json.loads(sessions_file.read_text(encoding="utf-8"))
                    session_count = len(sdata.get("sessions", []))
                except Exception:
                    pass

            return {
                "agent_id": agent_id,
                "persona_id": AGENT_PERSONA_MAP.get(agent_id),
                "model": agent.get("model", "unknown"),
                "registered": True,
                "session_count": session_count,
                "workspace": agent.get("workspace", ""),
                "source": "openclaw-gateway",
            }
    return {"agent_id": agent_id, "registered": False, "source": "direct"}
