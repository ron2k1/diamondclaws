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
    full_text = ""
    last_event = None
    async for event in stream_agent_message(agent_id, message, timeout_ms=timeout_ms):
        if event["type"] == "token":
            full_text += event["text"]
        elif event["type"] == "error":
            return {"ok": False, "error": event["error"], "routed_via": "openclaw-gateway"}
        last_event = event

    if last_event and last_event["type"] == "done":
        return {
            "ok": True,
            "text": last_event.get("text", full_text),
            "agent_id": agent_id,
            "run_id": last_event.get("run_id"),
            "session_key": last_event.get("session_key"),
            "routed_via": "openclaw-gateway",
        }
    return {"ok": bool(full_text), "text": full_text, "agent_id": agent_id, "routed_via": "openclaw-gateway"}


async def stream_agent_message(
    agent_id: str,
    message: str,
    session_key: str | None = None,
    timeout_ms: int = 60000,
):
    """Stream events from an agent via the real OpenClaw gateway.

    Async generator yielding dicts:
      {"type": "token", "text": "..."}        — response text (incremental or full)
      {"type": "tool_use", "name": "..."}     — agent is executing a tool
      {"type": "tool_result", "name": "..."}  — tool finished
      {"type": "done", "text": "...", "agent_id": "...", "run_id": "...", "session_key": "..."}
      {"type": "error", "error": "..."}
    """
    try:
        ws = await _connect_ws()
        if not ws:
            yield {"type": "error", "error": "Gateway unreachable or no device identity"}
            return

        async with ws:
            # Session key format: agent:{agentId}:{sessionName}
            if not session_key:
                session_key = f"agent:{agent_id}:webchat-{uuid.uuid4().hex[:8]}"
            idem = str(uuid.uuid4())

            resp = await _request(ws, "agent", {
                "message": message,
                "sessionKey": session_key,
                "idempotencyKey": idem,
                "deliver": False,
                "channel": "webchat",
            }, timeout=15)

            if not resp.get("ok"):
                yield {"type": "error", "error": resp.get("error", {}).get("message", "agent request failed")}
                return

            run_id = resp.get("payload", {}).get("runId")
            if not run_id:
                yield {"type": "error", "error": "no run ID returned"}
                return

            response_text = ""
            deadline = time.time() + (timeout_ms / 1000)

            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(
                        ws.recv(), timeout=min(5, deadline - time.time())
                    )
                    msg = json.loads(raw)

                    if msg.get("type") == "event":
                        evt = msg.get("event", "")
                        payload = msg.get("payload", {})

                        if evt == "chat":
                            state = payload.get("state", "")
                            if state == "error":
                                yield {"type": "error", "error": payload.get("errorMessage", "agent error")}
                                return

                            # Gateway sends state:"delta"/"final" with message.content[].text
                            # Each delta contains full text up to that point (not incremental)
                            message_obj = payload.get("message", {})
                            content_blocks = message_obj.get("content", [])
                            if isinstance(content_blocks, list):
                                content = " ".join(
                                    c.get("text", "") for c in content_blocks if c.get("type") == "text"
                                )
                            elif isinstance(content_blocks, str):
                                content = content_blocks
                            else:
                                content = ""

                            if content and content != response_text:
                                # Yield only the new delta
                                if content.startswith(response_text):
                                    delta = content[len(response_text):]
                                else:
                                    delta = content
                                if delta:
                                    yield {"type": "token", "text": delta}
                                response_text = content

                        elif evt == "tool":
                            name = payload.get("name", payload.get("toolName", ""))
                            status = payload.get("status", "")
                            if status in ("running", "start"):
                                yield {"type": "tool_use", "name": name}
                            elif status in ("done", "ok", "complete"):
                                yield {"type": "tool_result", "name": name}

                        elif evt == "agent":
                            status = payload.get("status", "")
                            if status in ("ok", "done", "complete"):
                                break

                    elif msg.get("type") == "res":
                        p = msg.get("payload", {})
                        if p.get("status") == "ok":
                            break

                except asyncio.TimeoutError:
                    continue

            # Fallback: fetch from session history if no streaming content
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
                                yield {"type": "token", "text": response_text}
                                break
                except Exception:
                    pass

            yield {
                "type": "done",
                "text": response_text,
                "agent_id": agent_id,
                "run_id": run_id,
                "session_key": session_key,
            }

    except Exception as e:
        yield {"type": "error", "error": str(e)}
