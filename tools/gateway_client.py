"""Real OpenClaw gateway WebSocket client.

Connects to the OpenClaw gateway using device identity authentication
(Ed25519 signed challenge-response). Provides health checks and agent
routing through the actual gateway protocol v3.
"""

import asyncio
import base64
import json
import os
import time
import uuid
from pathlib import Path
from typing import Optional

GATEWAY_URL = os.getenv("OPENCLAW_GATEWAY_URL", "ws://127.0.0.1:18789")
IDENTITY_PATH = Path.home() / ".openclaw" / "identity" / "device.json"


def _load_device_identity() -> Optional[dict]:
    """Load device identity keypair from ~/.openclaw/identity/device.json."""
    if not IDENTITY_PATH.exists():
        return None
    try:
        return json.loads(IDENTITY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def _sign_connect(device: dict, nonce: str) -> dict:
    """Build the signed device auth payload for connect handshake."""
    from cryptography.hazmat.primitives.serialization import (
        load_pem_private_key,
        load_pem_public_key,
        Encoding,
        PublicFormat,
    )

    pk = load_pem_private_key(device["privateKeyPem"].encode(), password=None)
    pub = load_pem_public_key(device["publicKeyPem"].encode())
    pub_raw = pub.public_bytes(Encoding.Raw, PublicFormat.Raw)
    pub_b64url = base64.urlsafe_b64encode(pub_raw).decode().rstrip("=")

    signed_at = int(time.time() * 1000)
    payload_str = "|".join([
        "v3",
        device["deviceId"],
        "gateway-client",
        "backend",
        "operator",
        "operator.admin",
        str(signed_at),
        "",  # token (empty)
        nonce,
        "win32",
        "",  # deviceFamily
    ])
    signature = pk.sign(payload_str.encode())
    sig_b64url = base64.urlsafe_b64encode(signature).decode().rstrip("=")

    return {
        "id": device["deviceId"],
        "publicKey": pub_b64url,
        "signature": sig_b64url,
        "signedAt": signed_at,
        "nonce": nonce,
    }


async def _connect_ws():
    """Connect and authenticate to the OpenClaw gateway. Returns websocket."""
    import websockets

    device = _load_device_identity()
    if not device:
        return None

    ws = await websockets.connect(GATEWAY_URL, open_timeout=5)

    # Get challenge
    raw = await asyncio.wait_for(ws.recv(), timeout=5)
    ch = json.loads(raw)
    nonce = ch["payload"]["nonce"]

    # Authenticate with device identity
    device_auth = _sign_connect(device, nonce)
    connect_msg = {
        "type": "req",
        "id": str(uuid.uuid4()),
        "method": "connect",
        "params": {
            "minProtocol": 3,
            "maxProtocol": 3,
            "client": {
                "id": "gateway-client",
                "version": "1.0.0",
                "platform": "win32",
                "mode": "backend",
            },
            "role": "operator",
            "scopes": ["operator.admin"],
            "device": device_auth,
        },
    }
    await ws.send(json.dumps(connect_msg))
    resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))

    if not resp.get("ok"):
        await ws.close()
        return None

    return ws


async def _request(ws, method: str, params: dict, timeout: float = 10) -> dict:
    """Send a request and wait for the matching response."""
    rid = str(uuid.uuid4())
    await ws.send(json.dumps({"type": "req", "id": rid, "method": method, "params": params}))
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        msg = json.loads(raw)
        if msg.get("type") == "res" and msg.get("id") == rid:
            return msg


async def probe_gateway() -> dict:
    """Probe the real OpenClaw gateway. Returns status dict."""
    try:
        ws = await _connect_ws()
        if not ws:
            return {"running": False, "reason": "no device identity"}

        async with ws:
            # Health check
            health = await _request(ws, "health", {})
            health_payload = health.get("payload", {})

            # Agents list
            agents_resp = await _request(ws, "agents.list", {})
            agents_payload = agents_resp.get("payload", {})
            agents = agents_payload.get("agents", [])

            diamond_agents = [
                a for a in agents if (a.get("id") or a.get("agentId") or "").startswith("diamond-")
            ]

            return {
                "running": True,
                "version": health_payload.get("version", "unknown"),
                "uptime_ms": health_payload.get("uptimeMs", 0),
                "agents": [a.get("id") or a.get("agentId") or "?" for a in agents],
                "diamond_agents": [a.get("id") or a.get("agentId") or "?" for a in diamond_agents],
                "agent_count": len(agents),
                "diamond_count": len(diamond_agents),
                "default_agent": agents_payload.get("defaultAgentId", "main"),
                "channels": list(health_payload.get("channels", {}).keys()),
            }
    except Exception as e:
        return {"running": False, "reason": str(e)}


async def send_agent_message(agent_id: str, message: str, timeout_ms: int = 30000) -> dict:
    """Send a message to an agent via the real OpenClaw gateway.

    Returns the agent's response text and metadata.
    """
    try:
        ws = await _connect_ws()
        if not ws:
            return {"ok": False, "error": "no device identity or gateway unreachable"}

        async with ws:
            session_key = f"{agent_id}:webchat:diamondclaws:{uuid.uuid4().hex[:8]}"
            idem = str(uuid.uuid4())

            # Send agent request
            resp = await _request(ws, "agent", {
                "message": message,
                "sessionKey": session_key,
                "idempotencyKey": idem,
                "deliver": False,
                "channel": "webchat",
            }, timeout=15)

            if not resp.get("ok"):
                return {"ok": False, "error": resp.get("error", {}).get("message", "unknown error")}

            run_id = resp.get("payload", {}).get("runId")
            if not run_id:
                return {"ok": False, "error": "no run ID returned"}

            # Collect events until done
            response_text = ""
            events = []
            deadline = time.time() + (timeout_ms / 1000)

            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=min(5, deadline - time.time()))
                    msg = json.loads(raw)

                    if msg.get("type") == "event":
                        evt = msg.get("event", "")
                        payload = msg.get("payload", {})

                        if evt == "chat":
                            # Check for completion or error
                            state = payload.get("state", "")
                            if state == "error":
                                return {
                                    "ok": False,
                                    "error": payload.get("errorMessage", "agent error"),
                                    "routed_via": "openclaw-gateway",
                                }
                            # Try to get response text
                            reply = payload.get("reply", {})
                            if isinstance(reply, dict):
                                content = reply.get("content", "")
                                if content:
                                    response_text = content
                        elif evt == "agent":
                            status = payload.get("status", "")
                            if status in ("ok", "done", "complete"):
                                break

                    elif msg.get("type") == "res":
                        # agent.wait response
                        p = msg.get("payload", {})
                        if p.get("status") == "ok":
                            break

                except asyncio.TimeoutError:
                    continue

            # Get final response from chat history
            if not response_text:
                try:
                    hist = await _request(ws, "chat.history", {"sessionKey": session_key}, timeout=5)
                    messages = hist.get("payload", {}).get("messages", [])
                    for m in reversed(messages):
                        if m.get("role") == "assistant":
                            content = m.get("content", "")
                            if isinstance(content, list):
                                response_text = " ".join(
                                    c.get("text", "") for c in content if c.get("type") == "text"
                                )
                            elif isinstance(content, str):
                                response_text = content
                            if response_text:
                                break
                except Exception:
                    pass

            return {
                "ok": True,
                "text": response_text,
                "agent_id": agent_id,
                "run_id": run_id,
                "session_key": session_key,
                "routed_via": "openclaw-gateway",
            }

    except Exception as e:
        return {"ok": False, "error": str(e)}
