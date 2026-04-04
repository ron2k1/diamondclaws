#!/usr/bin/env python3
"""
DiamondClaws — OpenClaw Gateway Setup

Creates the full ~/.openclaw/ directory structure so DiamondClaws agents
work out of the box on any machine. Run once after cloning the repo.

Usage:
    python scripts/setup_openclaw.py

What it does:
    1. Creates ~/.openclaw/ directory tree
    2. Writes openclaw.json with 3 diamond agents registered
    3. Creates agent workspaces with SOUL.md, IDENTITY.md, TOOLS.md
    4. Generates Ed25519 device identity for gateway auth
    5. Creates auth-profiles.json pointing to env vars (no hardcoded keys)
"""

import json
import os
import platform
import shutil
import sys
import time
import uuid
from pathlib import Path

# Resolve paths
REPO_ROOT = Path(__file__).resolve().parent.parent
SOULS_DIR = REPO_ROOT / "souls"
CONFIG_DIR = REPO_ROOT / "config"
OPENCLAW_HOME = Path.home() / ".openclaw"

AGENTS = [
    {
        "id": "diamond-bull",
        "soul": "bullish_alpha.md",
        "name": "Bullish Alpha",
        "role": "Senior Equity Research Analyst, Growth & Momentum Coverage",
        "emoji": "\U0001f4c8",
        "catchphrase": "This represents a generational opportunity. Position accordingly.",
    },
    {
        "id": "diamond-value",
        "soul": "value_contrarian.md",
        "name": "Value Contrarian",
        "role": "Deep Value Portfolio Strategist, Contrarian Coverage",
        "emoji": "\U0001f48e",
        "catchphrase": "The market is pricing this as a zero-probability event. We disagree profoundly.",
    },
    {
        "id": "diamond-quant",
        "soul": "quant_momentum.md",
        "name": "Quant Momentum",
        "role": "Senior Quantitative Researcher, Systematic Strategies",
        "emoji": "\u26a1",
        "catchphrase": "The momentum factor is extremely strong. The data speaks for itself.",
    },
]


def _generate_device_identity() -> dict:
    """Generate Ed25519 keypair for gateway authentication."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            NoEncryption,
            PrivateFormat,
            PublicFormat,
        )

        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        private_pem = private_key.private_bytes(
            Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
        ).decode()
        public_pem = public_key.public_bytes(
            Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
        ).decode()

        return {
            "version": 1,
            "deviceId": f"dc-{uuid.uuid4().hex[:12]}",
            "publicKeyPem": public_pem,
            "privateKeyPem": private_pem,
            "createdAtMs": int(time.time() * 1000),
        }
    except ImportError:
        print("  [!] cryptography package not installed — skipping device identity")
        print("      Install with: pip install cryptography")
        return None


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  [+] {path}")


def _write_text(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  [+] {path}")


def setup():
    print("=" * 60)
    print("  DiamondClaws — OpenClaw Gateway Setup")
    print("=" * 60)
    print()

    if OPENCLAW_HOME.exists():
        print(f"  [i] ~/.openclaw/ already exists at {OPENCLAW_HOME}")
        # Check if agents already registered
        existing_config = OPENCLAW_HOME / "openclaw.json"
        if existing_config.exists():
            try:
                cfg = json.loads(existing_config.read_text(encoding="utf-8"))
                agent_ids = [a.get("id") for a in cfg.get("agents", {}).get("list", [])]
                diamond_agents = [a for a in agent_ids if a and a.startswith("diamond-")]
                if len(diamond_agents) >= 3:
                    print(f"  [i] Diamond agents already registered: {diamond_agents}")
                    resp = input("  [?] Overwrite agent configs? (y/N): ").strip().lower()
                    if resp != "y":
                        print("  [i] Skipping config — updating workspaces only")
                        _setup_workspaces()
                        print("\n  Done! Workspaces updated.\n")
                        return
            except Exception:
                pass

    # 1. Create directory structure
    print("\n  [1/5] Creating directory structure...")
    dirs = [
        OPENCLAW_HOME,
        OPENCLAW_HOME / "identity",
        OPENCLAW_HOME / "workspace",
    ]
    for agent in AGENTS:
        aid = agent["id"]
        dirs.extend([
            OPENCLAW_HOME / "agents" / aid / "agent",
            OPENCLAW_HOME / "agents" / aid / "sessions",
            OPENCLAW_HOME / "agents" / aid / "workspace" / "memory",
        ])
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    print(f"  [+] Created {len(dirs)} directories")

    # 2. Write openclaw.json
    print("\n  [2/5] Writing openclaw.json...")
    openclaw_config = _build_openclaw_config()

    # Merge with existing config if present
    existing_path = OPENCLAW_HOME / "openclaw.json"
    if existing_path.exists():
        try:
            existing = json.loads(existing_path.read_text(encoding="utf-8"))
            # Preserve auth, wizard, meta, channels — overwrite agents/gateway
            for key in ("auth", "wizard", "meta", "channels", "models"):
                if key in existing:
                    openclaw_config[key] = existing[key]
        except Exception:
            pass

    _write_json(OPENCLAW_HOME / "openclaw.json", openclaw_config)

    # 3. Generate device identity
    print("\n  [3/5] Device identity...")
    identity_path = OPENCLAW_HOME / "identity" / "device.json"
    if identity_path.exists():
        print(f"  [i] Device identity already exists — keeping existing")
    else:
        identity = _generate_device_identity()
        if identity:
            _write_json(identity_path, identity)
        else:
            print("  [!] Skipped — gateway auth won't work without cryptography package")

    # 4. Setup agent workspaces
    print("\n  [4/5] Setting up agent workspaces...")
    _setup_workspaces()

    # 5. Write agent auth profiles (env var references, not actual keys)
    print("\n  [5/5] Writing agent auth profiles...")
    _setup_auth_profiles()

    print()
    print("=" * 60)
    print("  Setup complete!")
    print("=" * 60)
    print()
    print("  Next steps:")
    print("    1. Set OPENROUTER_API_KEY in your .env file")
    print("    2. Start DiamondClaws:  uvicorn main:app --port 8000")
    print("    3. (Optional) Start gateway:  openclaw gateway start")
    print()
    print(f"  Config: {OPENCLAW_HOME / 'openclaw.json'}")
    print(f"  Agents: {', '.join(a['id'] for a in AGENTS)}")
    print()


def _build_openclaw_config() -> dict:
    """Build the openclaw.json config with diamond agents."""
    plat = platform.system()
    home = str(OPENCLAW_HOME)

    agent_list = [{"id": "main"}]  # default main agent

    for agent in AGENTS:
        aid = agent["id"]
        workspace = str(OPENCLAW_HOME / "agents" / aid / "workspace")
        agent_dir = str(OPENCLAW_HOME / "agents" / aid / "agent")

        # Use forward slashes on all platforms for consistency
        if plat == "Windows":
            workspace = workspace.replace("/", "\\")
            agent_dir = agent_dir.replace("/", "\\")

        agent_list.append({
            "id": aid,
            "name": aid,
            "workspace": workspace,
            "agentDir": agent_dir,
            "model": "openrouter/google/gemini-2.0-flash-001",
        })

    return {
        "meta": {
            "lastTouchedVersion": "diamondclaws-setup",
            "lastTouchedAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
        },
        "agents": {
            "defaults": {
                "model": {
                    "primary": "openrouter/google/gemini-2.0-flash-001",
                },
                "workspace": str(OPENCLAW_HOME / "workspace"),
                "compaction": {"mode": "safeguard"},
                "timeoutSeconds": 300,
            },
            "list": agent_list,
        },
        "gateway": {
            "port": 18789,
            "mode": "local",
            "bind": "loopback",
            "auth": {
                "mode": "token",
                "token": "env:OPENCLAW_GATEWAY_TOKEN",
            },
        },
        "exec": {
            "ask": "on-miss",
        },
        "acp": {
            "enabled": True,
        },
    }


def _setup_workspaces():
    """Copy SOUL.md and create workspace files for each agent."""
    for agent in AGENTS:
        aid = agent["id"]
        ws = OPENCLAW_HOME / "agents" / aid / "workspace"
        ws.mkdir(parents=True, exist_ok=True)

        # Copy SOUL.md from repo
        soul_src = SOULS_DIR / agent["soul"]
        soul_dst = ws / "SOUL.md"
        if soul_src.exists():
            shutil.copy2(soul_src, soul_dst)
            print(f"  [+] {soul_dst}")
        else:
            print(f"  [!] Missing soul file: {soul_src}")

        # Write IDENTITY.md
        identity_content = f"""# IDENTITY.md — {agent['name']}

- **Name:** {agent['name']}
- **Agent ID:** {aid}
- **Role:** {agent['role']}
- **Emoji:** {agent['emoji']}
- **Catchphrase:** "{agent['catchphrase']}"

## Pipeline Position

You are one of 3 agents in the **DiamondClaws** system, a multi-agent equity research platform. You run as a real OpenClaw agent instance with your own workspace, tools, and memory.

- **Gateway:** OpenClaw on port 18789 routes messages to you
- **Web UI:** DiamondClaws on port 8000 renders your responses
- **Peers:** {', '.join(f"{a['name']} ({a['id']})" for a in AGENTS if a['id'] != aid)}
"""
        _write_text(ws / "IDENTITY.md", identity_content)

        # Write AGENTS.md (workspace readme)
        agents_md = """# AGENTS.md - Your Workspace

This folder is home. Treat it that way.

## Session Startup

Before doing anything else:

1. Read `SOUL.md` — this is who you are
2. Read `IDENTITY.md` — your agent identity and pipeline position
3. Read `memory/` for recent context if it exists

## Memory

You wake up fresh each session. These files are your continuity:

- **Daily notes:** `memory/YYYY-MM-DD.md` — raw logs of what happened
- **Long-term:** `MEMORY.md` — your curated memories

Capture what matters. Decisions, context, things to remember.
"""
        _write_text(ws / "AGENTS.md", agents_md)

        # Create empty memory dir marker
        (ws / "memory").mkdir(parents=True, exist_ok=True)


def _setup_auth_profiles():
    """Write auth-profiles.json for each agent pointing to env vars."""
    model_config = {
        "providers": {
            "openrouter": {
                "baseUrl": "https://openrouter.ai/api/v1",
                "api": "openai-completions",
                "apiKey": "env:OPENROUTER_API_KEY",
                "models": [
                    {
                        "id": "google/gemini-2.0-flash-001",
                        "name": "Gemini 2.0 Flash",
                        "reasoning": False,
                        "input": ["text"],
                        "cost": {"input": 0.1, "output": 0.4, "cacheRead": 0, "cacheWrite": 0},
                        "contextWindow": 1048576,
                        "maxTokens": 8192,
                    },
                ],
            },
        },
    }

    auth_profile = {
        "version": 1,
        "profiles": {
            "openrouter:default": {
                "type": "api_key",
                "provider": "openrouter",
                "key": "env:OPENROUTER_API_KEY",
            },
        },
        "lastGood": {
            "openrouter": "openrouter:default",
        },
    }

    for agent in AGENTS:
        aid = agent["id"]
        agent_dir = OPENCLAW_HOME / "agents" / aid / "agent"
        agent_dir.mkdir(parents=True, exist_ok=True)

        _write_json(agent_dir / "models.json", model_config)
        _write_json(agent_dir / "auth-profiles.json", auth_profile)


if __name__ == "__main__":
    setup()
